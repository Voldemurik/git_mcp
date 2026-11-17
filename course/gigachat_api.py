"""Dependency-free GigaChat v1 Function Calling transport.

Uses the officially documented OAuth and /v1/chat/completions endpoints.
Only obtains tokens in memory; never logs or persists credentials.
"""
from __future__ import annotations

import json
import re
import os
import ssl
import uuid
from urllib import error, parse, request
from pathlib import Path

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://api.giga.chat/v1/chat/completions"


class GigaChatError(RuntimeError):
    pass


def _ssl_context():
    # Preserve system roots for any public HTTPS endpoints and add the extra CA
    # only when explicitly configured (never disable hostname validation).
    ctx = ssl.create_default_context()
    bundle = os.getenv("GIGACHAT_CA_BUNDLE", "").strip()
    if bundle:
        path = Path(bundle)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        ctx.load_verify_locations(cafile=str(path))
    return ctx


def _post(url: str, body: bytes, headers: dict) -> dict:
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, context=_ssl_context(), timeout=90) as response:
            return json.load(response)
    except error.HTTPError as exc:
        # Read ONLY the API error description. Never print request bodies, tokens,
        # headers, or the raw provider response (which may echo user input).
        detail = "no structured error message"
        try:
            data = json.loads(exc.read(8192).decode("utf-8", "replace"))
            if isinstance(data, dict):
                candidate = data.get("message") or data.get("detail") or data.get("error_description")
                if isinstance(candidate, str):
                    detail = candidate
                elif isinstance(candidate, dict):
                    detail = str(candidate.get("message") or candidate.get("type") or detail)
        except (ValueError, UnicodeError, OSError):
            pass
        # A server-side validation error might contain part of a request.
        # Keep only a short, human-readable hint with secrets scrubbed.
        for secret in (os.getenv("GIGACHAT_CREDENTIALS", ""), os.getenv("GIGACHAT_ACCESS_TOKEN", "")):
            if len(secret) >= 8:
                detail = detail.replace(secret, "[REDACTED]")
        detail = re.sub(r"(?i)(bearer|basic)\s+[A-Za-z0-9._~+/-]{12,}", r"\1 [REDACTED]", detail)
        detail = re.sub(r"[A-Za-z0-9+/=_-]{80,}", "[REDACTED_LONG_VALUE]", detail)
        raise GigaChatError(f"GigaChat HTTP {exc.code}: {detail[:450]}") from None
    except error.URLError as exc:
        raise GigaChatError(f"GigaChat connection/TLS error: {exc.reason}") from None


class GigaChatAPI:
    def __init__(self):
        self.token = os.getenv("GIGACHAT_ACCESS_TOKEN", "").strip()
        self.credentials = os.getenv("GIGACHAT_CREDENTIALS", "").strip()
        self.scope = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
        self.model = os.getenv("GIGACHAT_MODEL", "GigaChat-2-Pro")
        # Only the last raw API usage; students implement their OWN accounting.
        self.last_usage: dict | None = None
        if not self.token and not self.credentials:
            raise GigaChatError("Set GIGACHAT_CREDENTIALS or GIGACHAT_ACCESS_TOKEN in .env")

    def _auth(self):
        if self.token:
            return
        cred = self.credentials
        if cred.lower().startswith("basic "):
            cred = cred[6:].strip()
        response = _post(OAUTH_URL, parse.urlencode({"scope": self.scope}).encode(), {
            "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": "Basic " + cred, "RqUID": str(uuid.uuid4()),
        })
        self.token = response["access_token"]

    def complete(self, messages: list[dict], tools: list[dict], *, force_function: str | None = None) -> dict:
        """Call GigaChat; optionally REQUIRE one advertised function.

        Forced calls are reserved for an explicitly audited last-resort retry,
        never silently counted as independent model tool selection.
        """
        self.last_usage = None  # Never reuse stale usage after a failed request.
        self._auth()
        functions = [
            {"name": t["name"], "description": t.get("description") or t["name"],
             "parameters": t["parameters"] if "parameters" in t else t["inputSchema"]}
            for t in tools
        ]
        if force_function is not None and force_function not in {f["name"] for f in functions}:
            raise GigaChatError("Forced function must exist in advertised functions")
        payload = {"model": self.model, "messages": messages, "functions": functions,
                   "function_call": ({"name": force_function} if force_function else "auto"),
                   "stream": False}
        response = _post(CHAT_URL, json.dumps(payload, ensure_ascii=False).encode(), {
            "Content-Type": "application/json", "Accept": "application/json",
            "Authorization": "Bearer " + self.token,
        })
        # Expose raw response usage without doing the student's aggregation.
        usage = response.get("usage")
        self.last_usage = dict(usage) if isinstance(usage, dict) else None
        # Preserve the existing return contract for working agents.
        return response["choices"][0]["message"]


def _giga_property(schema: dict, depth: int = 0) -> dict:
    """Convert general MCP JSON Schema to a conservative GigaChat-compatible subset.

    Original MCP schemas are NOT changed: only descriptions advertised to the LLM
    are simplified. Validation/authorization remains on the actual MCP server.
    """
    if not isinstance(schema, dict) or depth > 8:
        return {"type": "string"}
    typ = schema.get("type", "string")
    if isinstance(typ, list):
        typ = next((t for t in typ if t != "null"), "string")
    if typ not in ("object", "array", "string", "integer", "number", "boolean"):
        typ = "string"
    result = {"type": typ}
    if isinstance(schema.get("description"), str):
        result["description"] = schema["description"][:500]
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        result["enum"] = schema["enum"]
    if typ == "object":
        props = schema.get("properties", {})
        if not isinstance(props, dict):
            props = {}
        result["properties"] = {k: _giga_property(v, depth + 1) for k,v in props.items()}
        required = schema.get("required", [])
        if isinstance(required, list):
            result["required"] = [k for k in required if k in props]
        # Mapping-like arguments (additionalProperties being an object) are
        # retained as generic object input; the server validates the actual keys.
        # The agent rarely needs this one: analyze_case is invoked by the host.
    if typ == "array":
        result["items"] = _giga_property(schema.get("items", {"type":"string"}), depth + 1)
    return result


def to_gigachat_functions(tools: list[dict]) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """Map internal MCP aliases to letter-only public names for GigaChat.

    Avoids protocol-specific separators and unsupported JSON Schema keywords.
    Returns (advertised tools, public->internal, internal->public).
    """
    funcs, public_to_internal, internal_to_public = [], {}, {}
    for t in tools:
        internal = t["name"]
        words = re.findall(r"[A-Za-z]+", internal)
        public = "".join(w.capitalize() for w in words)
        if not public or public in public_to_internal:
            raise GigaChatError("Tool names cannot be uniquely mapped to GigaChat: " + internal)
        schema = t.get("inputSchema", {})
        normalized = _giga_property(schema if isinstance(schema,dict) else {"type":"object"})
        if normalized["type"] != "object":
            normalized = {"type":"object", "properties":{}, "required":[]}
        funcs.append({"name":public,
                      "description":(t.get("description") or internal)[:1500],
                      "parameters":normalized})
        public_to_internal[public] = internal
        internal_to_public[internal] = public
    return funcs, public_to_internal, internal_to_public

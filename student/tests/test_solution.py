"""Локальные тесты решения P04: предметный MCP, цикл агента, учёт токенов.

Запуск (из корня репозитория):
    python -m unittest student.tests.test_solution -v

Все тесты идут БЕЗ реального GigaChat: модель заменяется детерминированным
FakeGigaChat, который возвращает function_call с ПУБЛИЧНЫМИ именами функций —
так проверяется маршрутизация имён и аргументов, политика фаз и аудит.
Интеграционный тест полного прогона использует настоящие MCP-процессы
(свой stdio-сервер и готовый Filesystem через npx) и офлайн-проверки Checker.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import student.agent as agent
from course.gigachat_api import GigaChatError
from course.protocol import MCPStdio, child_env, content_json, content_text

ROOT = Path(__file__).resolve().parents[2]


def fc(name: str, args: dict | None = None) -> dict:
    """Сообщение модели с function_call (имя — публичное, как у GigaChat)."""
    return {"role": "assistant", "content": "",
            "function_call": {"name": name, "arguments": args or {}}}


def text(content: str) -> dict:
    return {"role": "assistant", "content": content}


class FakeGigaChat:
    """Сценарная модель: отдаёт заранее заданные сообщения и правдоподобный usage."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[tuple[list, list]] = []
        self.last_usage: dict | None = None

    def complete(self, messages, functions, *, force_function=None):
        self.calls.append((json.loads(json.dumps(messages, default=str)), functions))
        if not self.script:
            self.last_usage = {"prompt_tokens": 100, "completion_tokens": 20,
                               "total_tokens": 120, "precached_prompt_tokens": 5}
            return text("Готово.")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            self.last_usage = None
            raise item
        self.last_usage = {"prompt_tokens": 100, "completion_tokens": 20,
                           "total_tokens": 120, "precached_prompt_tokens": 5}
        return item


class FakeReady:
    """Мини-клиент готового MCP: один читающий инструмент, запоминает аргументы."""

    def __init__(self, reply: str = "Считать Recall@3. Релевантные непросмотренные: B,D."):
        self.reply = reply
        self.calls: list[tuple[str, dict]] = []

    def list_tools(self):
        return [{"name": "read_text_file",
                 "description": "Read a text file inside the allowed directory.",
                 "inputSchema": {"type": "object",
                                 "properties": {"path": {"type": "string"}},
                                 "required": ["path"]}}]

    def call(self, name, args):
        self.calls.append((name, args))
        if name != "read_text_file" or not isinstance(args, dict) or not args.get("path"):
            return {"isError": True,
                    "content": [{"type": "text", "text": "path is required"}]}
        return {"isError": False, "content": [{"type": "text", "text": self.reply}]}


def _audit_entries(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _temp_repo_copy() -> Path:
    """Изолированная копия репозитория для тестов, пишущих файлы."""
    tmp = Path(tempfile.mkdtemp(prefix="p04_test_"))
    shutil.copytree(ROOT, tmp / "repo",
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "llm-mcp-result"))
    return tmp / "repo"


class OwnServerProtocolTests(unittest.TestCase):
    """Предметный сервер — только через настоящий MCP JSON-RPC stdio."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="p04_own_"))
        shutil.copytree(ROOT / "student", cls.tmp / "student",
                        ignore=shutil.ignore_patterns("__pycache__", "tests"))
        shutil.copytree(ROOT / "case", cls.tmp / "case")
        cls.cmd = [sys.executable, "-u", "-m", "student.own_server"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _server(self):
        return MCPStdio(self.cmd, self.tmp, child_env(self.tmp), timeout=20)

    def test_tools_list_and_domain_result(self):
        with self._server() as srv:
            names = [t["name"] for t in srv.list_tools()]
            self.assertEqual(set(names), {"health_check", "get_user_data",
                                          "clean_recommendations", "save_result"})
            obj = content_json(srv.call("clean_recommendations", {}))
            self.assertEqual(obj["case_id"], "P04")
            self.assertEqual(obj["status"], "completed")
            u1 = obj["result"]["users"]["U1"]
            self.assertEqual(u1["cleaned_top_k"], ["B", "C"])
            self.assertEqual(u1["k"], 3)
            self.assertEqual(u1["relevant_items"], ["B", "D"])
            self.assertEqual(u1["hits"], ["B"])
            self.assertAlmostEqual(u1["recall_at_k"], 0.5)
            reasons = {r["reason"] for r in u1["removed"]}
            self.assertEqual(reasons, {"already_seen", "duplicate", "not_in_catalog"})
            self.assertAlmostEqual(obj["result"]["mean_recall_at_k"], 0.5)
            self.assertTrue(obj["checks"]["domain_passed"])
            self.assertGreaterEqual(len(obj["report_md"]), 60)

    def test_save_writes_only_outputs_and_rejects_args(self):
        with self._server() as srv:
            bad = srv.call("get_user_data", {"path": "/etc/passwd"})
            self.assertTrue(bad.get("isError"), "аргументы у own-инструментов запрещены")
            saved = content_json(srv.call("save_result", {}))
            self.assertEqual(saved["status"], "saved")
            out = self.tmp / "llm-mcp-result" / "outputs"
            self.assertTrue((out / "result.json").is_file())
            self.assertTrue((out / "report.md").is_file())
            stored = json.loads((out / "result.json").read_text(encoding="utf-8"))
            for field in ("case_id", "status", "sources", "result", "checks"):
                self.assertIn(field, stored)
            self.assertNotIn("report_md", stored)
            self.assertFalse((self.tmp / "case" / "data" / "catalog.csv").read_bytes()
                             .startswith(b"CHANGED"))


class FunctionLoopTests(unittest.TestCase):
    """Маршрутизация публичных имён GigaChat, аргументы, политика Plan, аудит."""

    def setUp(self):
        agent.TOKEN_USAGE = agent.TokenUsage()
        self.tmp = Path(tempfile.mkdtemp(prefix="p04_loop_"))
        self.audit_path = self.tmp / "audit.jsonl"
        self.audit_path.write_text("", encoding="utf-8")
        self.ready = FakeReady()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _own(self):
        return MCPStdio([sys.executable, "-u", "-m", "student.own_server"],
                        ROOT, child_env(ROOT), timeout=20)

    def test_public_names_routed_and_args_passed(self):
        metric_path = str(ROOT / "case" / "docs" / "metric.md")
        giga = FakeGigaChat([fc("OwnGetUserData"),
                             fc("ReadyReadTextFile", {"path": metric_path}),
                             text("План: очистить дубликаты, просмотренные и не-каталог; Recall@3.")])
        with self._own() as own:
            plan = agent.plan_phase(giga, self.ready, own, self.audit_path)
        self.assertIn("План", plan)
        # Аргументы модели ДОШЛИ до готового MCP (главная регрессия).
        self.assertEqual(self.ready.calls, [("read_text_file", {"path": metric_path})])
        entries = _audit_entries(self.audit_path)
        model_ok = [e for e in entries if e.get("event") == "tool_completed"
                    and e.get("actor") == "model" and e.get("status") == "ok"]
        self.assertTrue(any(e["server"] == "own" and e["name"] == "get_user_data"
                            for e in model_ok))
        self.assertTrue(any(e["server"] == "ready" and e["name"] == "read_text_file"
                            for e in model_ok))
        # Запрещённая запись в Plan заблокирована кодом (самопроверка хоста).
        self.assertTrue(any(e.get("event") == "policy_selftest"
                            and e.get("forbidden_write_blocked") is True for e in entries))
        # Ни одной записи operation="write" в Plan (требование Checker).
        self.assertFalse(any(e.get("phase") == "plan" and e.get("operation") == "write"
                             for e in entries))
        # Функции, объявленные модели, не содержат подчёркиваний.
        for _messages, functions in giga.calls:
            for f in functions:
                self.assertNotIn("_", f["name"])
        self.assertEqual(agent.TOKEN_USAGE.requests_total, 3)

    def test_model_write_attempt_in_plan_is_denied(self):
        giga = FakeGigaChat([fc("OwnSaveResult"), text("План без записи.")])
        with self._own() as own:
            agent.plan_phase(giga, self.ready, own, self.audit_path)
        entries = _audit_entries(self.audit_path)
        denied = [e for e in entries if e.get("status") == "denied"
                  and e.get("reason") == "write_forbidden_in_plan"
                  and e.get("actor") == "model"]
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[0].get("operation"), "write_denied")
        # Запись не состоялась: ни одного успешного save_result в журнале.
        self.assertFalse(any(e.get("name") == "save_result" and e.get("status") == "ok"
                             for e in entries))
        # Модель получила ошибку инструмента в истории (роль function).
        last_messages = giga.calls[-1][0]
        self.assertTrue(any(m.get("role") == "function" and "denied" in m.get("content", "")
                            for m in last_messages))

    def test_unknown_tool_is_denied_not_executed(self):
        giga = FakeGigaChat([fc("OwnDropDatabase"), text("План.")])
        with self._own() as own:
            agent.plan_phase(giga, self.ready, own, self.audit_path)
        entries = _audit_entries(self.audit_path)
        self.assertTrue(any(e.get("status") == "denied" and e.get("reason") == "unknown_tool"
                            for e in entries))


class TokenUsageTests(unittest.TestCase):
    def setUp(self):
        self.usage = agent.TokenUsage()

    def test_accumulation_by_phase_and_failed_requests(self):
        giga = FakeGigaChat([])
        self.usage.current_phase = "plan"
        giga.last_usage = {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
        self.usage.record(giga)
        self.usage.current_phase = "build"
        giga.last_usage = {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25,
                           "precached_prompt_tokens": 7}
        self.usage.record(giga)
        giga.last_usage = None
        self.usage.record(giga, failed=True)
        d = self.usage.to_dict()
        self.assertEqual(d["requests_total"], 3)
        self.assertEqual(d["requests_without_usage"], 1)
        self.assertEqual(d["phases"]["plan"]["prompt_tokens"], 10)
        self.assertEqual(d["phases"]["build"]["precached_prompt_tokens"], 7)
        self.assertEqual(d["phases"]["review"]["requests"], 0)
        self.assertEqual(d["totals"]["total_tokens"], 38)
        self.assertEqual(d["totals"]["prompt_tokens"], 30)

    def test_retry_counts_failed_attempt_and_succeeds(self):
        agent.TOKEN_USAGE = agent.TokenUsage()
        tmp = Path(tempfile.mkdtemp(prefix="p04_retry_"))
        try:
            giga = FakeGigaChat([GigaChatError("GigaChat HTTP 429: rate limit"),
                                 text("Ответ после повтора.")])
            with patch.object(agent.time, "sleep") as sleep:
                message = agent._complete_with_retry(giga, [], [], tmp / "a.jsonl", "plan")
            self.assertEqual(message["content"], "Ответ после повтора.")
            sleep.assert_called_once()
            d = agent.TOKEN_USAGE.to_dict()
            self.assertEqual(d["requests_total"], 2)
            self.assertEqual(d["requests_without_usage"], 1)
            self.assertEqual(d["phases"]["plan"]["requests"], 1)
            entries = _audit_entries(tmp / "a.jsonl")
            self.assertTrue(any(e.get("event") == "gigachat_retry" for e in entries))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_non_retryable_error_raises_immediately(self):
        agent.TOKEN_USAGE = agent.TokenUsage()
        tmp = Path(tempfile.mkdtemp(prefix="p04_err_"))
        try:
            giga = FakeGigaChat([GigaChatError("GigaChat HTTP 401: bad credentials"),
                                 text("не должно быть вызвано")])
            with patch.object(agent.time, "sleep") as sleep:
                with self.assertRaises(GigaChatError):
                    agent._complete_with_retry(giga, [], [], tmp / "a.jsonl", "plan")
            sleep.assert_not_called()
            self.assertEqual(agent.TOKEN_USAGE.requests_without_usage, 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class PreflightIntegrityTests(unittest.TestCase):
    def test_case_files_match_variant_hashes(self):
        from course.checker import preflight
        results = []
        preflight(ROOT, results)
        failed = [r for r in results if not r["passed"]]
        self.assertEqual(failed, [], str(failed))


@unittest.skipUnless(shutil.which("npx"), "npx/node недоступен — готовый Filesystem MCP не запустить")
class FullPipelineOfflineTests(unittest.TestCase):
    """Полный прогон main() с FakeGigaChat и ДВУМЯ настоящими MCP + проверки Checker."""

    def test_full_run_produces_valid_artifact(self):
        repo = _temp_repo_copy()
        self.addCleanup(shutil.rmtree, repo.parent, ignore_errors=True)
        metric_path = str(repo / "case" / "docs" / "metric.md")
        script = [
            # Plan: чтение через оба MCP, затем текст плана.
            fc("OwnGetUserData"),
            fc("ReadyReadTextFile", {"path": metric_path}),
            text("План: удалить повторы/просмотренные/не-каталог, взять top-3, "
                 "посчитать Recall@3 по relevance.json; Build сохранит, Review проверит."),
            # Build: предметный расчёт и разрешённая запись.
            fc("OwnCleanRecommendations"),
            fc("OwnSaveResult"),
            text("Сохранено: outputs/result.json и outputs/report.md; средний Recall@3 = 0.5."),
            # Review: критическое заключение по фактам хоста.
            text("Проверки хоста подтверждают результат: top-3 U1 = [B, C], Recall@3 = 0.5, "
                 "причины удалений покрыты. Результат допустим к сдаче."),
        ]
        giga = FakeGigaChat(script)
        agent.TOKEN_USAGE = agent.TokenUsage()
        argv = ["agent.py", "--case-dir", str(repo / "case"),
                "--report-dir", str(repo / "llm-mcp-result")]
        with (patch.object(agent, "ROOT", repo),
              patch.object(agent, "GigaChatAPI", return_value=giga),
              patch.object(sys, "argv", argv)):
            agent.main()

        out = repo / "llm-mcp-result"
        for name in ("manifest.json", "summary.json", "audit.jsonl", "plan.md",
                     "review.md", "token_usage.json",
                     "outputs/result.json", "outputs/report.md"):
            self.assertTrue((out / name).is_file(), name)

        # Офлайн-проверки самого Checker (live-часть без GigaChat-запросов).
        from course.checker import verify_live
        variant = json.loads((repo / "variant.json").read_text(encoding="utf-8"))
        results = []
        verify_live(repo, variant, results)
        failed = [r for r in results if not r["passed"]]
        self.assertEqual(failed, [], str(failed))

        # Учёт токенов: 7 запросов модели (3 plan + 3 build + 1 review).
        usage = json.loads((out / "token_usage.json").read_text(encoding="utf-8"))
        self.assertEqual(usage["requests_total"], 7)
        self.assertEqual(usage["requests_without_usage"], 0)
        self.assertEqual(usage["phases"]["plan"]["requests"], 3)
        self.assertEqual(usage["phases"]["build"]["requests"], 3)
        self.assertEqual(usage["phases"]["review"]["requests"], 1)
        self.assertEqual(usage["totals"]["total_tokens"], 840)
        self.assertEqual(usage["totals"]["precached_prompt_tokens"], 35)

        # Аудит: успешные model-вызовы обоих MCP и разрешённая запись в Build.
        entries = _audit_entries(out / "audit.jsonl")
        self.assertTrue(any(e.get("event") == "tool_completed" and e.get("actor") == "model"
                            and e.get("server") == "ready" and e.get("status") == "ok"
                            for e in entries))
        self.assertTrue(any(e.get("event") == "tool_completed" and e.get("actor") == "model"
                            and e.get("server") == "own" and e.get("name") == "save_result"
                            and e.get("operation") == "write" and e.get("phase") == "build"
                            for e in entries))
        self.assertFalse(any(e.get("phase") == "plan" and e.get("operation") == "write"
                             for e in entries))
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["backend"], "gigachat")
        self.assertIn("Расход токенов", (out / "review.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

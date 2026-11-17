"""Fetch official public trust root; pin its certificate DER SHA-256.

Only the one CA bootstrap request bypasses TLS verification because the
CA is not in the runner yet. The received certificate is authenticated by
its fixed fingerprint before it is trusted by the GigaChat client.
No credentials are involved in this step.
"""
from __future__ import annotations

import hashlib
import os
import ssl
import sys
from pathlib import Path
from urllib.request import urlopen

URL = "https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt"
# Russian Trusted Root CA certificate fingerprint (DER), expires 2032-02-27.
EXPECTED = "D26D2D0231B7C39F92CC738512BA54103519E4405D68B5BD703E9788CA8ECF31"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "certs" / "russian_trusted_root_ca_pem.crt"


def verify_pem(pem: str) -> str:
    if pem.count("-----BEGIN CERTIFICATE-----") != 1:
        raise ValueError("expected exactly one PEM certificate")
    der = ssl.PEM_cert_to_DER_cert(pem)
    fingerprint = hashlib.sha256(der).hexdigest().upper()
    if fingerprint != EXPECTED:
        raise ValueError("unexpected CA fingerprint; refuse to trust certificate")
    return fingerprint


def main() -> int:
    output = os.getenv("GIGACHAT_CA_BUNDLE", "").strip()
    path = Path(output) if output else DEFAULT
    if not path.is_absolute():
        path = ROOT / path
    if path.is_file():
        verify_pem(path.read_text(encoding="ascii"))
        print("GigaChat CA verified: already present")
        return 0
    # The download is intentionally limited to the public CA file. A pinned
    # fingerprint prevents a MITM from substituting another trust root.
    with urlopen(URL, timeout=20, context=ssl._create_unverified_context()) as response:
        raw = response.read(100_000)
    pem = raw.decode("ascii")
    verify_pem(pem)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pem, encoding="ascii")
    print("GigaChat CA verified: fingerprint matches pinned root")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"CA bootstrap failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

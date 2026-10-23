"""Inspect the actual TLS stores loaded inside a production container, offline."""

from __future__ import annotations

import hashlib
import ssl

import certifi

# emSign ECC Root CA - G3 and the Comodo AAA cross-signing trust path.
# https://emudhra.we-have-a-problem.com/#workarounds
DISTRUSTED_SHA256 = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",
}


def main() -> None:
    if tuple(map(int, certifi.__version__.split("."))) < (2026, 10, 23):
        raise RuntimeError(f"Unpatched certifi bundle: {certifi.__version__}")
    for name, context in (
        ("system", ssl.create_default_context()),
        ("certifi", ssl.create_default_context(cafile=certifi.where())),
    ):
        fingerprints = {
            hashlib.sha256(certificate).hexdigest()
            for certificate in context.get_ca_certs(binary_form=True)
        }
        if not fingerprints:
            raise RuntimeError(f"{name} trust store is empty")
        if fingerprints & DISTRUSTED_SHA256:
            raise RuntimeError(f"{name} still trusts an eMudhra compromise trust path")
        print(f"{name}: checked {len(fingerprints)} roots; distrusted paths absent")


if __name__ == "__main__":
    main()

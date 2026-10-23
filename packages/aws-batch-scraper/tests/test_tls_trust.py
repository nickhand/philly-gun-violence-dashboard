"""Keep AWS requests on the reviewed certificate bundle."""

import hashlib
import ssl

import certifi
from botocore.httpsession import get_cert_path


def test_botocore_uses_certifi_without_compromised_root_paths() -> None:
    """Cover botocore's optional-certifi fallback as well as bundle contents."""
    assert get_cert_path(True) == certifi.where()
    trusted = {
        hashlib.sha256(certificate).hexdigest()
        for certificate in ssl.create_default_context(cafile=get_cert_path(True)).get_ca_certs(
            binary_form=True
        )
    }
    # https://emudhra.we-have-a-problem.com/roots.json
    compromised_root_paths = {
        "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",  # emSign G3
        "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",  # AAA cross-sign
    }
    assert trusted
    assert trusted.isdisjoint(compromised_root_paths)

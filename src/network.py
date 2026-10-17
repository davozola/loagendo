"""Shared HTTPS transport settings; never disables certificate validation."""
from __future__ import annotations

import ssl
from pathlib import Path


EXTRA_CA = Path(__file__).resolve().parents[1] / 'config' / 'extra-ca.pem'


def tls_context():
    """Use the configured CA store, or macOS's system bundle when Homebrew's
    Python points at a missing OpenSSL bundle, plus the operator's extra CA
    certificates (config/extra-ca.pem) for hosts whose chain the bundle lacks.
    Verification remains required: nothing here disables it.
    """
    # Python's own bundle (Homebrew OpenSSL on macOS) plus the OS bundle when
    # present: each knows CAs the other lacks (gencat.cat verified with one but
    # not the other). Loading is additive, so both are trusted together.
    context = ssl.create_default_context()
    system_bundle = Path('/etc/ssl/cert.pem')
    if system_bundle.is_file():
        try: context.load_verify_locations(cafile=str(system_bundle))
        except ssl.SSLError: pass
    try:
        certifi = __import__('certifi')  # optional, never required
        context.load_verify_locations(cafile=certifi.where())
    except Exception: pass
    if EXTRA_CA.is_file():
        try: context.load_verify_locations(cafile=str(EXTRA_CA))
        except ssl.SSLError: pass
    return context

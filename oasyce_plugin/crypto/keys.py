"""
Ed25519 key management and signing utilities.

Uses oasyce_core if available, otherwise falls back to built-in
implementation using the `cryptography` library (already a dependency).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from cryptography.exceptions import InvalidSignature

DEFAULT_KEY_DIR = os.path.join(os.path.expanduser("~"), ".oasyce", "keys")


def generate_keypair() -> Tuple[str, str]:
    """Generate an Ed25519 keypair.

    Returns:
        (private_key_hex, public_key_hex)
    """
    private_key = Ed25519PrivateKey.generate()
    priv_bytes = private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    pub_bytes = private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    return priv_bytes.hex(), pub_bytes.hex()


def load_or_create_keypair(key_dir: str = DEFAULT_KEY_DIR) -> Tuple[str, str]:
    """Load an Ed25519 keypair from *key_dir*, creating one if missing.

    Files stored: ``private.key`` and ``public.key`` (hex-encoded).

    Returns:
        (private_key_hex, public_key_hex)
    """
    key_path = Path(key_dir)
    priv_file = key_path / "private.key"
    pub_file = key_path / "public.key"

    if priv_file.exists() and pub_file.exists():
        priv_hex = priv_file.read_text().strip()
        pub_hex = pub_file.read_text().strip()
        return priv_hex, pub_hex

    key_path.mkdir(parents=True, exist_ok=True)
    priv_hex, pub_hex = generate_keypair()
    priv_file.write_text(priv_hex)
    pub_file.write_text(pub_hex)
    return priv_hex, pub_hex


def sign(message: bytes, private_key_hex: str) -> str:
    """Sign *message* with an Ed25519 private key.

    Returns:
        Signature as a hex string.
    """
    priv_bytes = bytes.fromhex(private_key_hex)
    private_key = Ed25519PrivateKey.from_private_bytes(priv_bytes)
    sig = private_key.sign(message)
    return sig.hex()


def verify(message: bytes, signature_hex: str, public_key_hex: str) -> bool:
    """Verify an Ed25519 signature.

    Returns:
        ``True`` if valid, ``False`` otherwise.
    """
    try:
        pub_bytes = bytes.fromhex(public_key_hex)
        public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        sig_bytes = bytes.fromhex(signature_hex)
        public_key.verify(sig_bytes, message)
        return True
    except (InvalidSignature, ValueError):
        return False

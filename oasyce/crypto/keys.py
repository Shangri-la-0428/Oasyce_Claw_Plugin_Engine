"""
Ed25519 key management and signing utilities.

Uses oasyce_core if available, otherwise falls back to built-in
implementation using the `cryptography` library (already a dependency).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

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
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidSignature

DEFAULT_KEY_DIR = os.path.join(os.path.expanduser("~"), ".oasyce", "keys")

_PBKDF2_ITERATIONS = 480_000
_PBKDF2_KEY_LENGTH = 32
_SALT_LENGTH = 16
_NONCE_LENGTH = 12  # AES-GCM standard nonce size


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte encryption key from *passphrase* using PBKDF2HMAC/SHA256."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_PBKDF2_KEY_LENGTH,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _encrypt_key(private_key_hex: str, passphrase: str) -> bytes:
    """Encrypt *private_key_hex* with AES-GCM using a PBKDF2-derived key.

    Returns:
        ``salt (16 bytes) + nonce (12 bytes) + ciphertext`` as a single
        bytestring.
    """
    salt = os.urandom(_SALT_LENGTH)
    derived = _derive_key(passphrase, salt)
    nonce = os.urandom(_NONCE_LENGTH)
    aesgcm = AESGCM(derived)
    ciphertext = aesgcm.encrypt(nonce, private_key_hex.encode("utf-8"), None)
    return salt + nonce + ciphertext


def _decrypt_key(encrypted: bytes, passphrase: str) -> str:
    """Decrypt a blob produced by :func:`_encrypt_key`.

    Returns:
        The original private-key hex string.
    """
    salt = encrypted[:_SALT_LENGTH]
    nonce = encrypted[_SALT_LENGTH : _SALT_LENGTH + _NONCE_LENGTH]
    ciphertext = encrypted[_SALT_LENGTH + _NONCE_LENGTH :]
    derived = _derive_key(passphrase, salt)
    aesgcm = AESGCM(derived)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


def generate_keypair() -> Tuple[str, str]:
    """Generate an Ed25519 keypair.

    Returns:
        (private_key_hex, public_key_hex)
    """
    private_key = Ed25519PrivateKey.generate()
    priv_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv_bytes.hex(), pub_bytes.hex()


def load_or_create_keypair(
    key_dir: str = DEFAULT_KEY_DIR,
    passphrase: Optional[str] = None,
) -> Tuple[str, str]:
    """Load an Ed25519 keypair from *key_dir*, creating one if missing.

    Files stored: ``private.key`` (or ``private.key.enc`` when *passphrase*
    is provided) and ``public.key`` (hex-encoded).

    Args:
        key_dir: Directory for key storage.
        passphrase: If given, the private key is encrypted at rest using
            AES-GCM with a PBKDF2-derived key.  When *None* the legacy
            plaintext format is used for backward compatibility.

    Returns:
        (private_key_hex, public_key_hex)
    """
    key_path = Path(key_dir)
    priv_file = key_path / "private.key"
    priv_enc_file = key_path / "private.key.enc"
    pub_file = key_path / "public.key"

    # --- loading existing keys -------------------------------------------
    if passphrase is not None and priv_enc_file.exists() and pub_file.exists():
        encrypted = priv_enc_file.read_bytes()
        priv_hex = _decrypt_key(encrypted, passphrase)
        pub_hex = pub_file.read_text().strip()
        return priv_hex, pub_hex

    if passphrase is None and priv_file.exists() and pub_file.exists():
        priv_hex = priv_file.read_text().strip()
        pub_hex = pub_file.read_text().strip()
        return priv_hex, pub_hex

    # --- creating new keys -----------------------------------------------
    key_path.mkdir(parents=True, exist_ok=True)
    priv_hex, pub_hex = generate_keypair()

    if passphrase is not None:
        encrypted = _encrypt_key(priv_hex, passphrase)
        priv_enc_file.write_bytes(encrypted)
        os.chmod(priv_enc_file, 0o600)
    else:
        priv_file.write_text(priv_hex)
        os.chmod(priv_file, 0o600)

    pub_file.write_text(pub_hex)
    os.chmod(pub_file, 0o600)
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

"""
Oasyce Wallet Identity Module

Provides a simple Ed25519-based wallet for user identity on the Oasyce network.
The wallet stores a keypair in ~/.oasyce/wallet.json, with the private key
encrypted using AES-GCM (key derived from the system encryption_key).
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from oasyce_plugin.crypto.keys import _encrypt_key, _decrypt_key

WALLET_PATH = Path.home() / ".oasyce" / "wallet.json"
ENCRYPTION_KEY_PATH = Path.home() / ".oasyce" / "encryption_key"


def _load_or_create_encryption_key() -> str:
    """Load the system encryption key from ~/.oasyce/encryption_key,
    or create one if it does not exist."""
    if ENCRYPTION_KEY_PATH.exists():
        return ENCRYPTION_KEY_PATH.read_text().strip()
    # Auto-generate
    passphrase = secrets.token_hex(32)
    ENCRYPTION_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENCRYPTION_KEY_PATH.write_text(passphrase)
    os.chmod(str(ENCRYPTION_KEY_PATH), 0o600)
    return passphrase


class Wallet:
    """Ed25519 wallet for Oasyce identity.

    Wraps a single Ed25519 keypair.  The public key hex serves as
    the user's on-network address.
    """

    def __init__(self, private_key_hex: str, public_key_hex: str):
        self._private_key_hex = private_key_hex
        self._public_key_hex = public_key_hex

    # ── Properties ──────────────────────────────────────────

    @property
    def address(self) -> str:
        """Return the public key hex as the wallet address."""
        return self._public_key_hex

    @property
    def private_key_hex(self) -> str:
        return self._private_key_hex

    @property
    def public_key_hex(self) -> str:
        return self._public_key_hex

    # ── Factory methods ─────────────────────────────────────

    @staticmethod
    def exists(wallet_path: Optional[Path] = None) -> bool:
        """Check whether a wallet file exists on disk."""
        path = wallet_path or WALLET_PATH
        return path.is_file()

    @classmethod
    def create(
        cls,
        wallet_path: Optional[Path] = None,
        passphrase: Optional[str] = None,
    ) -> "Wallet":
        """Generate a new Ed25519 keypair and persist to *wallet_path*.

        The private key is encrypted with AES-GCM using a passphrase
        derived from the system encryption_key (or an explicit *passphrase*).

        Args:
            wallet_path: Where to store the wallet JSON (default ~/.oasyce/wallet.json).
            passphrase: Encryption passphrase.  If ``None``, the system
                encryption_key at ``~/.oasyce/encryption_key`` is used.

        Returns:
            A new :class:`Wallet` instance.
        """
        path = wallet_path or WALLET_PATH
        passphrase = passphrase or _load_or_create_encryption_key()

        # Generate keypair
        private_key = Ed25519PrivateKey.generate()
        priv_bytes = private_key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        pub_bytes = private_key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        priv_hex = priv_bytes.hex()
        pub_hex = pub_bytes.hex()

        # Encrypt and save
        encrypted = _encrypt_key(priv_hex, passphrase)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "public_key": pub_hex,
            "encrypted_private_key": encrypted.hex(),
        }
        path.write_text(json.dumps(payload, indent=2))
        os.chmod(str(path), 0o600)

        return cls(priv_hex, pub_hex)

    @classmethod
    def load(
        cls,
        wallet_path: Optional[Path] = None,
        passphrase: Optional[str] = None,
    ) -> "Wallet":
        """Load an existing wallet from disk.

        Args:
            wallet_path: Path to wallet JSON (default ~/.oasyce/wallet.json).
            passphrase: Decryption passphrase.  If ``None``, uses the
                system encryption_key.

        Returns:
            A :class:`Wallet` instance.

        Raises:
            FileNotFoundError: If the wallet file does not exist.
            ValueError: If decryption fails (wrong passphrase).
        """
        path = wallet_path or WALLET_PATH
        if not path.is_file():
            raise FileNotFoundError(f"Wallet not found at {path}")

        passphrase = passphrase or _load_or_create_encryption_key()
        data = json.loads(path.read_text())
        pub_hex = data["public_key"]
        encrypted = bytes.fromhex(data["encrypted_private_key"])
        priv_hex = _decrypt_key(encrypted, passphrase)

        return cls(priv_hex, pub_hex)

    @staticmethod
    def get_address(wallet_path: Optional[Path] = None) -> Optional[str]:
        """Return the wallet address without decrypting the private key.

        Returns ``None`` if no wallet exists.
        """
        path = wallet_path or WALLET_PATH
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text())
            return data.get("public_key")
        except (json.JSONDecodeError, KeyError):
            return None

    # ── Repr ────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"Wallet(address={self.address[:16]}...)"

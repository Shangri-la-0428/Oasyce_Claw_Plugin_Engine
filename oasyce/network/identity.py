"""Node identity: Ed25519 keypair generation, signing, and verification."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

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


@dataclass
class NodeIdentity:
    """An Oasyce node's cryptographic identity.

    node_id is the hex-encoded public key, used as the unique node address.
    """

    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey
    node_id: str  # hex of raw public key bytes

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def generate(cls) -> NodeIdentity:
        """Generate a brand-new random identity."""
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return cls(
            private_key=private_key,
            public_key=public_key,
            node_id=raw.hex(),
        )

    @classmethod
    def from_private_bytes(cls, data: bytes) -> NodeIdentity:
        """Reconstruct identity from raw 32-byte private key seed."""
        private_key = Ed25519PrivateKey.from_private_bytes(data)
        public_key = private_key.public_key()
        raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return cls(
            private_key=private_key,
            public_key=public_key,
            node_id=raw.hex(),
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, directory: str | Path) -> None:
        """Persist the private key to *directory*/node.key."""
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        key_file = path / "node.key"
        raw_private = self.private_key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        key_file.write_bytes(raw_private)
        os.chmod(key_file, 0o600)

    @classmethod
    def load(cls, directory: str | Path) -> NodeIdentity:
        """Load identity from *directory*/node.key."""
        key_file = Path(directory) / "node.key"
        raw_private = key_file.read_bytes()
        return cls.from_private_bytes(raw_private)

    @classmethod
    def load_or_generate(cls, directory: str | Path) -> NodeIdentity:
        """Load existing identity or generate and save a new one."""
        key_file = Path(directory) / "node.key"
        if key_file.exists():
            return cls.load(directory)
        identity = cls.generate()
        identity.save(directory)
        return identity

    # ------------------------------------------------------------------
    # Signing / verification
    # ------------------------------------------------------------------

    def sign(self, data: bytes) -> str:
        """Sign *data* and return hex-encoded signature."""
        return self.private_key.sign(data).hex()

    @staticmethod
    def verify(public_key_hex: str, data: bytes, signature_hex: str) -> bool:
        """Verify a signature against a public key (all hex-encoded).

        Returns True on valid signature, False otherwise.
        """
        try:
            pub_bytes = bytes.fromhex(public_key_hex)
            sig_bytes = bytes.fromhex(signature_hex)
            pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
            pub_key.verify(sig_bytes, data)
            return True
        except Exception:
            return False

    @staticmethod
    def hash_message(data: bytes) -> str:
        """SHA-256 hex digest used as message / dedup identifier."""
        return hashlib.sha256(data).hexdigest()

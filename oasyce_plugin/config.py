from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

# 自动加载 .env 文件（从项目根目录）
load_dotenv()


# ── Bootstrap nodes ──────────────────────────────────────────────────
BOOTSTRAP_NODES: List[Dict[str, object]] = [
    # 格式：{"host": "x.x.x.x", "port": 9527, "node_id": "..."}
    # 初始：Shangrila 跑的公共 bootstrap 节点
    {"host": "bootstrap.oasyce.com", "port": 9527, "node_id": "bootstrap-0"},
]


# ── Network configuration ───────────────────────────────────────────
@dataclass
class NetworkConfig:
    listen_host: str = "0.0.0.0"
    listen_port: int = 9527
    public_host: Optional[str] = None   # 公网 IP/域名（NAT 后需要）
    public_port: Optional[int] = None
    use_stun: bool = False              # 未来扩展：STUN/TURN


# ── Node identity persistence ───────────────────────────────────────
def load_or_create_node_identity(data_dir: str) -> Tuple[str, str]:
    """Load or create a persistent node identity (Ed25519 keypair).

    Saves to ``<data_dir>/node_id.json``.

    Returns:
        (private_key_hex, public_key_hex)
    """
    from oasyce_plugin.crypto import generate_keypair

    identity_path = Path(data_dir) / "node_id.json"
    if identity_path.exists():
        data = json.loads(identity_path.read_text())
        return data["private_key"], data["node_id"]

    # Generate new identity
    private_hex, public_hex = generate_keypair()
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_path.write_text(json.dumps({
        "node_id": public_hex,
        "private_key": private_hex,
        "created_at": time.time(),
    }, indent=2))
    return private_hex, public_hex


def reset_node_identity(data_dir: str) -> Tuple[str, str]:
    """Force-reset node identity by deleting existing and generating new."""
    identity_path = Path(data_dir) / "node_id.json"
    if identity_path.exists():
        identity_path.unlink()
    return load_or_create_node_identity(data_dir)


def _default_vault_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "genesis_vault")


def _default_data_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".oasyce")


def _parse_tags(raw: Optional[str]) -> List[str]:
    if not raw:
        return ["Core", "Genesis"]
    tags = [t.strip() for t in raw.split(",") if t.strip()]
    return tags or ["Core", "Genesis"]


@dataclass
class Config:
    vault_dir: str = ""
    owner: str = ""
    tags: List[str] = field(default_factory=list)
    signing_key: Optional[str] = None
    public_key: Optional[str] = None
    signing_key_id: str = ""
    data_dir: str = ""
    db_path: str = ""
    node_host: str = "0.0.0.0"
    node_port: int = 9527

    @staticmethod
    def from_env(
        vault_dir: Optional[str] = None,
        owner: Optional[str] = None,
        tags: Optional[str] = None,
        signing_key: Optional[str] = None,
        signing_key_id: Optional[str] = None,
        data_dir: Optional[str] = None,
        public_key: Optional[str] = None,
        db_path: Optional[str] = None,
        node_host: Optional[str] = None,
        node_port: Optional[int] = None,
    ) -> "Config":
        from oasyce_plugin.crypto import load_or_create_keypair

        env_vault = os.getenv("OASYCE_VAULT_DIR")
        env_owner = os.getenv("OASYCE_OWNER")
        env_tags = os.getenv("OASYCE_TAGS")
        env_key = os.getenv("OASYCE_SIGNING_KEY")
        env_key_id = os.getenv("OASYCE_SIGNING_KEY_ID")

        resolved_data_dir = data_dir or os.getenv("OASYCE_DATA_DIR") or _default_data_dir()
        key_dir = os.path.join(resolved_data_dir, "keys")

        # If signing_key provided explicitly, use it as-is (Ed25519 private key hex).
        # Otherwise load/create from key_dir.
        if signing_key:
            resolved_private = signing_key
            resolved_public = public_key or ""
        elif env_key:
            resolved_private = env_key
            resolved_public = public_key or os.getenv("OASYCE_PUBLIC_KEY", "")
        else:
            resolved_private, resolved_public = load_or_create_keypair(key_dir)

        resolved_db = db_path or os.getenv("OASYCE_DB_PATH") or os.path.join(resolved_data_dir, "chain.db")

        resolved_host = node_host or os.getenv("OASYCE_NODE_HOST") or "0.0.0.0"
        resolved_port = node_port or int(os.getenv("OASYCE_NODE_PORT", "0") or "0") or 9527

        return Config(
            vault_dir=vault_dir or env_vault or _default_vault_dir(),
            owner=owner or env_owner or "Shangrila",
            tags=_parse_tags(tags or env_tags),
            signing_key=resolved_private,
            public_key=resolved_public,
            signing_key_id=signing_key_id or env_key_id or "ed25519:default",
            data_dir=resolved_data_dir,
            db_path=resolved_db,
            node_host=resolved_host,
            node_port=resolved_port,
        )

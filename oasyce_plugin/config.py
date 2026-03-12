from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional


def _default_vault_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "genesis_vault")


def _parse_tags(raw: Optional[str]) -> List[str]:
    if not raw:
        return ["Core", "Genesis"]
    tags = [t.strip() for t in raw.split(",") if t.strip()]
    return tags or ["Core", "Genesis"]


@dataclass(frozen=True)
class Config:
    vault_dir: str
    owner: str
    tags: List[str]
    signing_key: Optional[str]
    signing_key_id: str

    @staticmethod
    def from_env(
        vault_dir: Optional[str] = None,
        owner: Optional[str] = None,
        tags: Optional[str] = None,
        signing_key: Optional[str] = None,
        signing_key_id: Optional[str] = None,
    ) -> "Config":
        env_vault = os.getenv("OASYCE_VAULT_DIR")
        env_owner = os.getenv("OASYCE_OWNER")
        env_tags = os.getenv("OASYCE_TAGS")
        env_key = os.getenv("OASYCE_SIGNING_KEY")
        env_key_id = os.getenv("OASYCE_SIGNING_KEY_ID")

        return Config(
            vault_dir=vault_dir or env_vault or _default_vault_dir(),
            owner=owner or env_owner or "Shangrila",
            tags=_parse_tags(tags or env_tags),
            signing_key=signing_key or env_key,
            signing_key_id=signing_key_id or env_key_id or "env:OASYCE_SIGNING_KEY",
        )

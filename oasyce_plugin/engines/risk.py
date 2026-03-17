"""Static risk auto-classification for data assets."""
from __future__ import annotations

import os
from typing import Optional

from .core_engines import PrivacyFilter

# Extension sets for risk classification
_SENSITIVE_EXTENSIONS = {".key", ".pem", ".env", ".p12", ".pfx", ".jks"}
_INTERNAL_EXTENSIONS = {".log", ".bak", ".tmp", ".swp", ".cache"}

# Risk level → maximum access level mapping
RISK_TO_ACCESS = {
    "public": "L3",
    "internal": "L3",
    "sensitive": "L2",
}


def auto_classify_risk(
    file_path: str,
    rights_type: str = "original",
    file_size_bytes: int = 0,
) -> str:
    """Classify a file's risk level based on static heuristics.

    Priority order:
    1. PrivacyFilter detects sensitive → "sensitive"
    2. Sensitive file extensions (.key, .pem, .env) → "sensitive"
    3. rights_type == "collection" → "internal"
    4. Internal extensions (.log, .bak, .tmp) → "internal"
    5. Default → "public"
    """
    # 1. PrivacyFilter check
    if file_path:
        result = PrivacyFilter.is_sensitive_file(file_path)
        if result.ok and result.data and result.data.get("is_sensitive"):
            return "sensitive"

    # 2. Sensitive extensions
    ext = os.path.splitext(file_path)[-1].lower() if file_path else ""
    if ext in _SENSITIVE_EXTENSIONS:
        return "sensitive"

    # 3. Collection rights type
    if rights_type == "collection":
        return "internal"

    # 4. Internal extensions
    if ext in _INTERNAL_EXTENSIONS:
        return "internal"

    # 5. Default
    return "public"

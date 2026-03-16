"""Asset Scanner — discovers registerable assets in user directories.

Scans files, classifies sensitivity, generates descriptions and tags.
Results are pushed to the ConfirmationInbox for user approval.
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

# File extensions considered scannable
_SCANNABLE_EXTENSIONS: Set[str] = {
    ".csv", ".json", ".jsonl", ".xml", ".yaml", ".yml",
    ".txt", ".md", ".rst", ".log",
    ".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".mp3", ".wav", ".flac", ".mp4", ".mov", ".avi",
    ".zip", ".tar", ".gz",
}

# Patterns that suggest sensitive content
_SENSITIVE_PATTERNS = {
    "password", "secret", "token", "private_key", "api_key",
    "credential", "auth", ".env", "id_rsa", "wallet",
}

_INTERNAL_PATTERNS = {
    "draft", "internal", "todo", "wip", "temp", "backup",
    "node_modules", "__pycache__", ".git",
}


@dataclass
class ScanResult:
    """A candidate asset discovered by the scanner."""
    scan_id: str
    file_path: str
    file_type: str
    size_bytes: int
    suggested_name: str
    suggested_tags: List[str]
    suggested_description: str
    sensitivity: str  # 'public' | 'internal' | 'sensitive'
    confidence: float  # 0.0 - 1.0
    scanned_at: int = field(default_factory=lambda: int(time.time()))


class AssetScanner:
    """Scans directories for registerable assets."""

    def __init__(
        self,
        max_file_size: int = 100 * 1024 * 1024,  # 100MB
        skip_hidden: bool = True,
    ) -> None:
        self._max_file_size = max_file_size
        self._skip_hidden = skip_hidden

    def scan_directory(self, path: str, recursive: bool = True) -> List[ScanResult]:
        """Scan a directory and return candidate assets."""
        results: List[ScanResult] = []
        root = Path(path)
        if not root.is_dir():
            return results

        iterator = root.rglob("*") if recursive else root.glob("*")
        for fp in iterator:
            if not fp.is_file():
                continue
            if self._skip_hidden and any(p.startswith(".") for p in fp.parts):
                continue
            if fp.suffix.lower() not in _SCANNABLE_EXTENSIONS:
                continue
            if fp.stat().st_size > self._max_file_size:
                continue

            result = self._analyze_file(fp)
            if result is not None:
                results.append(result)

        return results

    def scan_file(self, path: str) -> Optional[ScanResult]:
        """Scan a single file."""
        fp = Path(path)
        if not fp.is_file():
            return None
        return self._analyze_file(fp)

    def classify_sensitivity(self, file_path: str) -> str:
        """Classify file sensitivity: 'public', 'internal', or 'sensitive'."""
        path_lower = file_path.lower()

        for pattern in _SENSITIVE_PATTERNS:
            if pattern in path_lower:
                return "sensitive"

        for pattern in _INTERNAL_PATTERNS:
            if pattern in path_lower:
                return "internal"

        return "public"

    def generate_description(self, file_path: str) -> Dict[str, object]:
        """Generate suggested name, tags, and description for a file."""
        fp = Path(file_path)
        name = fp.stem.replace("_", " ").replace("-", " ").title()
        ext = fp.suffix.lower().lstrip(".")
        size = fp.stat().st_size if fp.exists() else 0

        # Basic tag generation from path and extension
        tags: List[str] = []
        if ext:
            tags.append(ext)

        # Category tags
        mime = mimetypes.guess_type(file_path)[0] or ""
        if mime.startswith("image"):
            tags.append("image")
        elif mime.startswith("audio"):
            tags.append("audio")
        elif mime.startswith("video"):
            tags.append("video")
        elif ext in ("csv", "json", "jsonl", "xml", "xlsx"):
            tags.append("data")
        elif ext in ("py", "js", "ts", "go", "rs", "java", "c", "cpp"):
            tags.append("code")
        elif ext in ("md", "txt", "rst", "pdf", "doc", "docx"):
            tags.append("document")

        # Parent directory as context
        parent = fp.parent.name
        if parent and parent not in (".", "/"):
            tags.append(parent.lower().replace(" ", "-"))

        description = f"{ext.upper()} file: {fp.name} ({self._human_size(size)})"

        return {
            "name": name,
            "tags": tags,
            "description": description,
        }

    def _analyze_file(self, fp: Path) -> Optional[ScanResult]:
        """Analyze a single file and produce a ScanResult."""
        path_str = str(fp)
        sensitivity = self.classify_sensitivity(path_str)

        # Skip sensitive files entirely
        if sensitivity == "sensitive":
            return None

        desc = self.generate_description(path_str)
        stat = fp.stat()

        # Confidence heuristic
        confidence = 0.7
        if sensitivity == "internal":
            confidence = 0.3
        if stat.st_size < 100:
            confidence *= 0.5  # very small files less likely useful

        scan_id = hashlib.md5(path_str.encode()).hexdigest()[:12]

        return ScanResult(
            scan_id=scan_id,
            file_path=path_str,
            file_type=fp.suffix.lower().lstrip("."),
            size_bytes=stat.st_size,
            suggested_name=desc["name"],
            suggested_tags=desc["tags"],
            suggested_description=desc["description"],
            sensitivity=sensitivity,
            confidence=confidence,
        )

    @staticmethod
    def _human_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.0f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

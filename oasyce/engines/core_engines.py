from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Set

from .result import Result, err, ok
from .schema import validate_metadata

ENGINE_VERSION = "0.3.0"
SCHEMA_VERSION = 1
HASH_ALGO = "sha256"
CHUNK_SIZE = 1024 * 1024


def _canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


class PrivacyFilter:
    """隐私过滤器：扫描后自动识别并过滤敏感文件，防止意外泄露"""

    # 默认敏感文件名模式（正则）
    DEFAULT_SENSITIVE_PATTERNS = [
        r".*身份证.*",
        r".*银行卡.*",
        r".*passport.*",
        r".*credit.?card.*",
        r".*social.?security.*",
        r".*\.key$",
        r".*\.pem$",
        r".*private.*",
        r".*secret.*",
        r".*password.*",
        r".*\.env$",
    ]

    # 默认敏感路径前缀
    DEFAULT_SENSITIVE_PATHS = [
        "/etc/",
        "/private/etc/",
        "/private/var/db/",
        "/private/var/root/",
        "/private/var/keychains/",
        ".ssh/",
        ".gnupg/",
        "keychain/",
        "credentials/",
    ]

    @staticmethod
    def _normalize_path(file_path: str) -> str:
        normalized = os.path.realpath(file_path or "").replace("\\", "/")
        return normalized.rstrip("/") + "/"

    @classmethod
    def is_sensitive_file(
        cls,
        file_path: str,
        custom_patterns: Optional[List[str]] = None,
        custom_paths: Optional[List[str]] = None,
    ) -> Result[Dict[str, Any]]:
        """检查文件是否敏感，返回是否阻止及原因"""
        patterns = custom_patterns or cls.DEFAULT_SENSITIVE_PATTERNS
        paths = custom_paths or cls.DEFAULT_SENSITIVE_PATHS
        normalized_path = cls._normalize_path(file_path)

        # 检查路径前缀
        for prefix in paths:
            normalized_prefix = prefix.replace("\\", "/")
            if normalized_prefix.startswith("/"):
                check_prefix = normalized_prefix.rstrip("/") + "/"
                if normalized_path.startswith(check_prefix):
                    return ok(
                        {
                            "is_sensitive": True,
                            "reason": f"Path matches sensitive prefix: {prefix}",
                            "sensitivity_type": "PATH_PREFIX",
                            "matched_pattern": prefix,
                        }
                    )
            elif f"/{normalized_prefix.strip('/')}/" in normalized_path:
                return ok(
                    {
                        "is_sensitive": True,
                        "reason": f"Path matches sensitive prefix: {prefix}",
                        "sensitivity_type": "PATH_PREFIX",
                        "matched_pattern": prefix,
                    }
                )

        # 检查文件名模式
        filename = os.path.basename(file_path)
        for pattern in patterns:
            if re.match(pattern, filename, re.IGNORECASE):
                return ok(
                    {
                        "is_sensitive": True,
                        "reason": f"Filename matches sensitive pattern: {pattern}",
                        "sensitivity_type": "FILENAME_PATTERN",
                        "matched_pattern": pattern,
                    }
                )

        return ok(
            {
                "is_sensitive": False,
                "reason": "No sensitive patterns matched",
                "sensitivity_type": None,
                "matched_pattern": None,
            }
        )

    @classmethod
    def filter_batch(
        cls,
        file_paths: List[str],
        custom_patterns: Optional[List[str]] = None,
        custom_paths: Optional[List[str]] = None,
    ) -> Result[Dict[str, List[str]]]:
        """批量过滤文件列表，返回允许和阻止的文件列表"""
        allowed: List[str] = []
        blocked: List[str] = []
        blocked_reasons: Dict[str, str] = {}

        for path in file_paths:
            result = cls.is_sensitive_file(path, custom_patterns, custom_paths)
            if not result.ok:
                return err(result.error, code=result.code)

            info = result.data
            if info["is_sensitive"]:
                blocked.append(path)
                blocked_reasons[path] = info["reason"]
            else:
                allowed.append(path)

        return ok(
            {
                "allowed": allowed,
                "blocked": blocked,
                "blocked_reasons": blocked_reasons,
                "total_scanned": len(file_paths),
                "total_allowed": len(allowed),
                "total_blocked": len(blocked),
            }
        )


class DataEngine:
    @staticmethod
    def scan_data(path: str) -> Result[Dict[str, Any]]:
        if not os.path.exists(path):
            return err(f"Path not found: {path}", code="PATH_NOT_FOUND")
        if not os.path.isfile(path):
            return err(f"Not a file: {path}", code="NOT_A_FILE")
        try:
            size = os.path.getsize(path)
            file_hash = _sha256_file(path)
            return ok(
                {
                    "file": os.path.basename(path),
                    "size": size,
                    "file_hash": file_hash,
                    "hash_algo": HASH_ALGO,
                    "path": path,
                }
            )
        except Exception as e:
            return err(str(e), code="SCAN_FAILED")

    @staticmethod
    def classify_data(file_info: Dict[str, Any]) -> Result[Dict[str, Any]]:
        ext = os.path.splitext(file_info.get("file", ""))[-1].lower()
        if ext in [".pdf", ".docx", ".md", ".txt"]:
            category = "DOCUMENT"
            sensitivity = "HIGH"
        elif ext in [".png", ".jpg", ".jpeg", ".mp4", ".mov"]:
            category = "MEDIA"
            sensitivity = "MEDIUM"
        else:
            category = "BINARY/OTHER"
            sensitivity = "UNKNOWN"

        return ok(
            {
                "category": category,
                "sensitivity": sensitivity,
                "ai_training_value": "HIGH" if sensitivity == "HIGH" else "NORMAL",
            }
        )

    @staticmethod
    def scan_data_with_privacy_check(
        path: str, privacy_filter: Optional[PrivacyFilter] = None
    ) -> Result[Dict[str, Any]]:
        """扫描文件并自动进行隐私检查，如果文件敏感则阻止"""
        # 先进行隐私检查
        privacy_result = PrivacyFilter.is_sensitive_file(path)
        if not privacy_result.ok:
            return err(privacy_result.error, code=privacy_result.code)

        if privacy_result.data["is_sensitive"]:
            privacy_info = privacy_result.data
            return err(
                f"File blocked by privacy filter: {privacy_info['reason']}", code="PRIVACY_BLOCKED"
            )

        # 隐私检查通过，继续扫描
        return DataEngine.scan_data(path)


class MetadataEngine:
    @staticmethod
    def generate_metadata(
        file_info: Dict[str, Any],
        tags: List[str],
        owner: str,
        classification: Optional[Dict[str, Any]] = None,
        rights_type: str = "original",
        co_creators: Optional[List[Dict[str, Any]]] = None,
    ) -> Result[Dict[str, Any]]:
        from oasyce.models import VALID_RIGHTS_TYPES

        if not file_info.get("file_hash"):
            return err("Missing file hash in file_info", code="MISSING_FILE_HASH")

        if rights_type not in VALID_RIGHTS_TYPES:
            return err(
                f"Invalid rights_type '{rights_type}'. Must be one of: {', '.join(sorted(VALID_RIGHTS_TYPES))}",
                code="INVALID_RIGHTS_TYPE",
            )

        if rights_type == "co_creation":
            if not co_creators or len(co_creators) < 2:
                return err(
                    "co_creation requires at least 2 co-creators",
                    code="INVALID_CO_CREATORS",
                )
            total_share = sum(c.get("share", 0) for c in co_creators)
            if abs(total_share - 100) > 0.01:
                return err(
                    f"Co-creator shares must sum to 100%, got {total_share}%",
                    code="INVALID_SHARES",
                )

        asset_id = f"OAS_{file_info.get('file_hash', 'UNKNOWN')[:8].upper()}"
        metadata: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "asset_id": asset_id,
            "filename": file_info.get("file"),
            "owner": owner,
            "tags": tags,
            "timestamp": int(time.time()),
            "file_size_bytes": file_info.get("size"),
            "file_hash": file_info.get("file_hash"),
            "hash_algo": file_info.get("hash_algo"),
            "rights_type": rights_type,
        }

        if co_creators:
            metadata["co_creators"] = co_creators

        metadata["disputed"] = False

        if classification:
            metadata["classification"] = classification

        # Auto-classify risk level
        from oasyce.engines.risk import auto_classify_risk, RISK_TO_ACCESS

        metadata["risk_level"] = auto_classify_risk(
            file_path=file_info.get("path", ""),
            rights_type=rights_type,
            file_size_bytes=file_info.get("size", 0),
        )
        metadata["max_access_level"] = RISK_TO_ACCESS[metadata["risk_level"]]

        return ok(metadata)


class CertificateEngine:
    @staticmethod
    def create_popc_certificate(
        metadata: Dict[str, Any],
        signing_key: Optional[str],
        key_id: str,
    ) -> Result[Dict[str, Any]]:
        if not signing_key:
            return err("Missing signing key", code="MISSING_SIGNING_KEY")

        validation = validate_metadata(metadata, require_signature=False)
        if not validation.ok:
            return err(validation.error or "Invalid metadata", code=validation.code)

        try:
            from oasyce.crypto import sign as ed25519_sign

            payload = dict(metadata)
            payload.pop("popc_signature", None)
            payload.pop("certificate_issuer", None)
            payload.pop("certificate_type", None)
            payload.pop("signature_alg", None)
            payload.pop("signature_key_id", None)

            canonical = _canonical_json(payload)
            signature = ed25519_sign(canonical.encode("utf-8"), signing_key)

            metadata = dict(metadata)
            metadata["popc_signature"] = signature
            metadata["signature_alg"] = "Ed25519"
            metadata["signature_key_id"] = key_id
            metadata["certificate_issuer"] = f"oasyce_node_{key_id[:8]}"
            metadata["certificate_type"] = "digital_signature"
            return ok(metadata)
        except Exception as e:
            return err(str(e), code="CERTIFICATE_FAILED")

    @staticmethod
    def verify_popc_certificate(
        metadata: Dict[str, Any], signing_key: Optional[str]
    ) -> Result[bool]:
        if not signing_key:
            return err("Missing signing key", code="MISSING_SIGNING_KEY")

        validation = validate_metadata(metadata, require_signature=True)
        if not validation.ok:
            return err(validation.error or "Invalid metadata", code=validation.code)

        try:
            from oasyce.crypto import verify as ed25519_verify

            signature = metadata.get("popc_signature")
            if not signature:
                return err("Missing signature", code="MISSING_SIGNATURE")

            payload = dict(metadata)
            payload.pop("popc_signature", None)
            payload.pop("certificate_issuer", None)
            payload.pop("certificate_type", None)
            payload.pop("signature_alg", None)
            payload.pop("signature_key_id", None)

            canonical = _canonical_json(payload)
            valid = ed25519_verify(canonical.encode("utf-8"), signature, signing_key)
            return ok(valid)
        except Exception as e:
            return err(str(e), code="VERIFY_FAILED")


class UploadEngine:
    @staticmethod
    def register_asset(
        metadata: Dict[str, Any], vault_path: str, ledger: Any = None
    ) -> Result[Dict[str, Any]]:
        asset_id = metadata.get("asset_id")
        if not asset_id:
            return err("Missing asset_id", code="MISSING_ASSET_ID")

        try:
            # Persist to SQLite ledger when available
            if ledger is not None:
                ledger.register_asset(
                    asset_id=asset_id,
                    owner=metadata.get("owner", ""),
                    file_hash=metadata.get("file_hash", ""),
                    metadata=metadata,
                    popc_signature=metadata.get("popc_signature", ""),
                )
                ledger.record_tx(
                    tx_type="register",
                    asset_id=asset_id,
                    from_addr=metadata.get("owner"),
                    metadata=metadata,
                    signature=metadata.get("popc_signature"),
                )

            # Always write JSON file for backward compatibility
            os.makedirs(vault_path, exist_ok=True)
            dest = os.path.join(vault_path, f"{asset_id}.json")
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)
            return ok({"status": "success", "vault_path": dest, "asset_id": asset_id})
        except Exception as e:
            return err(f"Failed to register asset: {str(e)}", code="REGISTER_FAILED")

    @staticmethod
    def register_asset_with_storage(
        metadata: Dict[str, Any],
        vault_path: str,
        file_path: Optional[str] = None,
        storage_backend: Optional[str] = None,
        storage_dir: Optional[str] = None,
        ledger: Any = None,
    ) -> Result[Dict[str, Any]]:
        """
        注册资产并存储到可插拔后端

        Args:
            metadata: 资产元数据
            vault_path: 账本目录
            file_path: 原文件路径（如果需要上传到存储后端）
            storage_backend: 存储后端类型 ("local" | "ipfs")
            storage_dir: 存储目录（storage_backend="local" 时使用）
            ledger: Optional Ledger instance for SQLite persistence

        Returns:
            注册结果，包含 CID 和存储后端信息
        """
        from oasyce.storage.ipfs_client import IPFSClient

        asset_id = metadata.get("asset_id")
        if not asset_id:
            return err("Missing asset_id", code="MISSING_ASSET_ID")

        try:
            # 初始化存储客户端
            if storage_backend is None:
                storage_backend = "local"

            client = IPFSClient(storage_type=storage_backend, storage_dir=storage_dir)

            # 如果有文件路径，上传文件
            cid = None
            if file_path and os.path.exists(file_path):
                upload_result = client.upload(file_path, metadata)
                if upload_result.get("success"):
                    cid = upload_result["cid"]
                    metadata["storage_cid"] = cid
                    metadata["storage_backend"] = storage_backend

            # Persist to SQLite ledger when available
            if ledger is not None:
                ledger.register_asset(
                    asset_id=asset_id,
                    owner=metadata.get("owner", ""),
                    file_hash=metadata.get("file_hash", ""),
                    metadata=metadata,
                    popc_signature=metadata.get("popc_signature", ""),
                )
                ledger.record_tx(
                    tx_type="register",
                    asset_id=asset_id,
                    from_addr=metadata.get("owner"),
                    metadata=metadata,
                    signature=metadata.get("popc_signature"),
                )

            # 保存到 vault (backward compatibility)
            os.makedirs(vault_path, exist_ok=True)
            dest = os.path.join(vault_path, f"{asset_id}.json")
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)

            return ok(
                {
                    "status": "success",
                    "vault_path": dest,
                    "asset_id": asset_id,
                    "storage_cid": cid,
                    "storage_backend": storage_backend,
                }
            )
        except Exception as e:
            return err(f"Failed to register asset with storage: {str(e)}", code="REGISTER_FAILED")


class SearchEngine:
    @staticmethod
    def search_assets(
        vault_path: str, query_tag: str, ledger: Any = None
    ) -> Result[List[Dict[str, Any]]]:
        # Prefer SQLite ledger when available
        if ledger is not None:
            return ok(ledger.search_assets(query_tag))

        # Fallback: scan JSON files in vault directory
        results: List[Dict[str, Any]] = []
        if not os.path.exists(vault_path):
            return ok(results)

        for filename in os.listdir(vault_path):
            if filename.endswith(".json"):
                filepath = os.path.join(vault_path, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if query_tag in data.get("tags", []):
                            results.append(data)
                except Exception:
                    continue
        return ok(results)


class TradeEngine:
    @staticmethod
    def quote_price(asset_id: str) -> Result[Dict[str, Any]]:
        return ok(
            {
                "asset_id": asset_id,
                "current_price_oas": 15.5,
                "liquidity_depth": "10000 OAS",
                "status": "Tradable",
            }
        )

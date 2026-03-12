from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, List, Optional

from .result import Result, err, ok
from .schema import validate_metadata

ENGINE_VERSION = "0.2.0"
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


class MetadataEngine:
    @staticmethod
    def generate_metadata(
        file_info: Dict[str, Any],
        tags: List[str],
        owner: str,
        classification: Optional[Dict[str, Any]] = None,
    ) -> Result[Dict[str, Any]]:
        if not file_info.get("file_hash"):
            return err("Missing file hash in file_info", code="MISSING_FILE_HASH")

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
        }

        if classification:
            metadata["classification"] = classification

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
            payload = dict(metadata)
            payload.pop("popc_signature", None)
            payload.pop("certificate_issuer", None)
            payload.pop("signature_alg", None)
            payload.pop("signature_key_id", None)

            canonical = _canonical_json(payload)
            signature = hmac.new(signing_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()

            metadata = dict(metadata)
            metadata["popc_signature"] = signature
            metadata["signature_alg"] = "HMAC-SHA256"
            metadata["signature_key_id"] = key_id
            metadata["certificate_issuer"] = "Oasyce_Hardware_Node_001"
            return ok(metadata)
        except Exception as e:
            return err(str(e), code="CERTIFICATE_FAILED")

    @staticmethod
    def verify_popc_certificate(metadata: Dict[str, Any], signing_key: Optional[str]) -> Result[bool]:
        if not signing_key:
            return err("Missing signing key", code="MISSING_SIGNING_KEY")

        validation = validate_metadata(metadata, require_signature=True)
        if not validation.ok:
            return err(validation.error or "Invalid metadata", code=validation.code)

        try:
            signature = metadata.get("popc_signature")
            if not signature:
                return err("Missing signature", code="MISSING_SIGNATURE")

            payload = dict(metadata)
            payload.pop("popc_signature", None)
            payload.pop("certificate_issuer", None)
            payload.pop("signature_alg", None)
            payload.pop("signature_key_id", None)

            canonical = _canonical_json(payload)
            expected = hmac.new(signing_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
            return ok(hmac.compare_digest(signature, expected))
        except Exception as e:
            return err(str(e), code="VERIFY_FAILED")


class UploadEngine:
    @staticmethod
    def register_asset(metadata: Dict[str, Any], vault_path: str) -> Result[Dict[str, Any]]:
        asset_id = metadata.get("asset_id")
        if not asset_id:
            return err("Missing asset_id", code="MISSING_ASSET_ID")

        try:
            os.makedirs(vault_path, exist_ok=True)
            dest = os.path.join(vault_path, f"{asset_id}.json")
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)
            return ok({"status": "success", "vault_path": dest, "asset_id": asset_id})
        except Exception as e:
            return err(f"Failed to register asset: {str(e)}", code="REGISTER_FAILED")


class SearchEngine:
    @staticmethod
    def search_assets(vault_path: str, query_tag: str) -> Result[List[Dict[str, Any]]]:
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

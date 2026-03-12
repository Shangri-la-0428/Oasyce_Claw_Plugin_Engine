import os
from typing import Dict, Any, List
from oasyce_plugin.engines.core_engines import (
    DataEngine, MetadataEngine, CertificateEngine, 
    UploadEngine, SearchEngine, TradeEngine
)
from oasyce_plugin.engines.result import Result
from oasyce_plugin.models import AssetMetadata
from oasyce_plugin.config import Config

class OasyceSkills:
    """Agent 可以调用的上层 API 能力集"""
    def __init__(self, config: Config):
        self.config = config
        self.vault_path = config.vault_dir
        if not os.path.exists(self.vault_path):
            try:
                os.makedirs(self.vault_path)
            except Exception as e:
                print(f"[错误] 无法创建账本目录：{e}")

    def _unwrap(self, result: Result) -> Any:
        if not result.ok:
            raise RuntimeError(result.error)
        return result.data

    def scan_data_skill(self, file_path: str) -> Dict[str, Any]:
        return self._unwrap(DataEngine.scan_data(file_path))

    def classify_data_skill(self, file_info: Dict[str, Any]) -> Dict[str, Any]:
        return self._unwrap(DataEngine.classify_data(file_info))

    def generate_metadata_skill(self, file_info: Dict[str, Any], tags: List[str], owner: str = None, classification: Dict[str, Any] = None) -> Dict[str, Any]:
        return self._unwrap(MetadataEngine.generate_metadata(file_info, tags, owner or self.config.owner, classification))

    def create_certificate_skill(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        return self._unwrap(CertificateEngine.create_popc_certificate(metadata, self.config.signing_key, self.config.signing_key_id))

    def register_data_asset_skill(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        return self._unwrap(UploadEngine.register_asset(metadata, self.vault_path))

    def search_data_skill(self, query_tag: str) -> List[Dict[str, Any]]:
        return self._unwrap(SearchEngine.search_assets(self.vault_path, query_tag))

    def trade_data_skill(self, asset_id: str) -> Dict[str, Any]:
        return self._unwrap(TradeEngine.quote_price(asset_id))

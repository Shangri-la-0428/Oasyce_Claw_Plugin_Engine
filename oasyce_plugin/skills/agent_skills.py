import os
from typing import Dict, Any, List, Optional
from oasyce_plugin.engines.core_engines import (
    DataEngine, MetadataEngine, CertificateEngine, 
    UploadEngine, SearchEngine, TradeEngine, PrivacyFilter
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
        
        # 隐私过滤器配置
        self.privacy_filter = PrivacyFilter()
        self.enable_privacy_check = True  # 默认启用隐私检查

    def _unwrap(self, result: Result) -> Any:
        if not result.ok:
            raise RuntimeError(result.error)
        return result.data

    def scan_data_skill(self, file_path: str, skip_privacy_check: bool = False) -> Dict[str, Any]:
        """
        扫描文件
        
        Args:
            file_path: 文件路径
            skip_privacy_check: 是否跳过隐私检查（默认 False）
        """
        if self.enable_privacy_check and not skip_privacy_check:
            return self._unwrap(DataEngine.scan_data_with_privacy_check(file_path, self.privacy_filter))
        return self._unwrap(DataEngine.scan_data(file_path))

    def classify_data_skill(self, file_info: Dict[str, Any]) -> Dict[str, Any]:
        """AI 分类数据"""
        return self._unwrap(DataEngine.classify_data(file_info))

    def generate_metadata_skill(
        self,
        file_info: Dict[str, Any],
        tags: List[str],
        owner: str = None,
        classification: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """生成数据元信息"""
        return self._unwrap(MetadataEngine.generate_metadata(
            file_info, tags, owner or self.config.owner, classification
        ))

    def create_certificate_skill(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """生成数据凭证（Data Certificate）"""
        return self._unwrap(CertificateEngine.create_popc_certificate(
            metadata, self.config.signing_key, self.config.signing_key_id
        ))

    def register_data_asset_skill(
        self,
        metadata: Dict[str, Any],
        file_path: Optional[str] = None,
        storage_backend: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        注册数据资产
        
        Args:
            metadata: 元数据
            file_path: 原文件路径（可选，如果提供则上传到存储后端）
            storage_backend: 存储后端 ("local" | "ipfs")，默认 "local"
        """
        storage_dir = getattr(self.config, 'storage_dir', None)
        return self._unwrap(UploadEngine.register_asset_with_storage(
            metadata, self.vault_path, file_path, storage_backend, storage_dir
        ))

    def search_data_skill(self, query_tag: str) -> List[Dict[str, Any]]:
        """搜索数据资产"""
        return self._unwrap(SearchEngine.search_assets(self.vault_path, query_tag))

    def trade_data_skill(self, asset_id: str) -> Dict[str, Any]:
        """查询资产价格（Agent 购买数据）"""
        return self._unwrap(TradeEngine.quote_price(asset_id))

    def check_privacy_skill(self, file_path: str) -> Dict[str, Any]:
        """检查文件是否敏感（不扫描，只检查隐私）"""
        return self._unwrap(PrivacyFilter.is_sensitive_file(file_path))

    def filter_batch_skill(self, file_paths: List[str]) -> Dict[str, Any]:
        """批量过滤文件列表"""
        return self._unwrap(PrivacyFilter.filter_batch(file_paths))

    def enable_privacy_filter(self, enable: bool = True):
        """启用/禁用隐私过滤器"""
        self.enable_privacy_check = enable

import os
import time
from typing import Dict, Any, List, Optional
from oasyce_plugin.engines.core_engines import (
    DataEngine, MetadataEngine, CertificateEngine,
    UploadEngine, SearchEngine, TradeEngine, PrivacyFilter
)
from oasyce_plugin.engines.result import Result
from oasyce_plugin.models import AssetMetadata
from oasyce_plugin.config import Config
from oasyce_plugin.fingerprint import FingerprintEngine, FingerprintRegistry


class OasyceSkills:
    """Agent 可以调用的上层 API 能力集"""

    def __init__(self, config: Config, ledger: "Any" = None):
        self.config = config
        self.vault_path = config.vault_dir
        if not os.path.exists(self.vault_path):
            try:
                os.makedirs(self.vault_path)
            except Exception as e:
                print(f"[错误] 无法创建账本目录：{e}")

        # SQLite ledger (None = legacy JSON-only mode)
        if ledger is not None:
            self.ledger = ledger
        elif config.db_path:
            from oasyce_plugin.storage.ledger import Ledger
            self.ledger = Ledger(config.db_path)
        else:
            self.ledger = None

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
            metadata, self.vault_path, file_path, storage_backend, storage_dir,
            ledger=self.ledger,
        ))

    def search_data_skill(self, query_tag: str) -> List[Dict[str, Any]]:
        """搜索数据资产"""
        return self._unwrap(SearchEngine.search_assets(self.vault_path, query_tag, ledger=self.ledger))

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

    def buy_shares_skill(self, asset_id: str, buyer: str, amount: float = 10.0) -> Dict[str, Any]:
        """购买资产份额（通过 L2 Bonding Curve 交易）

        Args:
            asset_id: 资产 ID
            buyer: 买方地址
            amount: 购买金额（默认 10.0 OAS）
        """
        from oasyce_plugin.bridge.core_bridge import bridge_buy
        return bridge_buy(asset_id, buyer, amount, ledger=self.ledger)

    def stake_skill(self, validator_id: str, amount: float) -> Dict[str, Any]:
        """质押到验证节点

        Args:
            validator_id: 验证者节点 ID
            amount: 质押金额（OAS）
        """
        from oasyce_plugin.bridge.core_bridge import bridge_stake
        return bridge_stake(validator_id, amount, ledger=self.ledger)

    def mine_block_skill(self) -> Dict[str, Any]:
        """将未打包的交易打包成一个新区块

        Returns:
            区块信息字典，如果没有待打包交易则返回 {"status": "no_pending_tx"}
        """
        if self.ledger is None:
            raise RuntimeError("Ledger not initialized")
        block = self.ledger.create_block()
        if block is None:
            return {"status": "no_pending_tx"}
        return block

    def get_shares_skill(self, owner: str) -> Any:
        """查询持仓份额

        Args:
            owner: 资产拥有者地址
        """
        from oasyce_plugin.bridge.core_bridge import bridge_get_shares
        return bridge_get_shares(owner)

    # ── Network / P2P Skills ────────────────────────────────────────

    def start_node_skill(self) -> Dict[str, Any]:
        """启动 P2P 节点（返回节点信息，不阻塞）

        Returns:
            节点信息字典: node_id, host, port, height, peers, running
        """
        import asyncio
        from oasyce_plugin.network.node import OasyceNode

        node_id = (self.config.public_key or "unknown")[:16]
        node = OasyceNode(
            host=self.config.node_host,
            port=self.config.node_port,
            node_id=node_id,
            ledger=self.ledger,
        )
        asyncio.run(node.start())
        self._node = node
        return node.info()

    def node_info_skill(self) -> Dict[str, Any]:
        """返回当前节点信息

        Returns:
            节点信息字典: node_id, host, port, chain_height
        """
        node_id = (self.config.public_key or "unknown")[:16]
        height = self.ledger.get_chain_height() if self.ledger else 0
        return {
            "node_id": node_id,
            "host": self.config.node_host,
            "port": self.config.node_port,
            "chain_height": height,
        }

    # ── Fingerprint Skills ──────────────────────────────────────────

    def fingerprint_embed_skill(
        self,
        asset_id: str,
        caller_id: str,
        content_or_path: Any,
        binary: bool = False,
    ) -> Dict[str, Any]:
        """Generate a fingerprint, embed it into content, and record in registry.

        Args:
            asset_id: The asset being distributed.
            caller_id: Identity of the caller receiving the content.
            content_or_path: Text string (or bytes if binary=True).
            binary: If True, treat content_or_path as bytes.

        Returns:
            dict with fingerprint, watermarked_content_or_path, record_id.
        """
        engine = FingerprintEngine(self.config.signing_key)
        ts = int(time.time())
        fingerprint = engine.generate_fingerprint(asset_id, caller_id, ts)

        if binary:
            watermarked = engine.embed_binary(content_or_path, fingerprint)
        else:
            watermarked = engine.embed_text(content_or_path, fingerprint)

        record_id = None
        if self.ledger is not None:
            registry = FingerprintRegistry(self.ledger)
            record_id = registry.record_distribution(asset_id, caller_id, fingerprint, ts)

        return {
            "fingerprint": fingerprint,
            "watermarked_content_or_path": watermarked,
            "record_id": record_id,
        }

    def fingerprint_extract_skill(
        self, content_or_path: Any, binary: bool = False
    ) -> Optional[str]:
        """Extract a fingerprint from watermarked content.

        Args:
            content_or_path: Watermarked text string (or bytes if binary=True).
            binary: If True, treat content_or_path as bytes.

        Returns:
            The extracted fingerprint hex string, or None.
        """
        if binary:
            return FingerprintEngine.extract_binary(content_or_path)
        return FingerprintEngine.extract_text(content_or_path)

    def fingerprint_trace_skill(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        """Trace a fingerprint to the caller who received it.

        Args:
            fingerprint: The fingerprint hex string to look up.

        Returns:
            Distribution record dict, or None if not found.
        """
        if self.ledger is None:
            return None
        registry = FingerprintRegistry(self.ledger)
        return registry.trace_fingerprint(fingerprint)

    def fingerprint_list_skill(self, asset_id: str) -> List[Dict[str, Any]]:
        """List all fingerprint distributions for an asset.

        Args:
            asset_id: The asset ID to query.

        Returns:
            List of distribution record dicts.
        """
        if self.ledger is None:
            return []
        registry = FingerprintRegistry(self.ledger)
        return registry.get_distributions(asset_id)

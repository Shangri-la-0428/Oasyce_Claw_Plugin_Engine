import logging
import os
import time
from typing import Dict, Any, List, Optional
from oasyce.engines.core_engines import (
    DataEngine,
    MetadataEngine,
    CertificateEngine,
    UploadEngine,
    SearchEngine,
    TradeEngine,
    PrivacyFilter,
)
from oasyce.engines.result import Result
from oasyce.models import AssetMetadata
from oasyce.config import Config
from oasyce.fingerprint import FingerprintEngine, FingerprintRegistry
from oasyce.services.access.provider import DataAccessProvider
from oasyce.services.reputation import ReputationEngine

logger = logging.getLogger(__name__)


class OasyceSkills:
    """Agent 可以调用的上层 API 能力集"""

    def __init__(self, config: Config, ledger: "Any" = None):
        self.config = config
        self.vault_path = config.vault_dir
        if not os.path.exists(self.vault_path):
            try:
                os.makedirs(self.vault_path)
            except Exception as e:
                logger.error("无法创建账本目录：%s", e)

        # SQLite ledger (None = legacy JSON-only mode)
        if ledger is not None:
            self.ledger = ledger
        elif config.db_path:
            from oasyce.storage.ledger import Ledger

            self.ledger = Ledger(config.db_path)
        else:
            self.ledger = None

        # 隐私过滤器配置
        self.privacy_filter = PrivacyFilter()
        self.enable_privacy_check = True  # 默认启用隐私检查

        # 访问控制
        self.access_provider = DataAccessProvider()

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
            return self._unwrap(
                DataEngine.scan_data_with_privacy_check(file_path, self.privacy_filter)
            )
        return self._unwrap(DataEngine.scan_data(file_path))

    def classify_data_skill(self, file_info: Dict[str, Any]) -> Dict[str, Any]:
        """AI 分类数据"""
        return self._unwrap(DataEngine.classify_data(file_info))

    def generate_metadata_skill(
        self,
        file_info: Dict[str, Any],
        tags: List[str],
        owner: str = None,
        classification: Dict[str, Any] = None,
        rights_type: str = "original",
        co_creators: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """生成数据元信息"""
        return self._unwrap(
            MetadataEngine.generate_metadata(
                file_info,
                tags,
                owner or self.config.owner,
                classification,
                rights_type=rights_type,
                co_creators=co_creators,
            )
        )

    def create_certificate_skill(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """生成数据凭证（Data Certificate）"""
        return self._unwrap(
            CertificateEngine.create_popc_certificate(
                metadata, self.config.signing_key, self.config.signing_key_id
            )
        )

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
        storage_dir = getattr(self.config, "storage_dir", None)
        result = self._unwrap(
            UploadEngine.register_asset_with_storage(
                metadata,
                self.vault_path,
                file_path,
                storage_backend,
                storage_dir,
                ledger=self.ledger,
            )
        )

        # Registration-time fragmentation detection
        frag_result = self._check_registration_fragmentation(metadata)
        if frag_result and frag_result.get("is_fragment"):
            result["fragment_warning"] = frag_result["warning"]
            result["fragment_matches"] = frag_result["matches"]

        return result

    def _check_registration_fragmentation(self, metadata: Dict[str, Any]) -> Optional[Dict]:
        """Check if a newly registered asset is a fragment of existing assets."""
        from oasyce.services.exposure.registry import ExposureRegistry

        new_vector = metadata.get("semantic_vector")
        new_size = metadata.get("file_size_bytes", 0)
        if not new_vector or not new_size:
            return None

        # Gather existing assets from ledger or vault
        existing = self._get_existing_asset_vectors()
        if not existing:
            return None

        registry = ExposureRegistry()
        return registry.check_registration_fragmentation(
            new_vector,
            new_size,
            existing,
        )

    def _get_existing_asset_vectors(self) -> List[Dict[str, Any]]:
        """Collect asset_id, semantic_vector, file_size_bytes from registered assets."""
        import json as _json

        assets: List[Dict[str, Any]] = []

        # Try ledger first
        if self.ledger is not None:
            try:
                for a in self.ledger.search_assets(""):
                    vec = a.get("semantic_vector")
                    size = a.get("file_size_bytes", 0)
                    if vec and size:
                        assets.append(
                            {
                                "asset_id": a.get("asset_id", ""),
                                "semantic_vector": vec,
                                "file_size_bytes": size,
                            }
                        )
            except Exception:
                pass

        # Fallback: scan vault JSON files
        if not assets and os.path.isdir(self.vault_path):
            for fname in os.listdir(self.vault_path):
                if fname.endswith(".json"):
                    fpath = os.path.join(self.vault_path, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = _json.load(f)
                        vec = data.get("semantic_vector")
                        size = data.get("file_size_bytes", 0)
                        if vec and size:
                            assets.append(
                                {
                                    "asset_id": data.get("asset_id", ""),
                                    "semantic_vector": vec,
                                    "file_size_bytes": size,
                                }
                            )
                    except Exception:
                        continue

        return assets

    def search_data_skill(self, query_tag: str) -> List[Dict[str, Any]]:
        """搜索数据资产"""
        return self._unwrap(
            SearchEngine.search_assets(self.vault_path, query_tag, ledger=self.ledger)
        )

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
        from oasyce.bridge.core_bridge import bridge_buy

        return bridge_buy(asset_id, buyer, amount, ledger=self.ledger)

    def discover_and_buy_skill(
        self,
        query: str,
        buyer: str,
        max_price: float = 100.0,
        amount: float = 10.0,
        with_watermark: bool = True,
    ) -> Dict[str, Any]:
        """One-shot: search → evaluate → quote → buy → watermark → return data.

        This is the primary skill for AI agents to autonomously acquire data.
        The agent describes what it needs, and gets back the data (watermarked).

        Args:
            query: What data the agent needs (matched against tags/metadata).
            buyer: Agent identity (used for watermark and purchase record).
            max_price: Maximum OAS willing to spend per token. Aborts if too expensive.
            amount: OAS to spend on purchase (default 10.0).
            with_watermark: If True, return a watermarked copy of the data.

        Returns:
            dict with: asset_id, tokens_received, price_paid, watermarked_content (if text),
                       fingerprint, receipt. Or {error} if nothing found / too expensive.
        """
        from oasyce.services.settlement.engine import SettlementEngine

        # 1. Search
        results = self._unwrap(
            SearchEngine.search_assets(self.vault_path, query, ledger=self.ledger)
        )
        if not results:
            return {"error": f"No data found matching '{query}'"}

        # 2. Pick best match (first result — search already ranks by relevance)
        asset = results[0]
        asset_id = asset.get("asset_id", "")

        # 3. Quote via settlement engine
        se = SettlementEngine()
        if asset_id not in se.pools:
            se.register_asset(asset_id, asset.get("owner", "unknown"))
        quote = se.quote(asset_id, amount)

        # 4. Price check — effective price per token
        effective_price = amount / quote.equity_minted if quote.equity_minted > 0 else float("inf")
        if effective_price > max_price:
            return {
                "error": f"Too expensive: {effective_price:.4f} OAS/token exceeds max {max_price}",
                "asset_id": asset_id,
                "price": effective_price,
                "max_price": max_price,
            }

        # 5. Execute purchase
        receipt = se.execute(asset_id, buyer, amount)
        if receipt.status.value != "SETTLED":
            return {"error": receipt.error or "Purchase failed", "asset_id": asset_id}

        result = {
            "asset_id": asset_id,
            "asset_info": asset,
            "tokens_received": round(receipt.quote.equity_minted, 4),
            "price_paid": amount,
            "effective_price": round(effective_price, 6),
            "price_after": round(receipt.quote.spot_price_after, 6),
            "receipt_id": receipt.receipt_id,
            "equity_balance": round(receipt.equity_balance, 4),
            "fee_burned": round(receipt.quote.burn_amount, 4),
        }

        # 6. Watermark (if text asset and content available)
        if with_watermark:
            try:
                # Try to read the asset content from vault
                import os

                asset_path = asset.get("path") or asset.get("file_path", "")
                if asset_path and os.path.isfile(asset_path):
                    with open(asset_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    embed_result = self.fingerprint_embed_skill(asset_id, buyer, content)
                    result["watermarked_content"] = embed_result["watermarked_content_or_path"]
                    result["fingerprint"] = embed_result["fingerprint"]
                else:
                    result["watermark_note"] = (
                        "Asset file not accessible locally; watermark skipped"
                    )
            except Exception:
                result["watermark_note"] = "Could not watermark (binary or inaccessible file)"

        # 7. Record transaction in ledger
        if self.ledger is not None:
            self.ledger.record_tx(
                tx_type="buy",
                asset_id=asset_id,
                from_addr=buyer,
                amount=amount,
                metadata=result,
            )

        return result

    def stake_skill(self, validator_id: str, amount: float) -> Dict[str, Any]:
        """质押到验证节点

        Args:
            validator_id: 验证者节点 ID
            amount: 质押金额（OAS）
        """
        from oasyce.bridge.core_bridge import bridge_stake

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
        from oasyce.bridge.core_bridge import bridge_get_shares

        return bridge_get_shares(owner)

    # ── Network / P2P Skills ────────────────────────────────────────

    def start_node_skill(self) -> Dict[str, Any]:
        """启动 P2P 节点（返回节点信息，不阻塞）

        Returns:
            节点信息字典: node_id, host, port, height, peers, running
        """
        import asyncio
        from oasyce.network.node import OasyceNode

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

    # ── Access Control Skills ─────────────────────────────────────

    def query_data_skill(self, agent_id: str, asset_id: str, query_string: str) -> Dict[str, Any]:
        """L0 查询 — 仅返回聚合统计，数据不离开飞地。

        Args:
            agent_id: 请求方 Agent ID
            asset_id: 资产 ID
            query_string: 查询语句
        """
        result = self.access_provider.query(agent_id, asset_id, query_string)
        return {
            "success": result.success,
            "access_level": result.access_level,
            "bond_required": result.bond_required,
            "data": result.data,
            "error": result.error,
        }

    def sample_data_skill(
        self, agent_id: str, asset_id: str, sample_size: int = 10
    ) -> Dict[str, Any]:
        """L1 采样 — 返回脱敏+水印片段。

        Args:
            agent_id: 请求方 Agent ID
            asset_id: 资产 ID
            sample_size: 采样数量
        """
        result = self.access_provider.sample(agent_id, asset_id, sample_size)
        return {
            "success": result.success,
            "access_level": result.access_level,
            "bond_required": result.bond_required,
            "data": result.data,
            "error": result.error,
        }

    def compute_data_skill(
        self, agent_id: str, asset_id: str, code: str, params: dict = None
    ) -> Dict[str, Any]:
        """L2 计算 — 在 TEE 内执行代码，只有输出离开。

        Args:
            agent_id: 请求方 Agent ID
            asset_id: 资产 ID
            code: 要执行的代码
            params: 可选参数字典
        """
        result = self.access_provider.compute(agent_id, asset_id, code, params)
        return {
            "success": result.success,
            "access_level": result.access_level,
            "bond_required": result.bond_required,
            "data": result.data,
            "error": result.error,
        }

    def deliver_data_skill(self, agent_id: str, asset_id: str) -> Dict[str, Any]:
        """L3 交付 — 完整数据交付，需要最高保证金。

        Args:
            agent_id: 请求方 Agent ID
            asset_id: 资产 ID
        """
        result = self.access_provider.deliver(agent_id, asset_id)
        return {
            "success": result.success,
            "access_level": result.access_level,
            "bond_required": result.bond_required,
            "data": result.data,
            "error": result.error,
        }

    def check_reputation_skill(self, agent_id: str) -> Dict[str, Any]:
        """查询 Agent 信誉分与保证金折扣。

        Args:
            agent_id: Agent ID
        """
        rep = self.access_provider.reputation
        score = rep.get_reputation(agent_id)
        discount = rep.get_bond_discount(agent_id)
        return {
            "agent_id": agent_id,
            "reputation": score,
            "bond_discount": discount,
        }

    def _find_asset_metadata(self, asset_id: str) -> Dict[str, Any]:
        """Look up asset metadata by ID from ledger or vault JSON files."""
        import json as _json

        # Try ledger first
        if self.ledger is not None:
            try:
                assets = self.ledger.search_assets("")
                for a in assets:
                    if a.get("asset_id") == asset_id:
                        return a
            except Exception:
                pass

        # Fallback: scan vault JSON files
        if os.path.isdir(self.vault_path):
            for fname in os.listdir(self.vault_path):
                if fname.endswith(".json"):
                    fpath = os.path.join(self.vault_path, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = _json.load(f)
                        if data.get("asset_id") == asset_id:
                            return data
                    except Exception:
                        continue

        raise RuntimeError(f"Asset not found: {asset_id}")

    def get_asset_standard_skill(self, asset_id: str) -> Dict[str, Any]:
        """Return OAS-DAS 5-layer representation of an asset.

        Args:
            asset_id: Asset ID to look up.

        Returns:
            OAS-DAS dict with identity/metadata/access_policy/compute_interface/provenance.
        """
        from oasyce.standards.oas_das import OasDasAsset

        meta_dict = self._find_asset_metadata(asset_id)
        meta = AssetMetadata(
            asset_id=meta_dict.get("asset_id", ""),
            filename=meta_dict.get("filename", ""),
            owner=meta_dict.get("owner", ""),
            tags=meta_dict.get("tags", []),
            timestamp=meta_dict.get("timestamp", 0),
            file_size_bytes=meta_dict.get("file_size_bytes", 0),
            classification=meta_dict.get("classification"),
            popc_signature=meta_dict.get("popc_signature"),
            certificate_issuer=meta_dict.get("certificate_issuer"),
            schema_version=meta_dict.get("schema_version", "1.0"),
            risk_level=meta_dict.get("risk_level", "public"),
            max_access_level=meta_dict.get("max_access_level", "L3"),
            compute_interface=meta_dict.get("compute_interface"),
            semantic_vector=meta_dict.get("semantic_vector"),
        )
        das = OasDasAsset.from_asset_metadata(meta)
        return das.to_dict()

    def validate_asset_standard_skill(self, asset_id: str) -> Dict[str, Any]:
        """Validate an asset against the OAS-DAS standard.

        Args:
            asset_id: Asset ID to validate.

        Returns:
            dict with 'valid' (bool) and 'errors' (list of error strings).
        """
        from oasyce.standards.oas_das import OasDasAsset

        meta_dict = self._find_asset_metadata(asset_id)
        meta = AssetMetadata(
            asset_id=meta_dict.get("asset_id", ""),
            filename=meta_dict.get("filename", ""),
            owner=meta_dict.get("owner", ""),
            tags=meta_dict.get("tags", []),
            timestamp=meta_dict.get("timestamp", 0),
            file_size_bytes=meta_dict.get("file_size_bytes", 0),
            classification=meta_dict.get("classification"),
            popc_signature=meta_dict.get("popc_signature"),
            certificate_issuer=meta_dict.get("certificate_issuer"),
            schema_version=meta_dict.get("schema_version", "1.0"),
            risk_level=meta_dict.get("risk_level", "public"),
            max_access_level=meta_dict.get("max_access_level", "L3"),
            compute_interface=meta_dict.get("compute_interface"),
            semantic_vector=meta_dict.get("semantic_vector"),
        )
        das = OasDasAsset.from_asset_metadata(meta)
        errors = das.validate()
        return {"valid": len(errors) == 0, "errors": errors, "asset_id": asset_id}

    # ── Contribution Proof Skills ────────────────────────────────

    def generate_contribution_proof_skill(
        self,
        file_path: str,
        creator_key: str,
        source_type: str = "manual",
    ) -> Dict[str, Any]:
        """Generate a contribution proof for a data file.

        Args:
            file_path: Path to the data file.
            creator_key: Creator's public key.
            source_type: Source type (tee_capture/api_log/sensor_sig/git_commit/manual).

        Returns:
            Contribution certificate as dict.
        """
        from oasyce.services.contribution import ContributionEngine

        engine = ContributionEngine()
        cert = engine.generate_proof(file_path, creator_key, source_type=source_type)
        return cert.to_dict()

    def verify_contribution_proof_skill(
        self,
        certificate_dict: Dict[str, Any],
        file_path: str,
    ) -> Dict[str, Any]:
        """Verify a contribution proof against a file.

        Args:
            certificate_dict: Certificate as dict (from generate_contribution_proof_skill).
            file_path: Path to the original data file.

        Returns:
            {"valid": bool, "checks": {...}}
        """
        from oasyce.services.contribution import (
            ContributionEngine,
            ContributionCertificate,
        )

        engine = ContributionEngine()
        cert = ContributionCertificate.from_dict(certificate_dict)
        return engine.verify_proof(cert, file_path)

    # ── Leakage Budget Skills ─────────────────────────────────

    def check_leakage_budget_skill(self, agent_id: str, asset_id: str) -> Dict[str, Any]:
        """Check leakage budget remaining for an (agent, asset) pair.

        Args:
            agent_id: Agent ID.
            asset_id: Asset ID.

        Returns:
            Budget status dict.
        """
        return self.access_provider.leakage.get_remaining(agent_id, asset_id)

    def calculate_bond_skill(
        self, agent_id: str, asset_id: str, access_level: str
    ) -> Dict[str, Any]:
        """计算指定访问级别所需的保证金。

        Args:
            agent_id: Agent ID
            asset_id: 资产 ID
            access_level: 访问级别 (L0/L1/L2/L3)
        """
        from oasyce.services.access import AccessLevel, parse_max_access_level

        level = parse_max_access_level(access_level)
        bond = self.access_provider._calculate_bond(agent_id, asset_id, level)
        return {
            "agent_id": agent_id,
            "asset_id": asset_id,
            "access_level": access_level,
            "bond_required": bond,
        }

    def calculate_price_skill(
        self,
        asset_id: str,
        base_price: float = 1.0,
        query_count: int = 0,
        similar_count: int = 0,
        contribution_score: float = 1.0,
        days_since_creation: float = 0,
    ) -> Dict[str, Any]:
        """计算数据资产价格（综合需求、稀缺性、贡献评分和新鲜度）。

        Args:
            asset_id: 资产 ID
            base_price: 基础价格（OAS）
            query_count: 累计查询次数
            similar_count: 相似资产数量
            contribution_score: 贡献评分 (0~1)
            days_since_creation: 创建后天数
        """
        from oasyce.services.pricing import DatasetPricingCurve

        curve = DatasetPricingCurve()
        return curve.calculate_price(
            asset_id=asset_id,
            base_price=base_price,
            query_count=query_count,
            similar_count=similar_count,
            contribution_score=contribution_score,
            days_since_creation=days_since_creation,
        )

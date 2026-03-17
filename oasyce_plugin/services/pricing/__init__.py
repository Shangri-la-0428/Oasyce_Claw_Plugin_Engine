"""
Dataset Pricing Curve — Demand, Scarcity & Contribution-Aware Pricing

Extends the base Bancor bonding curve with market-driven factors:
  demand_factor   = 1 + α × log(1 + query_count)        — grows with usage
  scarcity_factor = 1 / (1 + similar_count)              — rare data is worth more
  quality_factor  = 1 + weight × contribution_score      — better data earns premium
  freshness_factor = 0.5^(days / halflife) + 0.5         — decays toward 0.5 over time

Final price = max(base_price × Π(factors), min_price)
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List


# ─── Configuration ────────────────────────────────────────

@dataclass(frozen=True)
class PricingConfig:
    """定价曲线参数"""
    demand_alpha: float = 0.1              # 需求增长系数
    scarcity_base: float = 1.0             # 稀缺性基础值
    freshness_halflife_days: int = 180     # 新鲜度半衰期（天）
    min_price: float = 0.001               # 最低价格（OAS）
    contribution_score_weight: float = 0.5  # 贡献评分对价格的影响权重


# ─── Pricing Curve ────────────────────────────────────────

class DatasetPricingCurve:
    """数据资产自动定价 — 综合需求、稀缺性和贡献评分"""

    def __init__(self, config: PricingConfig | None = None):
        self.config = config or PricingConfig()
        self._query_counts: Dict[str, int] = {}    # asset_id → 累计查询次数
        self._similar_counts: Dict[str, int] = {}  # asset_id → 相似资产数量
        self._price_history: Dict[str, List[dict]] = {}  # asset_id → [{timestamp, price, factors}]

    # ─── Factor calculations ──────────────────────────────

    def _demand_factor(self, query_count: int) -> float:
        """demand_factor = 1 + α × log(1 + query_count)"""
        return 1.0 + self.config.demand_alpha * math.log(1 + query_count)

    def _scarcity_factor(self, similar_count: int) -> float:
        """scarcity_factor = 1 / (1 + similar_count), range (0, 1]"""
        return self.config.scarcity_base / (1 + similar_count)

    def _quality_factor(self, contribution_score: float) -> float:
        """quality_factor = 1 + weight × contribution_score, range [1, 1.5]"""
        raw = 1.0 + self.config.contribution_score_weight * contribution_score
        return min(raw, 1.5)

    def _freshness_factor(self, days_since_creation: float) -> float:
        """freshness_factor = 0.5^(days / halflife) + 0.5, range (0.5, 1.5]"""
        halflife = self.config.freshness_halflife_days
        if halflife <= 0:
            return 1.0
        return math.pow(0.5, days_since_creation / halflife) + 0.5

    @staticmethod
    def _rights_type_factor(rights_type: str) -> float:
        """Look up the pricing multiplier for a given rights type."""
        from oasyce_plugin.models import RIGHTS_TYPE_MULTIPLIER
        return RIGHTS_TYPE_MULTIPLIER.get(rights_type, 1.0)

    # ─── Core pricing ────────────────────────────────────

    def calculate_price(
        self,
        asset_id: str,
        base_price: float,
        query_count: int = 0,
        similar_count: int = 0,
        contribution_score: float = 1.0,
        days_since_creation: float = 0,
        rights_type: str = "original",
    ) -> dict:
        """
        计算最终价格。

        price = base_price × demand_factor × scarcity_factor
                            × quality_factor × freshness_factor
                            × rights_type_factor

        Returns:
            dict with final_price, base_price, and each factor value + breakdown.
        """
        demand = self._demand_factor(query_count)
        scarcity = self._scarcity_factor(similar_count)
        quality = self._quality_factor(contribution_score)
        freshness = self._freshness_factor(days_since_creation)
        rights = self._rights_type_factor(rights_type)

        raw_price = base_price * demand * scarcity * quality * freshness * rights
        final_price = max(raw_price, self.config.min_price)

        result = {
            "final_price": round(final_price, 6),
            "base_price": round(base_price, 6),
            "demand_factor": round(demand, 6),
            "scarcity_factor": round(scarcity, 6),
            "quality_factor": round(quality, 6),
            "freshness_factor": round(freshness, 6),
            "rights_type_factor": round(rights, 6),
            "breakdown": {
                "query_count": query_count,
                "similar_count": similar_count,
                "contribution_score": round(contribution_score, 6),
                "days_since_creation": round(days_since_creation, 2),
                "rights_type": rights_type,
            },
        }

        # Record history
        if asset_id not in self._price_history:
            self._price_history[asset_id] = []
        self._price_history[asset_id].append({
            "timestamp": int(time.time()),
            "final_price": result["final_price"],
            "demand_factor": result["demand_factor"],
            "scarcity_factor": result["scarcity_factor"],
            "quality_factor": result["quality_factor"],
            "freshness_factor": result["freshness_factor"],
            "rights_type_factor": result["rights_type_factor"],
        })

        return result

    # ─── State tracking ──────────────────────────────────

    def record_query(self, asset_id: str) -> int:
        """记录一次查询，更新需求计数。返回新的累计查询次数。"""
        self._query_counts[asset_id] = self._query_counts.get(asset_id, 0) + 1
        return self._query_counts[asset_id]

    def get_query_count(self, asset_id: str) -> int:
        """获取资产的累计查询次数。"""
        return self._query_counts.get(asset_id, 0)

    def update_similar_count(self, asset_id: str, count: int) -> None:
        """更新相似资产数量。"""
        self._similar_counts[asset_id] = count

    def get_similar_count(self, asset_id: str) -> int:
        """获取资产的相似资产数量。"""
        return self._similar_counts.get(asset_id, 0)

    def get_price_history(self, asset_id: str) -> List[dict]:
        """获取价格变化历史。"""
        return list(self._price_history.get(asset_id, []))

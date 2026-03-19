"""Project-wide information hub — single source of truth for all audiences.

Consumed by: GUI about panel, CLI `oasyce info`, API `/api/info`.
"""

from __future__ import annotations

from typing import Any, Dict, List

from oasyce import __version__

# ── Version & identity ────────────────────────────────────────────
PROJECT_NAME = "Oasyce"
VERSION = __version__
TAGLINE_EN = "Data-rights clearing network for the machine economy"
TAGLINE_ZH = "面向机器经济的数据权利清算网络"
LICENSE = "MIT"

# ── Links ─────────────────────────────────────────────────────────
LINKS = {
    "homepage": "https://oasyce.com",
    "github_project": "https://github.com/Shangri-la-0428/Oasyce_Project",
    "github_engine": "https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine",
    "whitepaper": "https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/WHITEPAPER.md",
    "protocol_overview": "https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/PROTOCOL_OVERVIEW.md",
    "discord": "https://discord.gg/oasyce",
    "email": "wutc@oasyce.com",
}

# ── Audience-targeted sections ────────────────────────────────────

QUICK_START: Dict[str, str] = {
    "en": (
        "1. pip install oasyce\n"
        "2. oasyce doctor          # verify setup\n"
        "3. oasyce start           # launch node + dashboard\n"
        "4. Open http://localhost:8420 in your browser"
    ),
    "zh": (
        "1. pip install oasyce\n"
        "2. oasyce doctor          # 验证安装\n"
        "3. oasyce start           # 启动节点 + 仪表盘\n"
        "4. 浏览器打开 http://localhost:8420"
    ),
}

HOW_IT_WORKS: Dict[str, str] = {
    "en": (
        "Oasyce is a decentralized protocol where AI agents autonomously "
        "register, discover, license, and settle data rights. "
        "Data owners register files and receive a cryptographic proof-of-provenance certificate (PoPc). "
        "AI agents discover data via a Recall-Rank pipeline, negotiate prices through bonding curves, "
        "and settle transactions with escrow-protected OAS tokens. "
        "All interactions are recorded on a peer-to-peer ledger with Ed25519 signatures."
    ),
    "zh": (
        "Oasyce 是一个去中心化协议，AI 代理在其中自主注册、发现、许可和结算数据权利。"
        "数据所有者注册文件并获得加密来源证明证书 (PoPc)。"
        "AI 代理通过 Recall-Rank 管道发现数据，通过联合曲线协商价格，"
        "并使用托管保护的 OAS 代币进行结算。"
        "所有交互都记录在使用 Ed25519 签名的点对点账本上。"
    ),
}

ARCHITECTURE: Dict[str, str] = {
    "en": (
        "Core Layers:\n"
        "  - Schema Registry: Unified validation for data/capability/oracle/identity assets\n"
        "  - Engine Pipeline: Scan -> Classify -> Metadata -> PoPc Certificate -> Register\n"
        "  - Discovery: Recall (broad retrieval) -> Rank (trust + economics) with feedback loop\n"
        "  - Settlement: Bonding curve pricing, escrow, share distribution\n"
        "  - Access Control: L0 (metadata) / L1 (sample) / L2 (compute) / L3 (full)\n"
        "  - P2P Network: Ed25519 identity, gossip sync, PoS consensus\n"
        "  - Risk Engine: Auto-classification (public/internal/sensitive)"
    ),
    "zh": (
        "核心层级:\n"
        "  - Schema Registry: 统一验证 data/capability/oracle/identity 四种资产类型\n"
        "  - 引擎管道: 扫描 -> 分类 -> 元数据 -> PoPc 证书 -> 注册\n"
        "  - 发现引擎: Recall (广召回) -> Rank (信任 + 经济) + 反馈循环\n"
        "  - 结算引擎: 联合曲线定价、托管、份额分配\n"
        "  - 访问控制: L0 (元数据) / L1 (采样) / L2 (计算) / L3 (完整)\n"
        "  - P2P 网络: Ed25519 身份、gossip 同步、PoS 共识\n"
        "  - 风险引擎: 自动分级 (public/internal/sensitive)"
    ),
}

ECONOMICS: Dict[str, str] = {
    "en": (
        "Token: OAS\n"
        "Pricing: Bonding curve (reserve ratio 0.35) — more buyers = higher price, no order book\n"
        "Shares: Early buyers earn more (diminishing: 100% -> 80% -> 60% -> 40%)\n"
        "Rights multiplier: original 1.0x / co_creation 0.9x / licensed 0.7x / collection 0.3x\n"
        "Staking: Validators stake OAS to produce blocks and earn rewards\n"
        "Block reward: 4.0 OAS (mainnet), halving every ~1M blocks\n"
        "Escrow: Funds locked before execution, released after quality verification\n"
        "Reputation: Long-term score — bad behavior follows you"
    ),
    "zh": (
        "代币: OAS\n"
        "定价: 联合曲线 (储备率 0.35) — 买家越多价格越高，无订单簿\n"
        "份额: 早期买家获利更多 (递减: 100% -> 80% -> 60% -> 40%)\n"
        "权利系数: 原创 1.0x / 共创 0.9x / 授权 0.7x / 收藏 0.3x\n"
        "质押: 验证者质押 OAS 出块并获得奖励\n"
        "区块奖励: 4.0 OAS (主网)，每约 100 万块减半\n"
        "托管: 执行前锁定资金，质量验证后释放\n"
        "声誉: 长期评分 — 不良行为如影随形"
    ),
}

UPDATE_GUIDE: Dict[str, str] = {
    "en": (
        "Update:\n"
        "  pip install --upgrade oasyce\n"
        "\n"
        "Build from source:\n"
        "  git clone https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine\n"
        "  cd Oasyce_Claw_Plugin_Engine\n"
        "  pip install -e .\n"
        "\n"
        "Run tests:\n"
        "  python -m pytest tests/ -v\n"
        "\n"
        "Contribute:\n"
        "  Fork -> Branch -> PR. See CONTRIBUTING.md for details."
    ),
    "zh": (
        "更新:\n"
        "  pip install --upgrade oasyce\n"
        "\n"
        "从源码构建:\n"
        "  git clone https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine\n"
        "  cd Oasyce_Claw_Plugin_Engine\n"
        "  pip install -e .\n"
        "\n"
        "运行测试:\n"
        "  python -m pytest tests/ -v\n"
        "\n"
        "贡献:\n"
        "  Fork -> Branch -> PR。详见 CONTRIBUTING.md。"
    ),
}


def get_info(lang: str = "en") -> Dict[str, Any]:
    """Return full project info dict, suitable for JSON serialization."""
    l = lang if lang in ("en", "zh") else "en"
    return {
        "project": PROJECT_NAME,
        "version": VERSION,
        "tagline": TAGLINE_EN if l == "en" else TAGLINE_ZH,
        "license": LICENSE,
        "links": LINKS,
        "asset_types": ["data", "capability", "oracle", "identity"],
        "schema_version": 1,
        "quick_start": QUICK_START[l],
        "how_it_works": HOW_IT_WORKS[l],
        "architecture": ARCHITECTURE[l],
        "economics": ECONOMICS[l],
        "update_guide": UPDATE_GUIDE[l],
    }

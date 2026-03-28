from __future__ import annotations

from oasyce.doc_contract import (
    render_ai_integration_onboarding_block,
    render_beta_onboarding,
    render_public_beta_readme_block,
)
from oasyce.info import get_info


def test_public_beta_readme_block_mentions_single_guide():
    block = render_public_beta_readme_block("en")
    assert "single product-facing public beta guide" in block
    assert "oas doctor --public-beta --json" in block
    assert "oas --json sandbox status" in block
    assert "compatibility alias" not in block


def test_public_beta_readme_block_zh_mentions_sandbox_boundary():
    block = render_public_beta_readme_block("zh")
    assert "唯一产品入口文档" in block
    assert "`oas sandbox *`" in block
    assert "公测发布 gate" in block


def test_beta_onboarding_comes_from_contract():
    onboarding = render_beta_onboarding("en")
    assert onboarding.startswith("Beta Onboarding:")
    assert "Idempotency-Key" in onboarding
    assert "oas smoke public-beta --json" in onboarding


def test_ai_integration_onboarding_block_comes_from_contract():
    block = render_ai_integration_onboarding_block("en")
    assert "Keep onboarding truth narrow:" in block
    assert "oas doctor --public-beta --json" in block
    assert "oas --json sandbox status" in block


def test_info_beta_onboarding_uses_contract_text():
    payload = get_info("zh")
    assert payload["beta_onboarding"].startswith("公测引导:")
    assert "Idempotency-Key" in payload["beta_onboarding"]

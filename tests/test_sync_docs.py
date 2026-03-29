from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "sync_docs.py"
SPEC = importlib.util.spec_from_file_location("sync_docs_module", SCRIPT_PATH)
assert SPEC and SPEC.loader
sync_docs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_docs)


def test_replace_generated_block_replaces_only_target_block():
    original = (
        "before\n"
        "<!-- BEGIN GENERATED:PUBLIC_BETA -->\n"
        "old\n"
        "<!-- END GENERATED:PUBLIC_BETA -->\n"
        "after\n"
    )

    updated = sync_docs.replace_generated_block(original, "PUBLIC_BETA", "new")

    assert "old" not in updated
    assert "new" in updated
    assert updated.startswith("before\n")
    assert updated.endswith("after\n")


def test_render_public_beta_readme_block_contains_release_gate():
    block = sync_docs.render_public_beta_readme_block("en")
    assert "single product-facing public beta guide" in block
    assert "oas doctor --public-beta --json" in block
    assert "oas device export --output oasyce-device.json" in block
    assert "compatibility alias" not in block


def test_render_ai_onboarding_block_contains_smoke_and_sandbox():
    block = sync_docs.render_ai_onboarding_block("en")
    assert "Keep onboarding truth narrow, with owner account + trusted device:" in block
    assert "oas smoke public-beta --json" in block
    assert "oas --json sandbox onboard" in block

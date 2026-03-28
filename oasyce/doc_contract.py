from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Dict


@lru_cache(maxsize=1)
def get_doc_contract() -> Dict[str, Any]:
    payload = files("oasyce").joinpath("doc_contract.json").read_text(encoding="utf-8")
    return json.loads(payload)


def render_public_beta_readme_block(lang: str) -> str:
    contract = get_doc_contract()["public_beta"]
    locale = "zh" if lang == "zh" else "en"
    commands = "\n".join(contract["readme_commands"][locale])
    return (
        f'{contract["readme_title"][locale]}\n\n'
        f'{contract["readme_intro"][locale]}\n\n'
        "```bash\n"
        f"{commands}\n"
        "```"
    )


def render_ai_integration_onboarding_block(lang: str) -> str:
    contract = get_doc_contract()["public_beta"]
    locale = "zh" if lang == "zh" else "en"
    sources = "\n".join(contract["ai_onboarding_sources"][locale])
    gate_commands = "\n".join(contract["ai_onboarding_gate_commands"][locale])
    sandbox_commands = "\n".join(contract["ai_onboarding_sandbox_commands"][locale])
    return (
        f'{contract["ai_onboarding_intro"][locale]}\n\n'
        f"{sources}\n\n"
        f'{contract["ai_onboarding_gate_title"][locale]}\n\n'
        "```bash\n"
        f"{gate_commands}\n"
        "```\n\n"
        f'{contract["ai_onboarding_sandbox_title"][locale]}\n\n'
        "```bash\n"
        f"{sandbox_commands}\n"
        "```"
    )


def render_beta_onboarding(lang: str) -> str:
    contract = get_doc_contract()["public_beta"]
    locale = "zh" if lang == "zh" else "en"
    return "\n".join(
        [contract["beta_onboarding_title"][locale], *contract["beta_onboarding_lines"][locale]]
    )

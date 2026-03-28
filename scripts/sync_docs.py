#!/usr/bin/env python3
"""
Sync documentation across the Oasyce ecosystem.

Single source of truth:
  - Version: pyproject.toml
  - Content: AGENTS.md

Generated outputs:
  - SKILL.md (ClawHub skill = frontmatter + AGENTS.md body)

Usage:
  python scripts/sync_docs.py              # check mode (CI)
  python scripts/sync_docs.py --write      # write mode (update files)
  python scripts/sync_docs.py --write --skill-path /path/to/SKILL.md
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
AGENTS_MD = ROOT / "AGENTS.md"
DEFAULT_SKILL_PATH = ROOT / "SKILL.md"
CLAWHUB_SKILL_PATH = ROOT.parent / "OpenClaw" / "workspace" / "skills" / "oasyce" / "SKILL.md"
DOC_CONTRACT_PATH = ROOT / "oasyce" / "doc_contract.json"
README_PATHS = {"zh": ROOT / "README.md", "en": ROOT / "README_EN.md"}

SKILL_FRONTMATTER = """---
name: oasyce
version: {version}
description: >
  Oasyce Protocol — decentralized AI data marketplace. Register data assets,
  list AI capabilities, submit compute tasks (Proof of Useful Work), trade shares
  on bonding curves, and operate your node. One install: pip install oasyce.
  Use when user mentions Oasyce, data rights, data registration, bonding curve,
  AI capabilities, compute tasks, PoUW, capability marketplace, OAS tokens, staking,
  data scanning, or wants to monetize/protect their data.
read_when:
  - User mentions Oasyce, OAS, data rights, or data registration
  - User wants to register, protect, price, or monetize data
  - User asks about bonding curves, shares, manual pricing, or staking
  - User wants to invoke, list, or register AI capabilities/services
  - User asks about agent scheduler, autonomous trading, or periodic tasks
  - User asks about compute tasks, proof of useful work, PoUW, or AI execution
  - User asks about oracle feeds, real-time data, or price feeds
  - User asks about agent identity, trust tiers, or reputation
  - User mentions "确权", "上链", "数据资产", "能力市场", or agent services
  - User wants to run a protocol demo or start a node
  - User wants to scan, inventory, or classify local data assets
metadata: {{"emoji":"⚡","requires":{{"bins":["python3","oasyce"]}}}}
---
"""


def read_version() -> str:
    """Read version from pyproject.toml."""
    text = PYPROJECT.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        print("ERROR: Cannot find version in pyproject.toml", file=sys.stderr)
        sys.exit(1)
    return match.group(1)


def extract_agents_body(text: str) -> str:
    """Strip the AGENTS title/intro and return the reusable body."""
    # Remove the first line (# title) and the blockquote about AI tools
    lines = text.split("\n")
    body_lines = []
    skip_header = True
    for line in lines:
        if skip_header:
            # Skip until we hit the first ## or --- separator after the intro
            if line.startswith("## ") or (line.strip() == "---" and body_lines):
                skip_header = False
                body_lines.append(line)
        else:
            body_lines.append(line)
    body = "\n".join(body_lines)
    return re.sub(r"<!-- (BEGIN|END) GENERATED:[A-Z_]+ -->\n?", "", body)


def read_doc_contract() -> dict:
    return json.loads(DOC_CONTRACT_PATH.read_text())


def render_public_beta_readme_block(lang: str) -> str:
    contract = read_doc_contract()["public_beta"]
    commands = "\n".join(contract["readme_commands"][lang])
    return (
        f'{contract["readme_title"][lang]}\n\n'
        f'{contract["readme_intro"][lang]}\n\n'
        "```bash\n"
        f"{commands}\n"
        "```"
    )


def render_ai_onboarding_block(lang: str) -> str:
    contract = read_doc_contract()["public_beta"]
    intro = contract["ai_onboarding_intro"][lang]
    sources = "\n".join(contract["ai_onboarding_sources"][lang])
    gate_title = contract["ai_onboarding_gate_title"][lang]
    gate_commands = "\n".join(contract["ai_onboarding_gate_commands"][lang])
    sandbox_title = contract["ai_onboarding_sandbox_title"][lang]
    sandbox_commands = "\n".join(contract["ai_onboarding_sandbox_commands"][lang])
    return (
        f"{intro}\n\n"
        f"{sources}\n\n"
        f"{gate_title}\n\n"
        "```bash\n"
        f"{gate_commands}\n"
        "```\n\n"
        f"{sandbox_title}\n\n"
        "```bash\n"
        f"{sandbox_commands}\n"
        "```"
    )


def replace_generated_block(text: str, block_name: str, content: str) -> str:
    begin = f"<!-- BEGIN GENERATED:{block_name} -->"
    end = f"<!-- END GENERATED:{block_name} -->"
    pattern = re.compile(rf"{re.escape(begin)}.*?{re.escape(end)}", re.DOTALL)
    replacement = f"{begin}\n{content}\n{end}"
    if not pattern.search(text):
        print(f"ERROR: Cannot find generated block {block_name}", file=sys.stderr)
        sys.exit(1)
    return pattern.sub(replacement, text, count=1)


def generate_skill(version: str, agents_text: str) -> str:
    """Generate SKILL.md content from AGENTS.md + frontmatter."""
    frontmatter = SKILL_FRONTMATTER.format(version=version)
    body = extract_agents_body(agents_text)

    # Add title after frontmatter
    content = frontmatter + "\n# Oasyce Protocol Skill\n\n"
    content += "Decentralized AI data marketplace — data rights + AI capabilities "
    content += "+ compute tasks + autonomous agent + P2P node.\n\n"
    content += "## Prerequisites\n\n"
    content += "```bash\n"
    content += "pip install oasyce              # everything included (DataVault bundled)\n"
    content += "oas bootstrap                   # self-update + wallet + DataVault readiness\n"
    content += "oas doctor                      # optional diagnostics\n"
    content += "```\n\n"
    content += "---\n\n"
    content += body.lstrip("\n")

    # Add footer
    if "When to Use" not in content:
        content += "\n---\n\n## When to Use\n\n"
        content += "- Data registration with pricing control (auto/fixed/floor)\n"
        content += "- AI capability listing, discovery, invocation, settlement\n"
        content += "- Compute task submission and executor registration (PoUW)\n"
        content += "- Local data scanning, classification, PII detection\n"
        content += "- Autonomous agent operation (scheduled scan/register/trade)\n"
        content += "- Consensus participation, staking, governance voting\n"
        content += "- Fingerprint watermarking and provenance verification\n"
        content += "- Testnet onboarding and demos\n"

    if "When NOT to Use" not in content:
        content += "\n## When NOT to Use\n\n"
        content += "- General file management (mv/cp/rm — use standard tools)\n"
        content += "- General crypto questions unrelated to data rights\n"
        content += "- Browser-based web3 wallet interactions\n"

    return content


def check_symlinks() -> list[str]:
    """Verify CLAUDE.md and other tool files are symlinks to AGENTS.md."""
    errors = []
    for name in [
        "CLAUDE.md",
        "CODEX.md",
        ".cursorrules",
        ".windsurfrules",
        ".clinerules",
        ".github/copilot-instructions.md",
    ]:
        path = ROOT / name
        if not path.exists():
            errors.append(f"MISSING: {name} does not exist")
        elif not path.is_symlink():
            errors.append(f"NOT SYMLINK: {name} should be a symlink to AGENTS.md")
        elif path.resolve() != AGENTS_MD.resolve():
            errors.append(f"WRONG TARGET: {name} -> {path.resolve()} (expected AGENTS.md)")
    return errors


def check_version_consistency() -> list[str]:
    """Check version is consistent across files."""
    errors = []
    version = read_version()

    # Check AGENTS.md doesn't have a stale version (if it mentions one)
    agents_text = AGENTS_MD.read_text()
    version_refs = re.findall(r"v(\d+\.\d+\.\d+)", agents_text)
    for ref in version_refs:
        if ref != version and ref not in ("0.50.10", "8.8.0", "0.2.0"):  # skip SDK/IBC/odv versions
            errors.append(
                f"VERSION MISMATCH: AGENTS.md references v{ref}, pyproject.toml is v{version}"
            )

    return errors


def main():
    parser = argparse.ArgumentParser(description="Sync Oasyce documentation")
    parser.add_argument(
        "--write", action="store_true", help="Write generated files (default: check only)"
    )
    parser.add_argument(
        "--skill-path", type=Path, default=DEFAULT_SKILL_PATH, help="Path to SKILL.md output"
    )
    args = parser.parse_args()

    version = read_version()
    errors = []

    # 1. Check symlinks
    symlink_errors = check_symlinks()
    errors.extend(symlink_errors)

    # 2. Check version consistency
    version_errors = check_version_consistency()
    errors.extend(version_errors)

    # 3. Generate and compare/write AGENTS.md generated blocks
    current_agents = AGENTS_MD.read_text()
    generated_agents = replace_generated_block(
        current_agents,
        "AI_ONBOARDING",
        render_ai_onboarding_block("en"),
    )
    if current_agents != generated_agents:
        if args.write:
            AGENTS_MD.write_text(generated_agents)
            print(f"UPDATED: {AGENTS_MD}")
        else:
            errors.append(
                f"STALE: {AGENTS_MD} AI onboarding block differs from generated content. Run with --write to update."
            )

    # 4. Generate and compare/write SKILL.md to all targets
    generated_skill = generate_skill(version, generated_agents)
    skill_targets = [args.skill_path]
    if CLAWHUB_SKILL_PATH.parent.exists():
        skill_targets.append(CLAWHUB_SKILL_PATH)

    for target in skill_targets:
        if target.exists():
            current_skill = target.read_text()
            if current_skill != generated_skill:
                if args.write:
                    target.write_text(generated_skill)
                    print(f"UPDATED: {target}")
                else:
                    errors.append(
                        f"STALE: {target} differs from generated content. Run with --write to update."
                    )
        else:
            if args.write:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(generated_skill)
                print(f"CREATED: {target}")
            else:
                errors.append(f"MISSING: {target} does not exist. Run with --write to create.")

    # 5. Generate and compare/write README public beta blocks
    for lang, path in README_PATHS.items():
        generated = replace_generated_block(
            path.read_text(), "PUBLIC_BETA", render_public_beta_readme_block(lang)
        )
        current = path.read_text()
        if current != generated:
            if args.write:
                path.write_text(generated)
                print(f"UPDATED: {path}")
            else:
                errors.append(
                    f"STALE: {path} public beta block differs from generated content. Run with --write to update."
                )

    # 6. Report
    if errors:
        print(f"\n{'='*60}")
        print(f"  Doc Sync Check: {len(errors)} issue(s) found")
        print(f"{'='*60}\n")
        for e in errors:
            print(f"  - {e}")
        print(f"\nRun 'python scripts/sync_docs.py --write' to fix generated files.")
        if not args.write:
            sys.exit(1)
    else:
        print(f"Doc sync OK (v{version}): AGENTS.md -> SKILL.md, symlinks verified")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE_NAME = "oasyce"


def project_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise RuntimeError("could not read version from pyproject.toml")
    return match.group(1)


def expected_artifact_names(package_name: str, version: str) -> set[str]:
    normalized = version.replace("-", "_")
    return {
        f"{package_name}-{version}.tar.gz",
        f"{package_name}-{normalized}-py3-none-any.whl",
    }


def ensure_expected_artifacts(outdir: Path, package_name: str, version: str) -> list[Path]:
    expected = expected_artifact_names(package_name, version)
    present = {path.name: path for path in outdir.iterdir() if path.is_file()}
    missing = sorted(expected - set(present))
    if missing:
        raise RuntimeError(
            "missing release artifacts: " + ", ".join(missing)
        )
    return [present[name] for name in sorted(expected)]


def run_step(label: str, cmd: list[str]) -> None:
    print(f"[release-check] {label}")
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reproducible local release checks")
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest")
    parser.add_argument("--skip-build", action="store_true", help="Skip package build")
    args = parser.parse_args()

    version = project_version()

    run_step("doc sync", [sys.executable, "scripts/sync_docs.py"])
    if not args.skip_tests:
        run_step("tests", [sys.executable, "-m", "pytest", "--tb=short", "-q"])

    built_artifacts: list[Path] = []
    if not args.skip_build:
        with tempfile.TemporaryDirectory(prefix="oasyce-release-build-") as tmp:
            outdir = Path(tmp)
            run_step(
                "build",
                [sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(outdir)],
            )
            built_artifacts = ensure_expected_artifacts(outdir, PACKAGE_NAME, version)

    print("[release-check] ok")
    print(f"[release-check] version={version}")
    for artifact in built_artifacts:
        print(f"[release-check] artifact={artifact.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

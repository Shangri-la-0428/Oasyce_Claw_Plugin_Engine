from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "release_check.py"
SPEC = importlib.util.spec_from_file_location("release_check_module", SCRIPT_PATH)
assert SPEC and SPEC.loader
release_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_check)


def test_expected_artifact_names_match_python_build_convention():
    names = release_check.expected_artifact_names("oasyce", "2.3.2")
    assert names == {
        "oasyce-2.3.2.tar.gz",
        "oasyce-2.3.2-py3-none-any.whl",
    }


def test_ensure_expected_artifacts_returns_paths(tmp_path):
    (tmp_path / "oasyce-2.3.2.tar.gz").write_text("sdist", encoding="utf-8")
    (tmp_path / "oasyce-2.3.2-py3-none-any.whl").write_text("wheel", encoding="utf-8")

    artifacts = release_check.ensure_expected_artifacts(tmp_path, "oasyce", "2.3.2")

    assert [path.name for path in artifacts] == [
        "oasyce-2.3.2-py3-none-any.whl",
        "oasyce-2.3.2.tar.gz",
    ]

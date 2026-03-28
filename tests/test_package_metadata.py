from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path


def test_package_version_matches_pyproject():
    import oasyce

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = None
    for line in pyproject.read_text().splitlines():
        if line.startswith("version = "):
            expected = line.split('"')[1]
            break
    assert expected is not None
    assert oasyce.__version__ == expected


def test_package_import_survives_chain_client_import_error(monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "oasyce.chain_client":
            raise ModuleNotFoundError("requests")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    sys.modules.pop("oasyce", None)
    sys.modules.pop("oasyce.chain_client", None)

    try:
        module = importlib.import_module("oasyce")
        assert module.OasyceClient is None
        assert module.OasyceServiceFacade is not None
    finally:
        sys.modules.pop("oasyce", None)
        importlib.import_module("oasyce")

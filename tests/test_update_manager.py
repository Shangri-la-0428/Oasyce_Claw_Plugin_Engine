from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from oasyce import update_manager


def test_enable_managed_install_persists_auto_update(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    state = update_manager.enable_managed_install(auto_update=True)

    assert state["auto_update"] is True
    persisted = update_manager.read_managed_install_state()
    assert persisted["auto_update"] is True
    assert persisted["installed_via_bootstrap"] is True


def test_maybe_auto_update_skips_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    called = {"upgrade": False}
    monkeypatch.setattr(
        update_manager, "upgrade_managed_packages", lambda: called.update({"upgrade": True})
    )

    result = update_manager.maybe_auto_update_for_cli(
        module_name="oasyce.cli",
        argv=["info"],
        command_name="info",
    )

    assert result is False
    assert called["upgrade"] is False


def test_maybe_auto_update_reexecs_after_success(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    update_manager.enable_managed_install(auto_update=True)
    update_manager.write_managed_install_state(last_auto_update_check=0)

    monkeypatch.setattr(
        update_manager,
        "check_package_updates",
        lambda package_names=("oasyce", "odv"): [
            {
                "name": "oasyce",
                "current": "2.3.0",
                "latest": "2.4.0",
                "installed": True,
                "up_to_date": False,
            },
            {
                "name": "odv",
                "current": "0.2.1",
                "latest": "0.2.1",
                "installed": True,
                "up_to_date": True,
            },
        ],
    )
    monkeypatch.setattr(
        update_manager,
        "upgrade_managed_packages",
        lambda: SimpleNamespace(returncode=0, stderr=""),
    )

    seen = {}

    def fake_execvpe(executable, args, env):
        seen["executable"] = executable
        seen["args"] = args
        seen["env"] = env
        raise RuntimeError("reexec")

    monkeypatch.setattr(os, "execvpe", fake_execvpe)

    with pytest.raises(RuntimeError, match="reexec"):
        update_manager.maybe_auto_update_for_cli(
            module_name="oasyce.cli",
            argv=["quote", "ASSET_1"],
            command_name="quote",
        )

    assert seen["args"][0] == seen["executable"]
    assert seen["args"][1:4] == ["-m", "oasyce.cli", "quote"]
    assert seen["env"]["OASYCE_SKIP_AUTO_UPDATE"] == "1"

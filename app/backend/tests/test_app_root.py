from __future__ import annotations

import importlib


def test_backend_root_comes_from_environment(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "books"
    workspace.mkdir()
    monkeypatch.setenv("LEDGER_FLOW_ROOT", str(workspace))

    import main

    reloaded = importlib.reload(main)

    assert reloaded.ROOT_DIR == workspace
    assert reloaded.workspace_manager.app_root == workspace

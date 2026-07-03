from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_serves_packaged_frontend_shell(tmp_path, monkeypatch) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><title>Ledger Flow</title>", encoding="utf-8")
    (static_dir / "app.js").write_text("console.log('ledger-flow')", encoding="utf-8")
    monkeypatch.setenv("LEDGER_FLOW_STATIC_DIR", str(static_dir))

    import main

    client = TestClient(importlib.reload(main).app)

    root = client.get("/")
    assert root.status_code == 200
    assert "Ledger Flow" in root.text

    deep_link = client.get("/transactions")
    assert deep_link.status_code == 200
    assert "Ledger Flow" in deep_link.text

    asset = client.get("/app.js")
    assert asset.status_code == 200
    assert "ledger-flow" in asset.text


def test_api_routes_still_win_when_frontend_is_served(tmp_path, monkeypatch) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><title>Ledger Flow</title>", encoding="utf-8")
    monkeypatch.setenv("LEDGER_FLOW_STATIC_DIR", str(static_dir))

    import main

    client = TestClient(importlib.reload(main).app)

    response = client.get("/api/app/state")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

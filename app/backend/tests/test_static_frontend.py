from __future__ import annotations

import importlib


def test_serves_packaged_frontend_shell(tmp_path, monkeypatch) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><title>Ledger Flow</title>", encoding="utf-8")
    (static_dir / "app.js").write_text("console.log('ledger-flow')", encoding="utf-8")
    monkeypatch.setenv("LEDGER_FLOW_STATIC_DIR", str(static_dir))

    import main

    app = importlib.reload(main).app
    routes = {getattr(route, "path", ""): route for route in app.routes}

    root = routes["/"].endpoint()
    assert root.path == static_dir / "index.html"

    deep_link = routes["/{full_path:path}"].endpoint("transactions")
    assert deep_link.path == static_dir / "index.html"

    asset = routes["/{full_path:path}"].endpoint("app.js")
    assert asset.path == static_dir / "app.js"


def test_api_routes_still_win_when_frontend_is_served(tmp_path, monkeypatch) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><title>Ledger Flow</title>", encoding="utf-8")
    monkeypatch.setenv("LEDGER_FLOW_STATIC_DIR", str(static_dir))

    import main

    app = importlib.reload(main).app
    route_paths = [getattr(route, "path", "") for route in app.routes]
    assert route_paths.index("/api/app/state") < route_paths.index("/{full_path:path}")

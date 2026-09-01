from starlette.testclient import TestClient

import main
from app.server import app


class TestB11UiMigration:
    def test_root_redirects_to_claudex_studio(self):
        with TestClient(app) as client:
            response = client.get("/", follow_redirects=False)

        assert response.status_code in (302, 307)
        assert response.headers["location"] == "/claudex-studio/"

    def test_claudex_studio_is_served_from_default_ui_route(self):
        with TestClient(app) as client:
            response = client.get("/claudex-studio/index.html")

        assert response.status_code == 200
        assert "Claudex Studio" in response.text

    def test_legacy_paths_redirect_to_claudex_studio(self):
        with TestClient(app) as client:
            response = client.get("/html/index.html", follow_redirects=False)
            response2 = client.get("/legacy/index.html", follow_redirects=False)

        assert response.status_code in (302, 307)
        assert response.headers["location"] == "/claudex-studio/"
        assert response2.status_code in (302, 307)
        assert response2.headers["location"] == "/claudex-studio/"

    def test_main_starts_runtime_and_http_servers(self, monkeypatch):
        called = {}

        def fake_start_bridge():
            called["bridge"] = True

        async def fake_run_server(host, port):
            called["runtime_server"] = (host, port)

        def fake_runtime_thread(*args, **kwargs):
            class DummyThread:
                def __init__(self, target=None, daemon=None):
                    self.target = target
                    self.daemon = daemon

                def start(self):
                    called["runtime_start"] = True
                    self.target()

            return DummyThread(*args, **kwargs)

        def fake_http_server():
            called["http"] = True
            raise KeyboardInterrupt

        monkeypatch.setattr(main, "start_bridge", fake_start_bridge)
        monkeypatch.setattr(main, "run_server", fake_run_server)
        monkeypatch.setattr(main.threading, "Thread", fake_runtime_thread)
        monkeypatch.setattr(main, "start_http_server", fake_http_server)

        try:
            main.main()
        except KeyboardInterrupt:
            pass

        assert called.get("bridge") is True
        assert called.get("runtime_start") is True
        assert called.get("runtime_server") == ("127.0.0.1", 8765)
        assert called.get("http") is True

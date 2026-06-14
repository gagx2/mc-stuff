import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "mcupd", pathlib.Path(__file__).resolve().parents[1] / "mc-autoupdate.py")
mcupd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcupd)


def test_geyser_latest(monkeypatch):
    payload = {"version": "2.10.1", "build": 1165,
               "downloads": {"spigot": {"name": "Geyser-Spigot.jar"}}}
    monkeypatch.setattr(mcupd, "http_get_json", lambda url, **k: payload)
    got = mcupd.geyser_latest("geyser")
    assert got["build"] == 1165
    assert got["url"] == ("https://download.geysermc.org/v2/projects/geyser/"
                          "versions/latest/builds/latest/downloads/spigot")


def test_github_latest_release(monkeypatch):
    payload = {"tag_name": "5.9.1", "assets": [
        {"name": "ViaVersion-5.9.1.jar",
         "browser_download_url": "https://x/ViaVersion-5.9.1.jar"},
        {"name": "checksums.txt", "browser_download_url": "https://x/checksums.txt"}]}
    monkeypatch.setattr(mcupd, "http_get_json", lambda url, **k: payload)
    got = mcupd.github_latest_release("ViaVersion/ViaVersion")
    assert got["tag"] == "5.9.1"
    assert got["jar_url"] == "https://x/ViaVersion-5.9.1.jar"


def test_find_latest_paper(monkeypatch):
    def fake_get(url, **k):
        if url.endswith("/projects/paper"):
            return {"versions": ["1.21.8", "1.21.11", "26.1.2"]}
        if url.endswith("/versions/26.1.2/builds"):
            return [{"id": 5, "channel": "STABLE", "time": "2026-06-01T00:00:00Z",
                     "downloads": {"server:default": {"url": "u", "name": "paper-26.1.2-5.jar",
                                   "checksums": {"sha256": "h"}}}}]
        return []
    monkeypatch.setattr(mcupd, "http_get_json", fake_get)
    got = mcupd.find_latest_paper(min_age_days=0, now_epoch=2_000_000_000)
    assert got["version"] == "26.1.2" and got["build"] == 5 and got["sha256"] == "h"


def test_crafty_action_builds_request(monkeypatch):
    captured = {}

    class FakeResp:
        def read(self):
            return b'{"status":"ok"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0, context=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["auth"] = req.headers.get("Authorization")
        return FakeResp()

    monkeypatch.setattr(mcupd.urllib.request, "urlopen", fake_urlopen)
    c = mcupd.CraftyClient("https://localhost:8443", "JWT123")
    ok = c.action("SID", "restart_server")
    assert ok is True
    assert captured["url"] == "https://localhost:8443/api/v2/servers/SID/action/restart_server"
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer JWT123"


def test_crafty_patch_server(monkeypatch):
    captured = {}

    class FakeResp:
        def read(self):
            return b'{"status":"ok"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0, context=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["body"] = req.data
        return FakeResp()

    monkeypatch.setattr(mcupd.urllib.request, "urlopen", fake_urlopen)
    c = mcupd.CraftyClient("https://localhost:8443", "JWT123")
    ok = c.patch_server("SID", {"executable": "paper.jar"})
    assert ok is True
    assert captured["method"] == "PATCH"
    assert b'"executable": "paper.jar"' in captured["body"]

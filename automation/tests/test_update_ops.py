import importlib.util
import pathlib

from conftest import make_jar

spec = importlib.util.spec_from_file_location(
    "mcupd", pathlib.Path(__file__).resolve().parents[1] / "mc-autoupdate.py")
mcupd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcupd)


def _logger():
    lines = []
    return (lambda m: lines.append(m)), lines


def test_geyser_updates_when_newer(tmp_path, monkeypatch):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "Geyser-Spigot.jar").write_bytes(
        make_jar({"git.properties": "git.build.number=1100\n"}))
    monkeypatch.setattr(mcupd, "geyser_latest",
                        lambda p: {"build": 1165, "version": "2.10.1", "url": "U"})

    def fake_dl(url, dest, **k):
        with open(dest, "wb") as f:
            f.write(make_jar({"git.properties": "git.build.number=1165\n"}))

    monkeypatch.setattr(mcupd, "http_download", fake_dl)
    log, _ = _logger()
    changed = mcupd.update_one_geyser(str(plugins), "geyser", "Geyser-Spigot.jar", log, dry_run=False)
    assert changed is True
    assert mcupd.read_git_build_number(str(plugins / "Geyser-Spigot.jar")) == 1165


def test_geyser_noop_when_current(tmp_path, monkeypatch):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "Geyser-Spigot.jar").write_bytes(
        make_jar({"git.properties": "git.build.number=1165\n"}))
    monkeypatch.setattr(mcupd, "geyser_latest",
                        lambda p: {"build": 1165, "version": "2.10.1", "url": "U"})
    called = {"n": 0}
    monkeypatch.setattr(mcupd, "http_download", lambda *a, **k: called.__setitem__("n", 1))
    log, _ = _logger()
    changed = mcupd.update_one_geyser(str(plugins), "geyser", "Geyser-Spigot.jar", log, dry_run=False)
    assert changed is False and called["n"] == 0


def test_via_updates_and_renames(tmp_path, monkeypatch):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    old = plugins / "ViaVersion-5.7.1.jar"
    old.write_bytes(make_jar({"plugin.yml": "version: 5.7.1\n"}))
    monkeypatch.setattr(mcupd, "github_latest_release",
                        lambda repo: {"tag": "5.9.1", "jar_url": "U"})
    monkeypatch.setattr(mcupd, "http_download",
                        lambda url, dest, **k: open(dest, "wb").write(
                            make_jar({"plugin.yml": "version: 5.9.1\n"})))
    log, _ = _logger()
    changed = mcupd.update_one_via(str(plugins), "ViaVersion/ViaVersion", "ViaVersion", log, dry_run=False)
    assert changed is True
    assert not old.exists()
    assert (plugins / "ViaVersion-5.9.1.jar").exists()


def test_update_paper_jumps_version(tmp_path, monkeypatch):
    server_dir = tmp_path / "srv"
    server_dir.mkdir()
    cfg = {"server_dir": str(server_dir), "autoupdate_dir": str(tmp_path),
           "paper_canonical_jar": "paper.jar", "jvm_args": "-Xms1G -Xmx2G",
           "server_id": "SID", "mc_version_min_age_days": 0}
    state = {"paper": {"version": "1.21.8", "build": 60}}
    monkeypatch.setattr(mcupd, "find_latest_paper",
                        lambda **k: {"version": "26.1.2", "build": 5, "url": "U",
                                     "sha256": "h", "name": "paper-26.1.2-5.jar"})
    monkeypatch.setattr(mcupd, "http_download", lambda url, dest, **k: open(dest, "wb").write(b"jar"))
    calls = []

    class FakeCrafty:
        def action(self, sid, a):
            calls.append(("action", a))
            return True

        def patch_server(self, sid, f):
            calls.append(("patch", f))
            return True

    log, _ = _logger()
    changed = mcupd.update_paper(cfg, FakeCrafty(), state, log, dry_run=False, now_epoch=2_000_000_000)
    assert changed is True
    assert ("action", "backup_server") in calls
    assert any(c[0] == "patch" and c[1]["executable"] == "paper.jar" for c in calls)
    assert state["paper"]["version"] == "26.1.2" and state["paper"]["build"] == 5
    assert (server_dir / "paper.jar").exists()


def test_update_paper_noop_same_build(tmp_path, monkeypatch):
    cfg = {"server_dir": str(tmp_path), "autoupdate_dir": str(tmp_path),
           "paper_canonical_jar": "paper.jar", "jvm_args": "x", "server_id": "SID",
           "mc_version_min_age_days": 0}
    state = {"paper": {"version": "1.21.8", "build": 60}}
    monkeypatch.setattr(mcupd, "find_latest_paper",
                        lambda **k: {"version": "1.21.8", "build": 60, "url": "U",
                                     "sha256": "h", "name": "n"})
    log, _ = _logger()
    changed = mcupd.update_paper(cfg, None, state, log, dry_run=False, now_epoch=1)
    assert changed is False


def test_should_restart():
    assert mcupd.should_restart("on-change", True) is True
    assert mcupd.should_restart("on-change", False) is False
    assert mcupd.should_restart("always", False) is True
    assert mcupd.should_restart("always", True) is True
    assert mcupd.should_restart("never", True) is False


def test_state_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    mcupd.save_state(str(p), {"paper": {"version": "1.21.8", "build": 60}})
    assert mcupd.load_state(str(p))["paper"]["build"] == 60
    assert mcupd.load_state(str(tmp_path / "missing.json")) == {}

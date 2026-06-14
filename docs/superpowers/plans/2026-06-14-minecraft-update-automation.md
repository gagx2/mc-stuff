# Minecraft Update Automation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a nightly Dokploy-scheduled automation that keeps Geyser/Floodgate/Via, Paper, Crafty, and playit current and the playit tunnel always up — plus in-depth documentation of the whole stack.

**Architecture:** A single Dokploy `dokploy-server` cron (3:30 AM UTC) runs an orchestrator (`nightly-maintenance.sh`) inside the Dokploy container. It (1) `docker exec`s a pure-`python3` updater (`mc-autoupdate.py`) inside `crafty_container` to update plugins + Paper, back up, and restart the MC server via the Crafty API; then (2) pulls the Crafty/playit images and redeploys via Dokploy deploy-webhooks only when the image digest changed; (3) ensures playit is running. A one-time `deploy.sh` installs the updater into the Crafty volume, fixes the playit compose (`:1.0` + `restart: unless-stopped`), and creates the schedule.

**Tech Stack:** Python 3.12 stdlib only (`urllib`, `ssl`, `zipfile`, `hashlib`, `json`) — the Crafty container has no curl/wget/unzip; pytest for unit tests (dev only); bash; Dokploy REST API (`x-api-key` / deploy webhooks); Crafty Controller API v2 (Bearer JWT); GeyserMC / GitHub / PaperMC Fill v3 download APIs.

**Reference values (from the spec):**
- SSH: `ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210`
- Dokploy API (via SSH): `http://localhost:3000/api`, header `x-api-key: $DOKPLOY_KEY`; org `eFbswAqh7vlP_F7SfdS8D`
- Crafty: `https://localhost:8443/api/v2` (self-signed), header `Authorization: Bearer $CRAFTY_JWT`
- MC server id: `394a3479-b8e9-4f4f-aa36-49c87eafe548`; dir `/crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548`
- Crafty compose webhook token: `P4G6U5tnpT1UbETaPDfcx`; image `registry.gitlab.com/crafty-controller/crafty-4:latest`
- playit compose id `Up4B06-EaIzJuYH3mxgTj`, webhook `FohNmoNN_pzIgkfljoAJo`; image → `ghcr.io/playit-cloud/playit-agent:1.0`
- Updater install dir (in Crafty volume, persistent): `/crafty/import/autoupdate/`

> **Secrets:** `$DOKPLOY_KEY` and `$CRAFTY_JWT` are passed via environment to `deploy.sh`; never commit them. `config.json` on the server holds the Crafty JWT (chmod 600). The repo only ever contains `config.example.json` with placeholders.

---

## File Structure

```
automation/
  mc-autoupdate.py            in-Crafty updater (plugins + Paper + restart). Pure-stdlib. Built across Tasks 2–9.
  nightly-maintenance.sh      dokploy-server orchestrator script (Task 10)
  config.example.json         config template, no secrets (Task 1)
  deploy.sh                   idempotent installer, runs from workstation over SSH (Task 11)
  tests/
    test_jar.py               jar-inspection unit tests (Task 2)
    test_versions.py          version-comparison unit tests (Task 3)
    test_paper_select.py      Paper stable-build selection tests (Task 4)
    test_http_clients.py      geyser/github/paper/crafty client tests via monkeypatch (Tasks 5–6)
    test_update_ops.py        update_plugins/update_paper tests with temp dirs (Tasks 7–8)
    conftest.py               shared fixtures (in-memory jar builder, sample API JSON)
  requirements-dev.txt        pytest
docs/
  01-architecture.md          Task 13
  02-minecraft-server.md      Task 14
  03-green-axolotl.md         Task 15
  04-bedrock-connectivity.md  Task 16
  05-updates-automation.md    Task 17
  06-runbook.md               Task 18
README.md                     Task 19
```

`mc-autoupdate.py` is built **additively** across Tasks 2–9: each task appends functions/classes and their tests. Keep names exactly as written here.

---

## Task 1: Scaffold automation directory, pytest, config template

**Files:**
- Create: `automation/requirements-dev.txt`
- Create: `automation/config.example.json`
- Create: `automation/tests/conftest.py`
- Create: `automation/mc-autoupdate.py` (header + imports only)

- [ ] **Step 1: Create dev requirements**

`automation/requirements-dev.txt`:
```
pytest>=8
```

- [ ] **Step 2: Create config template**

`automation/config.example.json`:
```json
{
  "crafty_base": "https://localhost:8443",
  "crafty_jwt": "REPLACE_WITH_CRAFTY_JWT",
  "server_id": "394a3479-b8e9-4f4f-aa36-49c87eafe548",
  "server_dir": "/crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548",
  "plugins_dir": "/crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/plugins",
  "autoupdate_dir": "/crafty/import/autoupdate",
  "jvm_args": "-Xms1000M -Xmx2000M",
  "paper_canonical_jar": "paper.jar",
  "mc_version_min_age_days": 0,
  "keep_logs": 30,
  "update_plugins": true,
  "update_paper": true,
  "restart": true
}
```

- [ ] **Step 3: Create the module header**

`automation/mc-autoupdate.py`:
```python
#!/usr/bin/env python3
"""Nightly updater for the green-axolotl Minecraft server.

Runs INSIDE crafty_container (python3 stdlib only — no curl/wget/unzip).
Updates Geyser/Floodgate/ViaVersion/ViaBackwards plugins and Paper, then
restarts the server via the Crafty API. See docs/05-updates-automation.md.
"""
import json
import os
import re
import ssl
import sys
import time
import zipfile
import hashlib
import tempfile
import urllib.request
import urllib.error
from datetime import datetime, timezone
```

- [ ] **Step 4: Create shared test fixtures**

`automation/tests/conftest.py`:
```python
import io
import zipfile
import pytest


def make_jar(members: dict) -> bytes:
    """Build an in-memory .jar (zip) with the given {name: text} members."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in members.items():
            z.writestr(name, text)
    return buf.getvalue()


@pytest.fixture
def jar_factory(tmp_path):
    def _factory(filename: str, members: dict) -> str:
        path = tmp_path / filename
        path.write_bytes(make_jar(members))
        return str(path)
    return _factory
```

- [ ] **Step 5: Verify pytest collects (no tests yet)**

Run: `cd automation && python3 -m pytest -q`
Expected: `no tests ran` (exit 5) — confirms pytest + imports work.

- [ ] **Step 6: Commit**

```bash
git add automation/
git commit -m "scaffold mc update automation (config template + test harness)"
```

---

## Task 2: Jar inspection — read installed plugin versions

**Files:**
- Modify: `automation/mc-autoupdate.py` (append functions)
- Create: `automation/tests/test_jar.py`

- [ ] **Step 1: Write failing tests**

`automation/tests/test_jar.py`:
```python
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mcupd", pathlib.Path(__file__).resolve().parents[1] / "mc-autoupdate.py")
mcupd = importlib.util.module_from_spec(spec); spec.loader.exec_module(mcupd)


def test_read_git_build_number(jar_factory):
    jar = jar_factory("Geyser-Spigot.jar", {
        "git.properties": "git.branch=master\ngit.build.number=1165\ngit.build.version=2.10.1-b1165\n"
    })
    assert mcupd.read_git_build_number(jar) == 1165


def test_read_git_build_number_missing(jar_factory):
    jar = jar_factory("x.jar", {"other.txt": "hi"})
    assert mcupd.read_git_build_number(jar) is None


def test_read_plugin_yml_version(jar_factory):
    jar = jar_factory("ViaVersion.jar", {"plugin.yml": "name: ViaVersion\nversion: 5.7.1\nmain: x\n"})
    assert mcupd.read_plugin_yml_version(jar) == "5.7.1"


def test_read_plugin_yml_version_quoted(jar_factory):
    jar = jar_factory("V.jar", {"plugin.yml": "name: V\nversion: '5.9.1'\n"})
    assert mcupd.read_plugin_yml_version(jar) == "5.9.1"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd automation && python3 -m pytest tests/test_jar.py -q`
Expected: FAIL — `AttributeError: module 'mcupd' has no attribute 'read_git_build_number'`

- [ ] **Step 3: Implement**

Append to `automation/mc-autoupdate.py`:
```python
def read_jar_member(jar_path: str, member: str) -> str | None:
    """Return the text of a member inside a .jar (zip), or None if absent."""
    try:
        with zipfile.ZipFile(jar_path) as z:
            return z.read(member).decode("utf-8", "ignore")
    except (KeyError, zipfile.BadZipFile, FileNotFoundError):
        return None


def read_git_build_number(jar_path: str) -> int | None:
    """Geyser/Floodgate embed git.properties with git.build.number=<int>."""
    text = read_jar_member(jar_path, "git.properties")
    if not text:
        return None
    m = re.search(r"git\.build\.number=(\d+)", text)
    return int(m.group(1)) if m else None


def read_plugin_yml_version(jar_path: str) -> str | None:
    """ViaVersion/ViaBackwards/etc expose version in plugin.yml."""
    text = read_jar_member(jar_path, "plugin.yml")
    if not text:
        return None
    m = re.search(r"^version:\s*['\"]?([^'\"\r\n]+)['\"]?\s*$", text, re.MULTILINE)
    return m.group(1).strip() if m else None
```

- [ ] **Step 4: Run to verify pass**

Run: `cd automation && python3 -m pytest tests/test_jar.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add automation/mc-autoupdate.py automation/tests/test_jar.py
git commit -m "mc-autoupdate: read installed plugin versions from jars"
```

---

## Task 3: Version comparison helpers

**Files:**
- Modify: `automation/mc-autoupdate.py`
- Create: `automation/tests/test_versions.py`

- [ ] **Step 1: Write failing tests**

`automation/tests/test_versions.py`:
```python
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "mcupd", pathlib.Path(__file__).resolve().parents[1] / "mc-autoupdate.py")
mcupd = importlib.util.module_from_spec(spec); spec.loader.exec_module(mcupd)


def test_parse_version_tuple():
    assert mcupd.parse_version_tuple("5.9.1") == (5, 9, 1)
    assert mcupd.parse_version_tuple("1.21.8") == (1, 21, 8)
    assert mcupd.parse_version_tuple("26.1.2") == (26, 1, 2)
    assert mcupd.parse_version_tuple("5.9.1-SNAPSHOT") == (5, 9, 1)


def test_semver_newer():
    assert mcupd.semver_newer("5.7.1", "5.9.1") is True
    assert mcupd.semver_newer("5.9.1", "5.9.1") is False
    assert mcupd.semver_newer("5.9.1", "5.7.1") is False
    assert mcupd.semver_newer(None, "5.9.1") is True   # unknown installed -> update


def test_compare_mc_versions():
    assert mcupd.compare_mc_versions("1.21.8", "1.21.11") < 0
    assert mcupd.compare_mc_versions("1.21.11", "26.1.2") < 0
    assert mcupd.compare_mc_versions("26.1.2", "26.1.2") == 0
    assert mcupd.compare_mc_versions("26.2", "26.1.2") > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd automation && python3 -m pytest tests/test_versions.py -q`
Expected: FAIL — attribute errors.

- [ ] **Step 3: Implement**

Append to `automation/mc-autoupdate.py`:
```python
def parse_version_tuple(s: str) -> tuple:
    """'5.9.1-SNAPSHOT' -> (5, 9, 1). Non-numeric suffixes are dropped."""
    nums = re.findall(r"\d+", s.split("-")[0].split("+")[0])
    return tuple(int(n) for n in nums)


def semver_newer(installed: str | None, latest: str) -> bool:
    if installed is None:
        return True
    return parse_version_tuple(latest) > parse_version_tuple(installed)


def compare_mc_versions(a: str, b: str) -> int:
    ta, tb = parse_version_tuple(a), parse_version_tuple(b)
    return (ta > tb) - (ta < tb)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd automation && python3 -m pytest tests/test_versions.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add automation/mc-autoupdate.py automation/tests/test_versions.py
git commit -m "mc-autoupdate: version comparison helpers"
```

---

## Task 4: Paper stable-build selection (pure)

**Files:**
- Modify: `automation/mc-autoupdate.py`
- Create: `automation/tests/test_paper_select.py`

PaperMC Fill v3 `GET /v3/projects/paper/versions/{V}/builds` returns a list of build objects:
`{"id": 60, "channel": "STABLE", "time": "2026-...Z", "downloads": {"server:default": {"url": "...", "checksums": {"sha256": "..."}, "name": "paper-1.21.8-60.jar"}}}`.

- [ ] **Step 1: Write failing tests**

`automation/tests/test_paper_select.py`:
```python
import importlib.util, pathlib, calendar, time
spec = importlib.util.spec_from_file_location(
    "mcupd", pathlib.Path(__file__).resolve().parents[1] / "mc-autoupdate.py")
mcupd = importlib.util.module_from_spec(spec); spec.loader.exec_module(mcupd)

BUILDS = [
    {"id": 58, "channel": "STABLE", "time": "2026-05-01T00:00:00.000Z",
     "downloads": {"server:default": {"url": "u58", "name": "paper-1.21.8-58.jar",
                                       "checksums": {"sha256": "h58"}}}},
    {"id": 60, "channel": "STABLE", "time": "2026-06-01T00:00:00.000Z",
     "downloads": {"server:default": {"url": "u60", "name": "paper-1.21.8-60.jar",
                                       "checksums": {"sha256": "h60"}}}},
    {"id": 61, "channel": "ALPHA", "time": "2026-06-10T00:00:00.000Z",
     "downloads": {"server:default": {"url": "u61", "name": "paper-1.21.8-61.jar",
                                       "checksums": {"sha256": "h61"}}}},
]
NOW = calendar.timegm(time.strptime("2026-06-14", "%Y-%m-%d"))


def test_selects_newest_stable_not_alpha():
    b = mcupd.select_stable_build(BUILDS, min_age_days=0, now_epoch=NOW)
    assert b["id"] == 60 and b["url"] == "u60" and b["sha256"] == "h60"


def test_min_age_excludes_too_recent():
    # require 30 days old: build 60 (13 days) excluded, falls back to 58 (44 days)
    b = mcupd.select_stable_build(BUILDS, min_age_days=30, now_epoch=NOW)
    assert b["id"] == 58


def test_no_stable_returns_none():
    only_alpha = [BUILDS[2]]
    assert mcupd.select_stable_build(only_alpha, min_age_days=0, now_epoch=NOW) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd automation && python3 -m pytest tests/test_paper_select.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Append to `automation/mc-autoupdate.py`:
```python
def _iso_to_epoch(s: str) -> int:
    # "2026-06-01T00:00:00.000Z" -> epoch seconds
    s = s.replace("Z", "").split(".")[0]
    dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def select_stable_build(builds: list, min_age_days: int, now_epoch: int) -> dict | None:
    """Pick the newest STABLE build at least min_age_days old. Returns
    {id, url, sha256, name} or None."""
    cutoff = now_epoch - min_age_days * 86400
    best = None
    for b in builds:
        if str(b.get("channel", "")).upper() not in ("STABLE", "RECOMMENDED"):
            continue
        if _iso_to_epoch(b["time"]) > cutoff:
            continue
        dl = b["downloads"]["server:default"]
        cand = {"id": b["id"], "url": dl["url"],
                "sha256": dl.get("checksums", {}).get("sha256"), "name": dl["name"]}
        if best is None or cand["id"] > best["id"]:
            best = cand
    return best
```

- [ ] **Step 4: Run to verify pass**

Run: `cd automation && python3 -m pytest tests/test_paper_select.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add automation/mc-autoupdate.py automation/tests/test_paper_select.py
git commit -m "mc-autoupdate: Paper stable-build selection"
```

---

## Task 5: HTTP layer + upstream clients (Geyser/GitHub/Paper)

**Files:**
- Modify: `automation/mc-autoupdate.py`
- Create: `automation/tests/test_http_clients.py`

- [ ] **Step 1: Write failing tests** (monkeypatch the low-level fetchers)

`automation/tests/test_http_clients.py`:
```python
import importlib.util, pathlib, json
spec = importlib.util.spec_from_file_location(
    "mcupd", pathlib.Path(__file__).resolve().parents[1] / "mc-autoupdate.py")
mcupd = importlib.util.module_from_spec(spec); spec.loader.exec_module(mcupd)


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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd automation && python3 -m pytest tests/test_http_clients.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement** (append)

```python
USER_AGENT = "green-axolotl-autoupdate/1.0 (+https://crafty.tail.keeso.com)"


def _ctx(insecure: bool):
    if not insecure:
        return None
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def http_get_json(url: str, headers: dict | None = None, insecure: bool = False) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60, context=_ctx(insecure)) as r:
        return json.loads(r.read().decode("utf-8"))


def http_download(url: str, dest: str, expected_sha256: str | None = None,
                  headers: dict | None = None) -> None:
    """Download url to dest (urllib follows 30x). Verify sha256 if given. Atomic."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    h = hashlib.sha256()
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest) or ".", suffix=".part")
    try:
        with urllib.request.urlopen(req, timeout=120) as r, os.fdopen(fd, "wb") as out:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                h.update(chunk)
                out.write(chunk)
        if expected_sha256 and h.hexdigest().lower() != expected_sha256.lower():
            raise ValueError(f"sha256 mismatch for {url}: {h.hexdigest()} != {expected_sha256}")
        # sanity: must be a valid zip/jar
        if not zipfile.is_zipfile(tmp):
            raise ValueError(f"downloaded file is not a valid jar/zip: {url}")
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


GEYSER_API = "https://download.geysermc.org/v2/projects/{p}/versions/latest/builds/latest"


def geyser_latest(project: str) -> dict:
    """project in {'geyser','floodgate'}. Returns {build, version, url}."""
    data = http_get_json(GEYSER_API.format(p=project))
    return {"build": data["build"], "version": data["version"],
            "url": GEYSER_API.format(p=project) + "/downloads/spigot"}


def github_latest_release(repo: str) -> dict:
    """repo like 'ViaVersion/ViaVersion'. Returns {tag, jar_url}."""
    data = http_get_json(f"https://api.github.com/repos/{repo}/releases/latest",
                         headers={"Accept": "application/vnd.github+json"})
    jar = next((a["browser_download_url"] for a in data.get("assets", [])
                if a["name"].endswith(".jar")), None)
    return {"tag": data["tag_name"].lstrip("v"), "jar_url": jar}


PAPER_FILL = "https://fill.papermc.io/v3/projects/paper"


def find_latest_paper(min_age_days: int, now_epoch: int, max_versions: int = 5) -> dict | None:
    """Highest MC version (newest first) that has a usable STABLE build.
    Returns {version, build, url, sha256, name} or None."""
    versions = http_get_json(PAPER_FILL).get("versions", [])
    for v in list(reversed(versions))[:max_versions]:
        builds = http_get_json(f"{PAPER_FILL}/versions/{v}/builds")
        b = select_stable_build(builds, min_age_days, now_epoch)
        if b:
            return {"version": v, **b}
    return None
```

- [ ] **Step 4: Run to verify pass**

Run: `cd automation && python3 -m pytest tests/test_http_clients.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add automation/mc-autoupdate.py automation/tests/test_http_clients.py
git commit -m "mc-autoupdate: HTTP layer + Geyser/GitHub/Paper clients"
```

---

## Task 6: Crafty API client

**Files:**
- Modify: `automation/mc-autoupdate.py`
- Modify: `automation/tests/test_http_clients.py` (append)

- [ ] **Step 1: Write failing tests** (capture the request urllib would send)

Append to `automation/tests/test_http_clients.py`:
```python
def test_crafty_action_builds_request(monkeypatch):
    captured = {}
    class FakeResp:
        def read(self): return b'{"status":"ok"}'
        def __enter__(self): return self
        def __exit__(self, *a): return False
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
        def read(self): return b'{"status":"ok"}'
        def __enter__(self): return self
        def __exit__(self, *a): return False
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd automation && python3 -m pytest tests/test_http_clients.py -q`
Expected: FAIL — `CraftyClient` undefined.

- [ ] **Step 3: Implement** (append)

```python
class CraftyClient:
    def __init__(self, base: str, jwt: str):
        self.base = base.rstrip("/")
        self.jwt = jwt

    def _send(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.jwt}",
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=120, context=_ctx(insecure=True)) as r:
            return json.loads(r.read().decode("utf-8"))

    def action(self, server_id: str, action: str) -> bool:
        res = self._send("POST", f"/api/v2/servers/{server_id}/action/{action}")
        return res.get("status") == "ok"

    def patch_server(self, server_id: str, fields: dict) -> bool:
        res = self._send("PATCH", f"/api/v2/servers/{server_id}", fields)
        return res.get("status") == "ok"

    def get_server(self, server_id: str) -> dict:
        return self._send("GET", f"/api/v2/servers/{server_id}").get("data", {})
```

- [ ] **Step 4: Run to verify pass**

Run: `cd automation && python3 -m pytest tests/test_http_clients.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add automation/mc-autoupdate.py automation/tests/test_http_clients.py
git commit -m "mc-autoupdate: Crafty API client (action/patch/get)"
```

---

## Task 7: update_plugins() — download + atomic replace when newer

**Files:**
- Modify: `automation/mc-autoupdate.py`
- Create: `automation/tests/test_update_ops.py`

Plugin registry (name → jar filename glob + source). Geyser/Floodgate compare by build number; Via by semver tag.

- [ ] **Step 1: Write failing tests**

`automation/tests/test_update_ops.py`:
```python
import importlib.util, pathlib, os, json
from conftest import make_jar
spec = importlib.util.spec_from_file_location(
    "mcupd", pathlib.Path(__file__).resolve().parents[1] / "mc-autoupdate.py")
mcupd = importlib.util.module_from_spec(spec); spec.loader.exec_module(mcupd)


def _logger():
    lines = []
    return (lambda m: lines.append(m)), lines


def test_geyser_updates_when_newer(tmp_path, monkeypatch):
    plugins = tmp_path / "plugins"; plugins.mkdir()
    (plugins / "Geyser-Spigot.jar").write_bytes(
        make_jar({"git.properties": "git.build.number=1100\n"}))
    monkeypatch.setattr(mcupd, "geyser_latest",
                        lambda p: {"build": 1165, "version": "2.10.1", "url": "U"})
    def fake_dl(url, dest, **k):
        # write a jar that reports the new build
        with open(dest, "wb") as f:
            f.write(make_jar({"git.properties": "git.build.number=1165\n"}))
    monkeypatch.setattr(mcupd, "http_download", fake_dl)
    log, lines = _logger()
    changed = mcupd.update_one_geyser(str(plugins), "geyser", "Geyser-Spigot.jar", log, dry_run=False)
    assert changed is True
    assert mcupd.read_git_build_number(str(plugins / "Geyser-Spigot.jar")) == 1165


def test_geyser_noop_when_current(tmp_path, monkeypatch):
    plugins = tmp_path / "plugins"; plugins.mkdir()
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
    plugins = tmp_path / "plugins"; plugins.mkdir()
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
    assert not old.exists()                                  # old jar removed
    assert (plugins / "ViaVersion-5.9.1.jar").exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd automation && python3 -m pytest tests/test_update_ops.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement** (append)

```python
import glob as _glob


def _find_jar(plugins_dir: str, pattern: str) -> str | None:
    hits = sorted(_glob.glob(os.path.join(plugins_dir, pattern)))
    return hits[0] if hits else None


def update_one_geyser(plugins_dir: str, project: str, jar_name: str, log, dry_run: bool) -> bool:
    """Geyser/Floodgate: compare git.build.number, replace in place if newer."""
    path = os.path.join(plugins_dir, jar_name)
    installed = read_git_build_number(path) if os.path.exists(path) else None
    latest = geyser_latest(project)
    if installed is not None and installed >= latest["build"]:
        log(f"[ok] {project}: build {installed} up to date")
        return False
    log(f"[update] {project}: {installed} -> {latest['build']} ({latest['version']})")
    if dry_run:
        return True
    http_download(latest["url"], path)
    log(f"[ok] {project}: installed build {read_git_build_number(path)}")
    return True


def update_one_via(plugins_dir: str, repo: str, name: str, log, dry_run: bool) -> bool:
    """ViaVersion/ViaBackwards: compare plugin.yml version, download new
    versioned jar, remove the old one."""
    old = _find_jar(plugins_dir, f"{name}-*.jar")
    installed = read_plugin_yml_version(old) if old else None
    latest = github_latest_release(repo)
    if not semver_newer(installed, latest["tag"]):
        log(f"[ok] {name}: {installed} up to date")
        return False
    log(f"[update] {name}: {installed} -> {latest['tag']}")
    if dry_run:
        return True
    dest = os.path.join(plugins_dir, f"{name}-{latest['tag']}.jar")
    http_download(latest["jar_url"], dest)
    if old and os.path.abspath(old) != os.path.abspath(dest):
        os.remove(old)
    log(f"[ok] {name}: installed {read_plugin_yml_version(dest)}")
    return True


def update_plugins(cfg: dict, log, dry_run: bool) -> bool:
    pd = cfg["plugins_dir"]
    changed = False
    changed |= update_one_geyser(pd, "geyser", "Geyser-Spigot.jar", log, dry_run)
    changed |= update_one_geyser(pd, "floodgate", "floodgate-spigot.jar", log, dry_run)
    changed |= update_one_via(pd, "ViaVersion/ViaVersion", "ViaVersion", log, dry_run)
    changed |= update_one_via(pd, "ViaVersion/ViaBackwards", "ViaBackwards", log, dry_run)
    return changed
```

- [ ] **Step 4: Run to verify pass**

Run: `cd automation && python3 -m pytest tests/test_update_ops.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add automation/mc-autoupdate.py automation/tests/test_update_ops.py
git commit -m "mc-autoupdate: update_plugins (Geyser/Floodgate/Via)"
```

---

## Task 8: update_paper() + state tracking

**Files:**
- Modify: `automation/mc-autoupdate.py`
- Modify: `automation/tests/test_update_ops.py` (append)

State file `<autoupdate_dir>/state.json`: `{"paper": {"version": "1.21.8", "build": 0}}`. Bootstrapped on first run from the server's current `executable` filename via the Crafty API.

- [ ] **Step 1: Write failing tests** (append)

```python
def test_update_paper_jumps_version(tmp_path, monkeypatch):
    server_dir = tmp_path / "srv"; server_dir.mkdir()
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
        def action(self, sid, a): calls.append(("action", a)); return True
        def patch_server(self, sid, f): calls.append(("patch", f)); return True
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


def test_state_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    mcupd.save_state(str(p), {"paper": {"version": "1.21.8", "build": 60}})
    assert mcupd.load_state(str(p))["paper"]["build"] == 60
    assert mcupd.load_state(str(tmp_path / "missing.json")) == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd automation && python3 -m pytest tests/test_update_ops.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement** (append)

```python
def load_state(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def _paper_newer(cur_ver: str, cur_build: int, new_ver: str, new_build: int) -> bool:
    c = compare_mc_versions(new_ver, cur_ver)
    if c > 0:
        return True
    if c < 0:
        return False
    return new_build > cur_build


def update_paper(cfg: dict, crafty, state: dict, log, dry_run: bool, now_epoch: int) -> bool:
    cur = state.get("paper", {"version": "0", "build": 0})
    latest = find_latest_paper(min_age_days=cfg.get("mc_version_min_age_days", 0),
                               now_epoch=now_epoch)
    if not latest:
        log("[warn] paper: no stable build found")
        return False
    if not _paper_newer(cur["version"], cur["build"], latest["version"], latest["build"]):
        log(f"[ok] paper: {cur['version']} build {cur['build']} up to date")
        return False
    log(f"[update] paper: {cur['version']}#{cur['build']} -> "
        f"{latest['version']}#{latest['build']}")
    if dry_run:
        return True
    if crafty is not None:
        log("[backup] taking world backup before Paper change")
        crafty.action(cfg["server_id"], "backup_server")
    jar = cfg["paper_canonical_jar"]
    dest = os.path.join(cfg["server_dir"], jar)
    http_download(latest["url"], dest, expected_sha256=latest.get("sha256"))
    if crafty is not None:
        crafty.patch_server(cfg["server_id"], {
            "executable": jar,
            "execution_command": f"java {cfg['jvm_args']} -jar {jar} nogui",
            "executable_update_url": latest["url"],
        })
    state["paper"] = {"version": latest["version"], "build": latest["build"]}
    save_state(os.path.join(cfg["autoupdate_dir"], "state.json"), state)
    log(f"[ok] paper: now {latest['version']}#{latest['build']}")
    return True
```

> **Note on `expected_sha256`:** the test monkeypatches `http_download`, so the real sha check
> isn't exercised here; it is exercised live in Task 12.

- [ ] **Step 4: Run to verify pass**

Run: `cd automation && python3 -m pytest tests/test_update_ops.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add automation/mc-autoupdate.py automation/tests/test_update_ops.py
git commit -m "mc-autoupdate: update_paper + state tracking"
```

---

## Task 9: main() — config, logging, dry-run, bootstrap, exit code

**Files:**
- Modify: `automation/mc-autoupdate.py`

- [ ] **Step 1: Implement main()** (append)

```python
def make_logger(log_dir: str, keep: int):
    os.makedirs(log_dir, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logf = os.path.join(log_dir, f"update-{day}.log")
    fh = open(logf, "a")

    def log(msg: str):
        line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
        print(line, flush=True)
        fh.write(line + "\n"); fh.flush()
    # prune old logs
    logs = sorted(_glob.glob(os.path.join(log_dir, "update-*.log")))
    for old in logs[:-keep] if keep > 0 else []:
        try:
            os.remove(old)
        except OSError:
            pass
    return log


def bootstrap_paper_state(cfg: dict, crafty, state: dict, log) -> None:
    """First run: derive current Paper MC version from the server's executable."""
    if "paper" in state:
        return
    try:
        srv = crafty.get_server(cfg["server_id"])
        exe = srv.get("executable", "")
        m = re.search(r"paper-(\d+\.\d+(?:\.\d+)?)", exe)
        ver = m.group(1) if m else "0"
    except Exception:
        ver = "0"
    state["paper"] = {"version": ver, "build": 0}  # build 0 forces a refresh to latest
    log(f"[init] bootstrapped paper state: {ver}#0")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="/crafty/import/autoupdate/config.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    with open(args.config) as f:
        cfg = json.load(f)
    log = make_logger(os.path.join(cfg["autoupdate_dir"], "logs"), cfg.get("keep_logs", 30))
    log(f"=== mc-autoupdate start (dry_run={args.dry_run}) ===")

    crafty = CraftyClient(cfg["crafty_base"], cfg["crafty_jwt"])
    state = load_state(os.path.join(cfg["autoupdate_dir"], "state.json"))
    now_epoch = int(time.time())
    errors = 0
    changed = False

    try:
        if cfg.get("update_plugins", True):
            changed |= update_plugins(cfg, log, args.dry_run)
    except Exception as e:
        errors += 1; log(f"[error] plugins: {e}")

    try:
        if cfg.get("update_paper", True):
            bootstrap_paper_state(cfg, crafty, state, log)
            changed |= update_paper(cfg, crafty, state, log, args.dry_run, now_epoch)
    except Exception as e:
        errors += 1; log(f"[error] paper: {e}")

    if cfg.get("restart", True) and not args.dry_run:
        ok = crafty.action(cfg["server_id"], "restart_server")
        log(f"[restart] restart_server -> {'ok' if ok else 'FAILED'}")
        if not ok:
            ok = crafty.action(cfg["server_id"], "restart_server")
            log(f"[restart] retry -> {'ok' if ok else 'FAILED'}")
        errors += 0 if ok else 1
    log(f"=== mc-autoupdate done (changed={changed}, errors={errors}) ===")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Full test suite green + lints**

Run: `cd automation && python3 -m pytest -q && python3 -m py_compile mc-autoupdate.py`
Expected: all tests PASS, compile OK.

- [ ] **Step 3: Local dry-run smoke against a fake config** (no network)

Run:
```bash
cd automation && cat > /tmp/cfg.json <<'EOF'
{"crafty_base":"https://localhost:8443","crafty_jwt":"x","server_id":"SID",
 "server_dir":"/tmp","plugins_dir":"/tmp/none","autoupdate_dir":"/tmp/au",
 "jvm_args":"-Xms1G","paper_canonical_jar":"paper.jar","mc_version_min_age_days":0,
 "keep_logs":5,"update_plugins":false,"update_paper":false,"restart":false}
EOF
mkdir -p /tmp/au && python3 mc-autoupdate.py --config /tmp/cfg.json --dry-run; echo "exit=$?"
```
Expected: prints start/done lines, `exit=0`, writes `/tmp/au/logs/update-*.log`.

- [ ] **Step 4: Commit**

```bash
git add automation/mc-autoupdate.py
git commit -m "mc-autoupdate: main() with config/logging/dry-run/bootstrap"
```

---

## Task 10: Orchestrator script (nightly-maintenance.sh)

**Files:**
- Create: `automation/nightly-maintenance.sh`

This is the body that becomes the Dokploy schedule's `script`. It runs inside the Dokploy container (has `docker`, `curl`).

- [ ] **Step 1: Write the script**

`automation/nightly-maintenance.sh`:
```bash
#!/bin/bash
# Dokploy dokploy-server schedule body. Runs inside the Dokploy container.
# 1) plugins+paper+restart via the in-Crafty python updater
# 2) pull crafty/playit images, redeploy only when the digest changed
# 3) ensure playit is running
set -uo pipefail
ts() { date -u +%FT%TZ; }
echo "=== mc-nightly-maintenance start: $(ts) ==="

echo "--- step 1: in-Crafty updater ---"
if docker exec crafty_container python3 /crafty/import/autoupdate/mc-autoupdate.py; then
  echo "[ok] mc-autoupdate completed"
else
  echo "[warn] mc-autoupdate exited non-zero (see /crafty/import/autoupdate/logs)"
fi

update_image() {  # $1=image  $2=webhookToken  $3=label
  local img="$1" tok="$2" label="$3" old new
  old=$(docker image inspect -f '{{.Id}}' "$img" 2>/dev/null || echo none)
  if ! docker pull "$img" >/dev/null 2>&1; then echo "[warn] pull failed: $img"; return; fi
  new=$(docker image inspect -f '{{.Id}}' "$img" 2>/dev/null || echo none)
  if [ "$old" != "$new" ]; then
    echo "[update] $label image changed ($old -> $new); redeploying"
    if curl -fsS -X POST "http://localhost:3000/api/deploy/compose/$tok" >/dev/null; then
      echo "[ok] $label redeployed"
    else
      echo "[warn] $label redeploy webhook failed"
    fi
  else
    echo "[ok] $label image already current"
  fi
}

echo "--- step 2: image updates ---"
update_image "registry.gitlab.com/crafty-controller/crafty-4:latest" "P4G6U5tnpT1UbETaPDfcx" "crafty"
update_image "ghcr.io/playit-cloud/playit-agent:1.0" "FohNmoNN_pzIgkfljoAJo" "playit"

echo "--- step 3: playit liveness ---"
if docker ps --format '{{.Names}}' | grep -qi playit; then
  echo "[ok] playit container running"
else
  echo "[recover] playit not running; redeploying"
  curl -fsS -X POST "http://localhost:3000/api/deploy/compose/FohNmoNN_pzIgkfljoAJo" >/dev/null \
    && echo "[ok] playit redeploy triggered" || echo "[warn] playit redeploy failed"
fi

echo "=== mc-nightly-maintenance done: $(ts) ==="
```

- [ ] **Step 2: Lint the script**

Run: `bash -n automation/nightly-maintenance.sh && echo "syntax ok"`
Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add automation/nightly-maintenance.sh
git commit -m "automation: nightly-maintenance orchestrator (images + liveness)"
```

---

## Task 11: Installer (deploy.sh)

**Files:**
- Create: `automation/deploy.sh`

Runs from the workstation. Uses SSH for `docker exec` (into Crafty) and for `curl` to the Dokploy API on the remote's `localhost:3000`. Secrets come from env: `DOKPLOY_KEY`, `CRAFTY_JWT`. SSH command from env `SSHC` (defaults to the known target).

- [ ] **Step 1: Write the installer**

`automation/deploy.sh`:
```bash
#!/bin/bash
# Idempotent installer for the green-axolotl update automation.
# Requires env: DOKPLOY_KEY, CRAFTY_JWT.  Optional: SSHC (ssh command).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SSHC="${SSHC:-ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210}"
ORG="eFbswAqh7vlP_F7SfdS8D"
PLAYIT_COMPOSE="Up4B06-EaIzJuYH3mxgTj"
PLAYIT_WEBHOOK="FohNmoNN_pzIgkfljoAJo"
SERVER_ID="394a3479-b8e9-4f4f-aa36-49c87eafe548"
: "${DOKPLOY_KEY:?set DOKPLOY_KEY}"; : "${CRAFTY_JWT:?set CRAFTY_JWT}"

api() {  # api <proc> <json-body>   (POST mutation through remote localhost)
  $SSHC -- "curl -fsS -X POST 'http://localhost:3000/api/$1' \
    -H 'x-api-key: $DOKPLOY_KEY' -H 'Content-Type: application/json' -d '$2'"
}
apiget() { $SSHC -- "curl -fsS 'http://localhost:3000/api/$1' -H 'x-api-key: $DOKPLOY_KEY'"; }

echo "==> 1. install updater + config into crafty_container volume"
$SSHC -- "docker exec -i crafty_container sh -c 'mkdir -p /crafty/import/autoupdate/logs'"
$SSHC -- "docker exec -i crafty_container sh -c 'cat > /crafty/import/autoupdate/mc-autoupdate.py'" < "$HERE/mc-autoupdate.py"
# render config from template with secrets/values
python3 - "$HERE/config.example.json" "$CRAFTY_JWT" <<'PY' > /tmp/config.rendered.json
import json,sys
cfg=json.load(open(sys.argv[1])); cfg["crafty_jwt"]=sys.argv[2]; print(json.dumps(cfg,indent=2))
PY
$SSHC -- "docker exec -i crafty_container sh -c 'cat > /crafty/import/autoupdate/config.json && chmod 600 /crafty/import/autoupdate/config.json'" < /tmp/config.rendered.json
rm -f /tmp/config.rendered.json
echo "    installed."

echo "==> 2. fix playit compose (image :1.0 + restart: unless-stopped)"
NEWCOMPOSE=$($SSHC -- "curl -fsS 'http://localhost:3000/api/compose.one?composeId=$PLAYIT_COMPOSE' -H 'x-api-key: $DOKPLOY_KEY'" \
  | python3 -c '
import json,sys
c=json.load(sys.stdin); f=c["composeFile"]
f=f.replace("playit-agent:0.17","playit-agent:1.0")
if "restart:" not in f:
    f=f.replace("network_mode: host","network_mode: host\n    restart: unless-stopped")
print(json.dumps(f))')
api "compose.update" "{\"composeId\":\"$PLAYIT_COMPOSE\",\"composeFile\":$NEWCOMPOSE}" >/dev/null
echo "    redeploying playit..."
$SSHC -- "curl -fsS -X POST 'http://localhost:3000/api/deploy/compose/$PLAYIT_WEBHOOK'" >/dev/null
echo "    playit updated + redeployed."

echo "==> 3. create/update nightly schedule (3:30 UTC)"
SCRIPT_JSON=$(python3 -c 'import json,sys; print(json.dumps(open(sys.argv[1]).read()))' "$HERE/nightly-maintenance.sh")
EXISTING=$(apiget "schedule.list?id=$ORG&scheduleType=dokploy-server" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next((s["scheduleId"] for s in d if s["name"]=="mc-nightly-maintenance"),""))')
BODY="{\"name\":\"mc-nightly-maintenance\",\"cronExpression\":\"30 3 * * *\",\"scheduleType\":\"dokploy-server\",\"shellType\":\"bash\",\"enabled\":true,\"organizationId\":\"$ORG\",\"script\":$SCRIPT_JSON}"
if [ -n "$EXISTING" ]; then
  echo "    updating existing schedule $EXISTING"
  api "schedule.update" "{\"scheduleId\":\"$EXISTING\",$(echo "$BODY" | sed 's/^{//')" >/dev/null
else
  echo "    creating schedule"
  api "schedule.create" "$BODY" >/dev/null
fi
echo "==> done. Run a manual dry-run with:"
echo "    $SSHC -- \"docker exec crafty_container python3 /crafty/import/autoupdate/mc-autoupdate.py --dry-run\""
```

- [ ] **Step 2: Lint**

Run: `bash -n automation/deploy.sh && echo "syntax ok"`
Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add automation/deploy.sh
git commit -m "automation: idempotent installer (deploy.sh)"
```

---

## Task 12: Deploy to the live host and verify

> This task performs real changes. Have `DOKPLOY_KEY` and `CRAFTY_JWT` in the environment.

- [ ] **Step 1: Install + fix playit + create schedule**

Run: `cd automation && DOKPLOY_KEY=… CRAFTY_JWT=… ./deploy.sh`
Expected: prints steps 1–3 with "installed.", "playit updated + redeployed.", "creating/updating schedule".

- [ ] **Step 2: Verify playit is up and on :1.0**

Run:
```bash
SSHC="ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210"
$SSHC -- 'docker ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}" | grep -i playit'
$SSHC -- 'docker inspect -f "{{.HostConfig.RestartPolicy.Name}}" $(docker ps -q --filter name=playit | head -1)'
```
Expected: a running `…playit…` container on `…/playit-agent:1.0`, restart policy `unless-stopped`.

- [ ] **Step 3: Dry-run the updater against live APIs (no changes applied)**

Run: `$SSHC -- "docker exec crafty_container python3 /crafty/import/autoupdate/mc-autoupdate.py --dry-run"`
Expected: `[update] geyser: … -> 1165`, `[update] ViaVersion: 5.7.1 -> 5.9.1`, a Paper line, `done (changed=True …)`, exit 0. No jars changed yet.

- [ ] **Step 4: Real run (applies updates + restarts once)**

Run: `$SSHC -- "docker exec crafty_container python3 /crafty/import/autoupdate/mc-autoupdate.py"`
Then verify the new builds landed:
```bash
$SSHC -- 'docker exec crafty_container python3 - <<PY
import zipfile,re,glob
p="/crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/plugins"
print("geyser", re.search(r"git.build.number=(\d+)", zipfile.ZipFile(p+"/Geyser-Spigot.jar").read("git.properties").decode()).group(1))
print("via", glob.glob(p+"/ViaVersion-*.jar"))
PY'
```
Expected: Geyser build = latest (e.g. 1165), `ViaVersion-5.9.1.jar` present, old `ViaVersion-5.7.1.jar` gone. Confirm the server came back online (Crafty stats `running:true`).

- [ ] **Step 5: Verify schedule exists**

Run: `$SSHC -- "curl -fsS 'http://localhost:3000/api/schedule.list?id=eFbswAqh7vlP_F7SfdS8D&scheduleType=dokploy-server' -H 'x-api-key: \$DOKPLOY_KEY'"` (key inline)
Expected: JSON array contains `"name":"mc-nightly-maintenance"`, `"cronExpression":"30 3 * * *"`, `"enabled":true`.

- [ ] **Step 6: Verify the orchestrator end-to-end via runManually**

Run: get the scheduleId from step 5, then
`$SSHC -- "curl -fsS -X POST 'http://localhost:3000/api/schedule.runManually' -H 'x-api-key: \$DOKPLOY_KEY' -H 'Content-Type: application/json' -d '{\"scheduleId\":\"<id>\"}'"`
Then read the schedule's run log in the Dokploy UI (or `/etc/dokploy/...` logs). Expected: step 1/2/3 lines, images "already current", playit "running".

- [ ] **Step 7: Commit a deployment note**

```bash
git commit --allow-empty -m "chore: deployed update automation to live host (verified)"
```

---

## Tasks 13–18: Documentation

Each doc is prose written from the spec (`docs/superpowers/specs/2026-06-14-minecraft-update-automation-design.md`) and §2 of it. No placeholders — include the concrete values below.

### Task 13: `docs/01-architecture.md`
- [ ] Write covering: the homelab host (LAN 192.168.3.10, NAT, public egress, Tailscale 100.65.140.26), Dokploy v0.29.8 + Traefik + Let's Encrypt, the `crafty.tail.keeso.com`/`dokploy.tail.keeso.com` routes, a container inventory table (crafty_container, playit, plus the unrelated imggen/HA/postgres), the project/compose IDs, and a diagram of "Bedrock phone → playit tunnel → host:19132 → Geyser → Paper". Commit.

### Task 14: `docs/02-minecraft-server.md`
- [ ] Write covering: Crafty 4.x manages `mc-paper-1` as an in-container Java process; Paper 1.21.8, JVM `-Xms1000M -Xmx2000M`, Java 25; ports (25565 internal, 25500-25600 + 19132/udp published); the 5 active plugins with their roles; the orphaned `Essentials/`,`Updater/`,`old_plugins_backup/` and `spark` (Paper-bundled); key `server.properties` values (creative, online-mode true + Floodgate). Note the volume layout. Commit.

### Task 15: `docs/03-green-axolotl.md`
- [ ] Write covering: the `/greenaxolotl` MyCommand definition (give `axolotl_spawn_egg[...Variant:4]`, 300s cooldown) with the exact `commands.yml` snippet; the **Bedrock** `green-axolotl-pack-br.mcpack` (uuid `2d0e25e1-…`, "re-textures rare blue axolotl green"), how Geyser auto-serves packs from `plugins/Geyser-Spigot/packs/`; the difference vs the stale Java `pack.zip`; **how to update the pack** (drop a new `.mcpack` in the Geyser packs folder, bump the manifest version, restart). Commit.

### Task 16: `docs/04-bedrock-connectivity.md`
- [ ] Write covering: why Bedrock/Android can't connect after a Minecraft update (Geyser tracks the Bedrock protocol; stale build → "outdated client/server"); the roles of Geyser/Floodgate/ViaVersion/ViaBackwards; the always-latest download URLs; how the daily updater keeps Geyser current; the inherent hours-to-days lag after a Bedrock release; and that Java server version can lag because Geyser+Via bridge it. Commit.

### Task 17: `docs/05-updates-automation.md`  (the upgrade guide)
- [ ] Write covering: the whole automation — the 3:30 UTC `dokploy-server` schedule, `nightly-maintenance.sh` steps, `mc-autoupdate.py` logic per component (with the exact APIs/URLs), the `config.json` fields incl. `mc_version_min_age_days`, where logs live, how to read a run in Dokploy; **manual procedures** (force a run, run dry-run, change cadence, pin/raise the MC soak); **rollback** (restore a Crafty backup; repoint `executable`/`executable_update_url` to a prior Paper via `PATCH /servers/{id}`; restore a plugin jar from `old_plugins_backup/`); the playit `:1.0` + `restart: unless-stopped` fix and why; how to re-run `deploy.sh`. Commit.

### Task 18: `docs/06-runbook.md`
- [ ] Write covering quick procedures: restart server (Crafty UI/API), take/restore a backup, revive playit, rotate the Crafty JWT (update `config.json`) and Dokploy key, update Crafty/playit images manually, and a "players can't connect" triage tree (Bedrock vs Java; is playit up; is Geyser current; is the server running). Commit.

---

## Task 19: README + finish

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

Top-level overview: what this repo is (the green-axolotl Minecraft server's config, the canonical Bedrock pack, and the update automation + docs), a "I just want to…" quick-link table into `docs/`, and a one-paragraph architecture summary. Link the spec and plan.

- [ ] **Step 2: Full test suite + script lints green**

Run: `cd automation && python3 -m pytest -q && bash -n nightly-maintenance.sh && bash -n deploy.sh && echo OK`
Expected: all pass, `OK`.

- [ ] **Step 3: Commit + open PR**

```bash
git add README.md
git commit -m "docs: top-level README + index"
git push -u origin mc-update-automation
gh pr create --title "Minecraft server update automation + docs" --body "See docs/superpowers/specs and docs/."
```

---

## Self-Review (completed by plan author)

**Spec coverage:** §4.1 playit fix → Task 11/12; §4.2 schedule+orchestrator → Tasks 10–12; §4.3 updater (plugins+Paper+restart) → Tasks 2–9, 12; §4.4 secrets/config → Tasks 1, 11; §4.5 installer → Task 11; §5 docs → Tasks 13–19; §6 risks (backup-before-Paper, stable-only, pull-then-redeploy, 3:30 timing) → Tasks 8, 4, 10. All covered.

**Placeholder scan:** doc tasks (13–18) specify exact facts to include rather than "fill in details"; no TBD/TODO in code. OK.

**Type consistency:** function names used consistently (`geyser_latest`, `update_one_geyser`, `update_one_via`, `find_latest_paper`, `select_stable_build`, `CraftyClient.action/patch_server/get_server`, `update_plugins`, `update_paper`, `load_state/save_state`); config keys consistent across `config.example.json`, `update_paper`, `main`. OK.

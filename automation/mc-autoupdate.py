#!/usr/bin/env python3
"""Nightly updater for the green-axolotl Minecraft server.

Runs INSIDE crafty_container (python3 stdlib only — no curl/wget/unzip).
Updates Geyser/Floodgate/ViaVersion/ViaBackwards plugins and Paper, then
restarts the server via the Crafty API. See docs/05-updates-automation.md.
"""
from __future__ import annotations

import argparse
import glob as _glob
import hashlib
import json
import os
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone


# --------------------------------------------------------------------------- #
# Jar inspection — read installed plugin versions
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Version comparison
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Paper stable-build selection (pure)
# --------------------------------------------------------------------------- #
def _iso_to_epoch(s: str) -> int:
    # "2026-06-01T00:00:00.000Z" -> epoch seconds
    s = s.replace("Z", "").split(".")[0]
    dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def select_stable_build(builds: list, min_age_days: int, now_epoch: int) -> dict | None:
    """Pick the newest STABLE build at least min_age_days old. Returns
    {build, url, sha256, name} or None. (Fill v3's build number is its `id`.)"""
    cutoff = now_epoch - min_age_days * 86400
    best = None
    for b in builds:
        if str(b.get("channel", "")).upper() not in ("STABLE", "RECOMMENDED"):
            continue
        if _iso_to_epoch(b["time"]) > cutoff:
            continue
        dl = b["downloads"]["server:default"]
        cand = {"build": b["id"], "url": dl["url"],
                "sha256": dl.get("checksums", {}).get("sha256"), "name": dl["name"]}
        if best is None or cand["build"] > best["build"]:
            best = cand
    return best


# --------------------------------------------------------------------------- #
# HTTP layer + upstream clients
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Crafty API client
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Update operations
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def make_logger(log_dir: str, keep: int):
    os.makedirs(log_dir, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logf = os.path.join(log_dir, f"update-{day}.log")
    fh = open(logf, "a")

    def log(msg: str):
        line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
        print(line, flush=True)
        fh.write(line + "\n")
        fh.flush()

    logs = sorted(_glob.glob(os.path.join(log_dir, "update-*.log")))
    for old in (logs[:-keep] if keep > 0 else []):
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
        errors += 1
        log(f"[error] plugins: {e}")

    try:
        if cfg.get("update_paper", True):
            bootstrap_paper_state(cfg, crafty, state, log)
            changed |= update_paper(cfg, crafty, state, log, args.dry_run, now_epoch)
    except Exception as e:
        errors += 1
        log(f"[error] paper: {e}")

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

import calendar
import importlib.util
import pathlib
import time

spec = importlib.util.spec_from_file_location(
    "mcupd", pathlib.Path(__file__).resolve().parents[1] / "mc-autoupdate.py")
mcupd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcupd)

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
    assert b["build"] == 60 and b["url"] == "u60" and b["sha256"] == "h60"


def test_min_age_excludes_too_recent():
    # require 30 days old: build 60 (13 days) excluded, falls back to 58 (44 days)
    b = mcupd.select_stable_build(BUILDS, min_age_days=30, now_epoch=NOW)
    assert b["build"] == 58


def test_no_stable_returns_none():
    only_alpha = [BUILDS[2]]
    assert mcupd.select_stable_build(only_alpha, min_age_days=0, now_epoch=NOW) is None

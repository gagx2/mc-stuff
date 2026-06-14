import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "mcupd", pathlib.Path(__file__).resolve().parents[1] / "mc-autoupdate.py")
mcupd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcupd)


def test_parse_version_tuple():
    assert mcupd.parse_version_tuple("5.9.1") == (5, 9, 1)
    assert mcupd.parse_version_tuple("1.21.8") == (1, 21, 8)
    assert mcupd.parse_version_tuple("26.1.2") == (26, 1, 2)
    assert mcupd.parse_version_tuple("5.9.1-SNAPSHOT") == (5, 9, 1)


def test_semver_newer():
    assert mcupd.semver_newer("5.7.1", "5.9.1") is True
    assert mcupd.semver_newer("5.9.1", "5.9.1") is False
    assert mcupd.semver_newer("5.9.1", "5.7.1") is False
    assert mcupd.semver_newer(None, "5.9.1") is True


def test_compare_mc_versions():
    assert mcupd.compare_mc_versions("1.21.8", "1.21.11") < 0
    assert mcupd.compare_mc_versions("1.21.11", "26.1.2") < 0
    assert mcupd.compare_mc_versions("26.1.2", "26.1.2") == 0
    assert mcupd.compare_mc_versions("26.2", "26.1.2") > 0

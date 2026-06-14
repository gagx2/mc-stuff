import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "mcupd", pathlib.Path(__file__).resolve().parents[1] / "mc-autoupdate.py")
mcupd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcupd)


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


def test_read_installed_build_from_git_properties(jar_factory):
    jar = jar_factory("Geyser-Spigot.jar", {"git.properties": "git.build.number=1165\n"})
    assert mcupd.read_installed_build(jar) == 1165


def test_read_installed_build_floodgate_from_plugin_yml(jar_factory):
    # Floodgate has no git.properties; build is the b<NN> in its version string.
    jar = jar_factory("floodgate-spigot.jar",
                      {"plugin.yml": "name: floodgate\nversion: 2.2.5-SNAPSHOT (b132-5a72b6a)\n"})
    assert mcupd.read_installed_build(jar) == 132

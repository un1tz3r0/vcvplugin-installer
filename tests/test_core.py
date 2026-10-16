import zipfile

import pytest
from conftest import ELF_X64, zstd_available

from vcvplugin import core
from vcvplugin.core import Action, Level, PackageError


@pytest.mark.parametrize("older, newer", [
    ("2.0.0", "2.0.1"),
    ("2.0.9", "2.0.10"),
    ("2.1", "2.1.1"),
    ("2.0.0-beta", "2.0.0"),
    ("2.0.0-alpha", "2.0.0-beta"),
])
def test_version_order(older, newer):
    assert core.version_key(older) < core.version_key(newer)


@pytest.mark.parametrize("a, b", [("2.1", "2.1.0"), ("2.0.0+build5", "2.0.0")])
def test_version_equal(a, b):
    assert core.version_key(a) == core.version_key(b)


@pytest.mark.parametrize("fmt", [
    "zip", "tar", "tar.gz",
    pytest.param("tar.zst", marks=pytest.mark.skipif(not zstd_available(), reason="no zstd decoder")),
])
def test_package_formats(make_package, fmt):
    with core.Package(make_package(fmt=fmt, files={"res/panel.svg": b"<svg/>"})) as pkg:
        assert (pkg.slug, pkg.version, pkg.root) == ("TestPlugin", "2.0.0", "TestPlugin")
        assert set(pkg.files) == {"plugin.json", "plugin.so", "res/panel.svg"}
        assert pkg.read("res/panel.svg") == b"<svg/>"
        assert pkg.platform_problem() is None


def test_package_without_top_folder(make_package):
    with core.Package(make_package(root="")) as pkg:
        assert pkg.root == ""
        assert "plugin.json" in pkg.files


@pytest.mark.parametrize("kwargs, message", [
    ({"files": {"plugin.json": None}}, "no plugin.json"),
    ({"files": {"../evil": b""}}, "unsafe path"),
    ({"manifest": {"slug": "bad slug!", "version": "2.0.0"}}, "invalid or missing slug"),
    ({"manifest": {"slug": "TestPlugin"}}, "invalid or missing version"),
    ({"files": {"plugin.json": b"{not json"}}, "not valid JSON"),
])
def test_package_rejected(make_package, kwargs, message):
    with pytest.raises(PackageError, match=message):
        core.Package(make_package(**kwargs))


def test_package_rejects_symlink(tmp_path):
    path = tmp_path / "link.vcvplugin"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("TestPlugin/plugin.json", '{"slug": "TestPlugin", "version": "2.0.0"}')
        link = zipfile.ZipInfo("TestPlugin/plugin.so")
        link.external_attr = 0o120777 << 16
        z.writestr(link, "/etc/passwd")
    with pytest.raises(PackageError, match="link or device"):
        core.Package(path)


def test_not_an_archive(tmp_path):
    path = tmp_path / "junk.vcvplugin"
    path.write_bytes(b"hello")
    with pytest.raises(PackageError, match="not a zip, tar or tar.zst archive"):
        core.Package(path)


@pytest.mark.parametrize("files, problem", [
    ({"plugin.dll": b""}, "another operating system"),
    ({"plugin.so": None}, "no plugin.so"),
    ({"plugin.so": b"not an elf file at all"}, "not an ELF"),
    ({"plugin.so": ELF_X64[:18] + (0xB7).to_bytes(2, "little")}, "another CPU"),
])
def test_platform_problem(make_package, files, problem):
    with core.Package(make_package(files=files)) as pkg:
        assert problem in pkg.platform_problem()


def levels(plan) -> list[Level]:
    return [i.level for i in plan.issues]


def test_analyze_new_install(plugins_dir, make_package):
    plan = core.analyze(make_package())
    assert plan.action is Action.INSTALL
    assert not plan.blocked and not plan.needs_confirmation and plan.current is None


@pytest.mark.parametrize("installed, action, confirm", [
    ("1.9.0", Action.UPGRADE, False),
    ("2.0.0", Action.SAME, False),
    ("2.1.0", Action.DOWNGRADE, True),
])
def test_analyze_against_installed(plugins_dir, make_package, install_dir, installed, action, confirm):
    install_dir(version=installed)
    plan = core.analyze(make_package(version="2.0.0"))
    assert plan.action is action
    assert plan.needs_confirmation is confirm
    assert plan.current.version == installed


def test_analyze_same_version_different_files(plugins_dir, make_package, install_dir):
    install_dir(files={"plugin.so": ELF_X64 + b"old"})
    plan = core.analyze(make_package())
    assert plan.action is Action.SAME_DIFFERS
    assert plan.needs_confirmation
    assert "plugin.so" in plan.diff.changed


@pytest.mark.parametrize("kwargs, level, text", [
    ({"arch": "win-x64"}, Level.ERROR, "built for win-x64"),
    ({"filename": "TestPlugin-2.0.1-lin-x64.vcvplugin"}, Level.WARN, "file name says"),
    ({"filename": "whatever.vcvplugin"}, Level.INFO, "does not follow"),
    ({"version": "1.0.0"}, Level.WARN, "Rack 2 will refuse to load it"),
    ({"root": "build"}, Level.INFO, "will be installed into TestPlugin/"),
])
def test_analyze_issues(plugins_dir, make_package, kwargs, level, text):
    plan = core.analyze(make_package(**kwargs))
    assert any(i.level is level and text in i.text for i in plan.issues), plan.issues


def test_analyze_defer_needs_slug_folder(plugins_dir, make_package):
    plan = core.analyze(make_package(root="build"), defer=True)
    assert plan.blocked


def test_analyze_unreadable_never_raises(plugins_dir, tmp_path):
    plan = core.analyze(tmp_path / "missing-2.0.0-lin-x64.vcvplugin")
    assert plan.blocked


def test_install_extracts(plugins_dir, make_package):
    plan = core.analyze(make_package(files={"res/panel.svg": b"<svg/>"}))
    dest = core.install(plan)
    assert dest == plugins_dir / "TestPlugin"
    assert (dest / "res" / "panel.svg").read_bytes() == b"<svg/>"
    assert sorted(p.name for p in plugins_dir.iterdir()) == ["TestPlugin"]  # no staging leftovers


def test_install_replaces_old_files(plugins_dir, make_package, install_dir):
    install_dir(version="1.9.0", files={"obsolete.txt": b"x"})
    core.install(core.analyze(make_package()))
    assert not (plugins_dir / "TestPlugin" / "obsolete.txt").exists()
    assert core.find_installed("TestPlugin")[0].version == "2.0.0"


def test_install_removes_pending_packages(plugins_dir, make_package):
    pending = make_package(version="1.9.0", dest=plugins_dir)
    plan = core.analyze(make_package())
    assert [p.path for p in plan.pending] == [pending]
    core.install(plan)
    assert not pending.exists()


def test_install_package_from_plugins_dir_removes_it(plugins_dir, make_package):
    pkg = make_package(dest=plugins_dir)
    core.install(core.analyze(pkg))
    assert not pkg.exists()
    assert (plugins_dir / "TestPlugin" / "plugin.so").exists()


def test_install_defer_copies_package(plugins_dir, make_package):
    pkg = make_package(filename="download.vcvplugin")
    dest = core.install(core.analyze(pkg, defer=True), defer=True)
    assert dest == plugins_dir / "TestPlugin-2.0.0-lin-x64.vcvplugin"
    assert dest.read_bytes() == pkg.read_bytes()


def test_install_blocked_raises(plugins_dir, make_package):
    plan = core.analyze(make_package(arch="mac-x64"))
    with pytest.raises(PackageError):
        core.install(plan)


def test_install_reports_progress(plugins_dir, make_package):
    pkg, calls = make_package(), []
    core.install(core.analyze(pkg), progress=lambda name, done, total: calls.append((done, total)))
    with core.Package(pkg) as p:
        assert calls[-1] == (sum(e.size for e in p.files.values()),) * 2

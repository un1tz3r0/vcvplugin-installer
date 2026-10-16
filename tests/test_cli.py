import re
from pathlib import Path

import pytest

from vcvplugin import __version__, cli


def test_version(capsys):
    with pytest.raises(SystemExit) as exit:
        cli.main(["--version"])
    assert exit.value.code == 0
    assert capsys.readouterr().out == f"vcvplugin-install {__version__}\n"


def test_install(plugins_dir, make_package, capsys):
    assert cli.main([str(make_package())]) == 0
    assert (plugins_dir / "TestPlugin" / "plugin.so").exists()
    assert "installed 2.0.0" in capsys.readouterr().out


def test_dry_run_installs_nothing(plugins_dir, make_package):
    assert cli.main(["--dry-run", str(make_package())]) == 0
    assert not plugins_dir.exists() or not any(plugins_dir.iterdir())


def test_downgrade_needs_yes(plugins_dir, make_package, install_dir):
    install_dir(version="2.1.0")
    pkg = str(make_package(version="2.0.0"))
    assert cli.main([pkg]) == 2
    assert cli.main(["--yes", pkg]) == 0
    assert '"version": "2.0.0"' in (plugins_dir / "TestPlugin" / "plugin.json").read_text()


def test_exit_status_combines(plugins_dir, make_package, install_dir):
    install_dir(slug="Older", version="2.1.0")
    rejected = make_package(arch="mac-arm64")
    skipped = make_package(slug="Older", version="2.0.0")
    assert cli.main([str(rejected)]) == 1
    assert cli.main([str(rejected), str(skipped)]) == 3


def test_man_page_lists_every_option():
    man = (Path(__file__).parents[1] / "data" / "vcvplugin-install.1").read_text().replace("\\-", "-")
    section = man[man.index(".SH OPTIONS"):man.index(".SH EXIT STATUS")]
    documented = set(re.findall(r"(?<![\w-])--?[a-z][\w-]*", section))
    assert {o for a in cli.parser()._actions for o in a.option_strings} <= documented

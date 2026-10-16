# Contributing

Bug reports and pull requests are welcome at <https://github.com/un1tz3r0/vcvplugin-installer>.
To report a security problem, see [SECURITY.md](SECURITY.md) instead of opening an issue.

## Setup

You need the [requirements](README.md#requirements) and [uv](https://docs.astral.sh/uv/) (or pip). Run the app from
a checkout without installing it:

```sh
python3 -m vcvplugin --help   # CLI
python3 -m vcvplugin.gui      # GUI
```

## Checks

CI runs all of these on every pull request:

```sh
uv run pytest                                  # tests (or: python3 -m pytest)
uv run ruff check .                            # lint; `ruff check --fix .` fixes most findings
meson setup _build && meson test -C _build     # validates the desktop entries and AppStream metainfo
uv build                                       # sdist and wheel
xvfb-run -a python3 build-aux/screenshots.py   # renders data/screenshots/ (drop xvfb-run to watch it)
```

`core` has no GUI dependencies; put logic there with tests, and keep `cli.py` and `gui.py` thin. When adding a
module to `vcvplugin/`, also list it in `meson.build`.

The screenshots job uploads its renders as a build artifact. When your change affects the UI, download them from
the CI run and commit them to `data/screenshots/`.

## Every pull request bumps the version

1. Bump `vcvplugin/VERSION`: the patch number for fixes and housekeeping, the minor number for new features.
2. Add a `<release>` for it, with notes, at the top of `<releases>` in
   `data/io.github.un1tz3r0.VcvPluginInstaller.metainfo.xml`. `build-aux/release-notes.py` prints them as
   Markdown and fails if they are missing.

CI fails a pull request whose version is already tagged or has no release notes. When it is merged, the Release
workflow tags the commit `vX.Y.Z` and publishes a GitHub release with those notes, the sdist and the wheel.

## License

By contributing, you agree that your contributions are licensed under the GPL-3.0-or-later, like the rest of the
project.

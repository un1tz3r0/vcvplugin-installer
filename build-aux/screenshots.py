#!/usr/bin/env python3
"""Render the GUI screenshots from a scripted run with made-up plugins in a throwaway home directory.

    build-aux/screenshots.py [OUTPUT_DIR]     (default: data/screenshots)

Needs a display; in CI it runs under xvfb-run.
"""
import json
import os
import shutil
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else SRC / "data" / "screenshots").resolve()
HOME = Path(tempfile.mkdtemp(prefix="vcvplugin-screenshots-"))
# Stock Adwaita look: ignore the desktop's settings (color scheme, accent, window buttons).
os.environ.update(HOME=str(HOME), GSETTINGS_BACKEND="memory", ADW_DISABLE_PORTAL="1", GDK_DEBUG="no-portals",
                  **{var: str(HOME / var.lower()) for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")})
os.environ.pop("RACK_USER_DIR", None)
sys.path.insert(0, str(SRC))

import gi  # noqa: E402

gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, Gio, GLib, Graphene, Gtk  # noqa: E402

from vcvplugin import core, gui  # noqa: E402

ELF = b"\x7fELF" + bytes(14) + (0x3E).to_bytes(2, "little") + bytes(44)
TIMEOUT = 60


def package(slug: str, name: str, version: str, arch: str = "lin-x64") -> Path:
    path = HOME / "Downloads" / f"{slug}-{version}-{arch}.vcvplugin"
    path.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{slug}/plugin.json", json.dumps({"slug": slug, "name": name, "version": version}))
        z.writestr(f"{slug}/plugin.so", ELF)
        z.writestr(f"{slug}/res/panel.svg", "<svg/>")
    return path


def installed(slug: str, version: str, so: bytes = ELF):
    d = core.PLUGINS_DIR / slug
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(json.dumps({"slug": slug, "version": version}))
    (d / "plugin.so").write_bytes(so)


def shoot(win: Gtk.Window, name: str):
    w, h = win.get_width(), win.get_height()
    snapshot = Gtk.Snapshot()
    Gtk.WidgetPaintable(widget=win).snapshot(snapshot, w, h)
    texture = win.get_renderer().render_texture(snapshot.to_node(), Graphene.Rect().init(0, 0, w, h))
    texture.save_to_png(str(OUT / f"{name}.png"))
    print(f"wrote {OUT / name}.png")


def scenes(app: gui.App):
    """Each yield waits until the condition holds and the window has settled."""
    installed("AcmeOscillators", "2.0.3")
    installed("GranularToys", "2.3.1")
    installed("HexaSequencer", "2.0.1", so=ELF + b"old build")
    packages = [
        package("AcmeOscillators", "Acme Oscillators", "2.1.0"),
        package("DelayLab", "Delay Lab", "2.0.0"),
        package("GranularToys", "Granular Toys", "2.2.0"),
        package("HexaSequencer", "Hexa Sequencer", "2.0.1"),
        package("MacFilters", "Mac Filters", "2.0.0", arch="mac-arm64"),
    ]

    win = gui.Wizard(app, [])
    win.present()
    yield lambda: win.get_mapped()
    shoot(win, "choose")

    plans = [core.analyze(p) for p in packages]
    win.review(plans)
    yield lambda: win.heading.get_subtitle() == "Review"
    shoot(win, "review")

    win.confirm([plans[2]])
    yield lambda: win.heading.get_subtitle() == "Confirm"
    shoot(win, "confirm")

    win.install(plans[:2])
    yield lambda: win.heading.get_subtitle() == "Done"
    shoot(win, "done")

    app.about()
    yield None
    shoot(win, "about")


class ScreenshotApp(gui.App):
    def __init__(self):
        super().__init__()
        self.set_flags(self.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        self.status = 1

    def do_activate(self):
        settings = Gtk.Settings.get_default()
        settings.props.gtk_enable_animations = False
        settings.props.gtk_font_name = "Cantarell 11"
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(SRC / "data"))
        self.hold()
        GLib.timeout_add_seconds(TIMEOUT, self.fail, f"timed out after {TIMEOUT}s")
        self.resume(scenes(self))

    def fail(self, message: str):
        print(f"error: {message}", file=sys.stderr)
        self.quit()

    def resume(self, steps):
        try:
            condition = next(steps) or (lambda: True)
        except StopIteration:
            self.status = 0
            return self.quit()
        except Exception:
            return self.fail(traceback.format_exc())

        def poll():
            if condition():
                GLib.timeout_add(500, lambda: self.resume(steps) and False)
                return False
            return True

        GLib.timeout_add(100, poll)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    core.rack_running = lambda: False
    core.find_rack = lambda: HOME / "Rack2Free" / "Rack"
    try:
        app = ScreenshotApp()
        app.run([])
        return app.status
    finally:
        shutil.rmtree(HOME)


if __name__ == "__main__":
    sys.exit(main())

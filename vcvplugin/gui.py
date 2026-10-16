"""GTK 4 / libadwaita wizard for installing VCV Rack 2 plugin packages."""
import subprocess
import sys
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import core  # noqa: E402
from .core import Action, Level  # noqa: E402

APP_ID = "io.github.un1tz3r0.VcvPluginInstaller"
OK_ICON = "object-select-symbolic"
LEVEL_ICON = {Level.INFO: "dialog-information-symbolic", Level.WARN: "dialog-warning-symbolic",
              Level.ERROR: "dialog-error-symbolic"}
ACTION_ICON = {Action.INSTALL: "list-add-symbolic", Action.UPGRADE: "go-up-symbolic", Action.DOWNGRADE: "go-down-symbolic",
               Action.SAME: OK_ICON, Action.SAME_DIFFERS: "dialog-warning-symbolic"}


def plan_icon(plan: core.Plan) -> str:
    if plan.blocked:
        return LEVEL_ICON[Level.ERROR]
    return LEVEL_ICON[Level.WARN] if plan.needs_confirmation else ACTION_ICON[plan.action]


def row(title: str, subtitle: str = "", icon: str | None = None) -> Adw.ActionRow:
    r = Adw.ActionRow(title=title, subtitle=subtitle, use_markup=False)
    if icon:
        r.add_prefix(Gtk.Image(icon_name=icon))
    return r


def detail_rows(plan: core.Plan):
    yield from (row(i.text, icon=LEVEL_ICON[i.level]) for i in plan.issues)
    for label, names in plan.diff.groups() if plan.diff else ():
        yield row(f"{len(names)} file{'s' * (len(names) != 1)} {label}",
                  ", ".join(names[:5]) + (" …" if len(names) > 5 else ""), "document-edit-symbolic")


def group(rows, **props) -> Adw.PreferencesGroup:
    g = Adw.PreferencesGroup(**props)
    for r in rows:
        g.add(r)
    return g


def status(icon: str | None, title: str, description: str = "", child: Gtk.Widget | None = None) -> Adw.StatusPage:
    return Adw.StatusPage(icon_name=icon, title=title, description=GLib.markup_escape_text(description), child=child)


def page(content: Gtk.Widget, *actions) -> tuple[Gtk.Box, list[Gtk.Button]]:
    """A wizard page: content above a centered row of pill buttons, given as (label, style class, callback)."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    bar = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, margin_top=12, margin_bottom=24)
    buttons = []

    def clicked(_button, callback):
        stack = box.get_parent()
        if stack is None or stack.get_visible_child() is box:  # ignore clicks on a page we're leaving
            callback()

    for label, style, callback in actions:
        b = Gtk.Button(label=label, css_classes=["pill", *([style] if style else [])])
        b.connect("clicked", clicked, callback)
        bar.append(b)
        buttons.append(b)
    content.set_vexpand(True)
    box.append(content)
    box.append(bar)
    return box, buttons


class Wizard(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, paths: list[Path]):
        super().__init__(application=app, title="VCV Rack Plugin Installer", default_width=600, default_height=660)
        self.heading = Adw.WindowTitle(title=self.get_title())
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT)
        view = Adw.ToolbarView(content=self.stack)
        view.add_top_bar(Adw.HeaderBar(title_widget=self.heading))
        view.add_top_bar(Adw.Banner(title="VCV Rack is running. Restart it after installing to load the new plugins.",
                                    revealed=core.rack_running()))
        self.set_content(view)
        if paths:
            self.inspect(paths)
        else:
            self.choose()

    def show(self, step: str, widget: Gtk.Widget):
        self.heading.set_subtitle(step)
        self.stack.add_child(widget)
        self.stack.set_visible_child(widget)

    @staticmethod
    def background(work, then):
        threading.Thread(target=lambda: GLib.idle_add(then, work()), daemon=True).start()

    def choose(self):
        content = status("package-x-generic-symbolic", "Install VCV Rack Plugins",
                         "Choose .vcvplugin packages, or drop them here.")
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", lambda _t, files, _x, _y: self.inspect([Path(f.get_path()) for f in files.get_files() if f.get_path()]) or True)
        content.add_controller(drop)
        self.show("Choose packages", page(content, ("Choose Packages…", "suggested-action", self.open_dialog))[0])

    def open_dialog(self):
        pattern = Gtk.FileFilter(name="VCV Rack plugin packages")
        pattern.add_pattern("*.vcvplugin")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(pattern)
        dialog = Gtk.FileDialog(title="Choose Plugin Packages", filters=filters)

        def chosen(_dialog, result):
            try:
                files = dialog.open_multiple_finish(result)
            except GLib.Error:
                return
            self.inspect([Path(f.get_path()) for f in (files.get_item(i) for i in range(files.get_n_items())) if f.get_path()])

        dialog.open_multiple(self, None, chosen)

    def inspect(self, paths: list[Path]):
        if not paths:
            return
        spinner = Adw.Spinner() if hasattr(Adw, "Spinner") else Gtk.Spinner(spinning=True)
        spinner.set_size_request(48, 48)
        self.show("Inspecting", page(status(None, "Inspecting Packages…", child=spinner))[0])
        self.background(lambda: [core.analyze(p) for p in paths], self.review)

    def review(self, plans: list[core.Plan]):
        if all(p.blocked for p in plans):
            return self.finish(False, "Cannot Install", "", [row(p.title, p.summary, plan_icon(p)) for p in plans])
        checks, rows = [], []
        for plan in plans:
            details = list(detail_rows(plan))
            r = Adw.ExpanderRow(title=plan.title, subtitle=plan.summary, use_markup=False,
                                expanded=plan.blocked or plan.needs_confirmation, enable_expansion=bool(details))
            r.add_prefix(Gtk.Image(icon_name=plan_icon(plan)))
            check = Gtk.CheckButton(active=not (plan.blocked or plan.noop), sensitive=not plan.blocked, valign=Gtk.Align.CENTER)
            r.add_suffix(check)
            for d in details:
                r.add_row(d)
            checks.append((plan, check))
            rows.append(r)
        prefs = Adw.PreferencesPage()
        prefs.add(group(rows, title="Packages", description=f"Installing into {core.tilde(core.PLUGINS_DIR)}"))
        box, (_, install) = page(prefs, ("Cancel", None, self.close),
                                 ("Install", "suggested-action", lambda: self.confirm([p for p, c in checks if c.get_active()])))

        def sync(*_):
            install.set_sensitive(any(c.get_active() for _, c in checks))

        for _, c in checks:
            c.connect("toggled", sync)
        sync()
        self.show("Review", box)

    def confirm(self, todo: list[core.Plan], approved: tuple = ()):
        """Walk the selection, stopping at a confirmation page for each plan with warnings."""
        while todo and not todo[0].needs_confirmation:
            approved, todo = (*approved, todo[0]), todo[1:]
        if not todo:
            if approved:
                return self.install(list(approved))
            return self.finish(None, "Nothing Installed", "Every package was skipped.", [])
        plan, rest = todo[0], todo[1:]
        title = {Action.DOWNGRADE: f"Downgrade {plan.title}?",
                 Action.SAME_DIFFERS: f"Overwrite {plan.title} {plan.version}?"}.get(plan.action, f"Install {plan.title} Anyway?")
        content = status("dialog-warning-symbolic", title, plan.summary, group(detail_rows(plan)))
        self.show("Confirm", page(content, ("Skip", None, lambda: self.confirm(rest, approved)),
                                  ("Install Anyway", "destructive-action", lambda: self.confirm(rest, (*approved, plan))))[0])

    def install(self, plans: list[core.Plan]):
        bar = Gtk.ProgressBar(show_text=True)
        log = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                           top_margin=8, bottom_margin=8, left_margin=10, right_margin=10)
        buffer = log.get_buffer()
        end = buffer.create_mark(None, buffer.get_end_iter(), False)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=24, margin_start=24, margin_end=24)
        content.append(Gtk.Label(label=f"Installing {len(plans)} plugin{'s' * (len(plans) != 1)}", css_classes=["title-2"]))
        content.append(bar)
        content.append(Gtk.ScrolledWindow(child=log, vexpand=True, css_classes=["card"]))
        self.show("Installing", page(content)[0])

        def append(text):
            buffer.insert(buffer.get_end_iter(), text + "\n")
            log.scroll_mark_onscreen(end)

        def update(fraction, text):
            bar.set_fraction(fraction)
            bar.set_text(text)

        def work():
            results, last = [], {"name": None, "t": 0.0}
            for i, plan in enumerate(plans):
                GLib.idle_add(append, f"── {plan.title} {plan.version}")

                def progress(name, done, total, i=i, plan=plan):
                    if name != last["name"]:
                        last["name"] = name
                        GLib.idle_add(append, name)
                    if (now := time.monotonic()) - last["t"] > 0.05 or done == total:
                        last["t"] = now
                        GLib.idle_add(update, (i + (done / total if total else 1)) / len(plans), f"{plan.title}: {name}")

                try:
                    results.append((plan, core.install(plan, progress=progress), None))
                except Exception as e:
                    results.append((plan, None, e))
                    GLib.idle_add(append, f"error: {e}")
            return results

        self.background(work, self.done)

    def done(self, results):
        ok = [row(p.title, f"{p.version} → {core.tilde(dest)}", OK_ICON) for p, dest, e in results if not e]
        failed = [row(p.title, str(e), LEVEL_ICON[Level.ERROR]) for p, _, e in results if e]
        if not ok:
            return self.finish(False, "Installation Failed", "No plugins were installed.", failed)
        running = core.rack_running()
        self.finish(True, f"Plugin{'s' * (len(ok) > 1)} Installed",
                    "Restart VCV Rack to load the new plugins." if running else "Start VCV Rack to use the new plugins.",
                    ok + failed)

    def finish(self, success: bool | None, title: str, description: str, rows: list[Adw.ActionRow]):
        icon = {True: "emblem-ok-symbolic", False: "dialog-error-symbolic", None: "dialog-information-symbolic"}[success]
        content = status(icon, title, description, group(rows) if rows else None)
        if not success:
            return self.show("Failed" if success is False else "Done", page(content, ("Close", "suggested-action", self.close))[0])
        rack, running = core.find_rack(), core.rack_running()
        box, (_, start) = page(content, ("Close", None, self.close), ("Start Rack2", "suggested-action", lambda: self.start_rack(rack)))
        if rack is None or running:
            start.set_sensitive(False)
            start.set_tooltip_text("VCV Rack is already running" if running else
                                   "Rack executable not found; set RACK_EXECUTABLE or put Rack on PATH")
        self.show("Done", box)

    def start_rack(self, exe: Path):
        subprocess.Popen([exe], cwd=exe.parent, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.close()


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)

    def do_activate(self):
        Wizard(self, []).present()

    def do_open(self, files, _n_files, _hint):
        Wizard(self, [Path(f.get_path()) for f in files if f.get_path()]).present()


def run():
    sys.exit(App().run(sys.argv))


if __name__ == "__main__":
    run()

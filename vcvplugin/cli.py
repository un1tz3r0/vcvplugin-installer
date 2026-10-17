"""Install VCV Rack 2 .vcvplugin packages from the command line."""
import argparse
import contextlib
import sys
from pathlib import Path

from . import N_, _, __version__, core

LABEL = {core.Level.INFO: N_("note: {text}"), core.Level.WARN: N_("warning: {text}"), core.Level.ERROR: N_("error: {text}")}


def report(plan: core.Plan):
    summary = _("rejected") if plan.blocked else plan.summary
    print(f"{plan.title} ({plan.source.name}): {summary}")
    for issue in plan.issues:
        print("  " + _(LABEL[issue.level]).format(text=issue.text))
    if plan.diff:
        print("  " + _("files: {diff}").format(diff=plan.diff))


def ask(question: str) -> bool:
    # Translators: the answers ask() accepts as yes, separated by |
    yes = _("y|yes").split("|")
    try:
        return input("  " + _("{question} [y/N]").format(question=question) + " ").strip().lower() in yes
    except EOFError:
        return False


def progress_line(name: str, done: int, total: int):
    pct = 100 * done // total if total else 100
    print(f"\r\033[K  {pct:3d}% {name[-70:]}", end="", file=sys.stderr, flush=True)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vcvplugin-install", description=_("Install VCV Rack 2 .vcvplugin packages from the command line."),
                                 epilog=_("exit status: 0 all done, 1 some package failed or was rejected,\n"
                                          "2 some package was skipped because it needs confirmation (see --yes), 3 both"),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packages", nargs="+", type=Path, metavar="PACKAGE.vcvplugin")
    ap.add_argument("-y", "--yes", action="store_true", help=_("proceed past warnings (downgrades, same-version rebuilds, ...)"))
    ap.add_argument("-i", "--interactive", action="store_true", help=_("ask before proceeding past warnings"))
    ap.add_argument("--reinstall", action="store_true", help=_("install even when the identical version is already installed"))
    ap.add_argument("--defer", action="store_true", help=_("copy the package for Rack to unpack on its next start instead of unpacking now"))
    ap.add_argument("-n", "--dry-run", action="store_true", help=_("only report what would happen"))
    ap.add_argument("-q", "--quiet", action="store_true", help=_("only report problems"))
    ap.add_argument("--wait", action="store_true", help=_("wait for Enter before exiting (for terminal launchers)"))
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return ap


def main(argv=None) -> int:
    args = parser().parse_args(argv)

    if core.rack_running():
        print(_("warning: VCV Rack is running; restart it to load installed plugins"), file=sys.stderr)
    status = 0
    for path in args.packages:
        plan = core.analyze(path, defer=args.defer)
        if not args.quiet or plan.blocked or plan.needs_confirmation:
            report(plan)
        if plan.blocked:
            status |= 1
            continue
        if plan.noop and not args.reinstall:
            continue
        question = _("Install {plugin} {version} anyway?").format(plugin=plan.title, version=plan.version)
        if plan.needs_confirmation and not args.yes and not (args.interactive and ask(question)):
            print("  " + _("skipped (pass --yes to proceed past warnings)"), file=sys.stderr)
            status |= 2
            continue
        if args.dry_run:
            would = _("would copy into {folder}") if args.defer else _("would unpack into {folder}")
            print("  " + would.format(folder=core.tilde(core.PLUGINS_DIR)))
            continue
        show = progress_line if sys.stderr.isatty() and not args.quiet else lambda *_: None
        try:
            dest = core.install(plan, defer=args.defer, progress=show)
        except Exception as e:
            status |= 1
            error = "  " + _("error: {text}").format(text=e)
            print("\r\033[K" + error if sys.stderr.isatty() else error, file=sys.stderr)
            continue
        if show is progress_line:
            print("\r\033[K", end="", file=sys.stderr)
        if not args.quiet:
            print("  " + _("installed {version} → {path}").format(version=plan.version, path=core.tilde(dest)))
    if args.wait:
        with contextlib.suppress(EOFError, KeyboardInterrupt):
            input(_("Press Enter to close…"))
    return status


def run():
    sys.exit(main())


if __name__ == "__main__":
    run()

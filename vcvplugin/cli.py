"""Install VCV Rack 2 .vcvplugin packages from the command line."""
import argparse
import contextlib
import sys
from pathlib import Path

from . import __version__, core

LABEL = {core.Level.INFO: "note", core.Level.WARN: "warning", core.Level.ERROR: "error"}

EXIT_HELP = """exit status: 0 all done, 1 some package failed or was rejected,
2 some package was skipped because it needs confirmation (see --yes), 3 both"""


def report(plan: core.Plan):
    print(f"{plan.title} ({plan.source.name}): {'rejected' if plan.blocked else plan.summary}")
    for issue in plan.issues:
        print(f"  {LABEL[issue.level]}: {issue.text}")
    if plan.diff:
        print(f"  files: {plan.diff}")


def ask(question: str) -> bool:
    try:
        return input(f"  {question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def progress_line(name: str, done: int, total: int):
    pct = 100 * done // total if total else 100
    print(f"\r\033[K  {pct:3d}% {name[-70:]}", end="", file=sys.stderr, flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vcvplugin-install", description=__doc__, epilog=EXIT_HELP,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packages", nargs="+", type=Path, metavar="PACKAGE.vcvplugin")
    ap.add_argument("-y", "--yes", action="store_true", help="proceed past warnings (downgrades, same-version rebuilds, ...)")
    ap.add_argument("-i", "--interactive", action="store_true", help="ask before proceeding past warnings")
    ap.add_argument("--reinstall", action="store_true", help="install even when the identical version is already installed")
    ap.add_argument("--defer", action="store_true", help="copy the package for Rack to unpack on its next start instead of unpacking now")
    ap.add_argument("-n", "--dry-run", action="store_true", help="only report what would happen")
    ap.add_argument("-q", "--quiet", action="store_true", help="only report problems")
    ap.add_argument("--wait", action="store_true", help="wait for Enter before exiting (for terminal launchers)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)

    if core.rack_running():
        print("warning: VCV Rack is running; restart it to load installed plugins", file=sys.stderr)
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
        if plan.needs_confirmation and not args.yes and not (args.interactive and ask(f"Install {plan.title} {plan.version} anyway?")):
            print("  skipped (pass --yes to proceed past warnings)", file=sys.stderr)
            status |= 2
            continue
        if args.dry_run:
            print(f"  would {'copy' if args.defer else 'unpack'} into {core.tilde(core.PLUGINS_DIR)}")
            continue
        show = progress_line if sys.stderr.isatty() and not args.quiet else lambda *_: None
        try:
            dest = core.install(plan, defer=args.defer, progress=show)
        except Exception as e:
            status |= 1
            print(f"\r\033[K  error: {e}" if sys.stderr.isatty() else f"  error: {e}", file=sys.stderr)
            continue
        if show is progress_line:
            print("\r\033[K", end="", file=sys.stderr)
        if not args.quiet:
            print(f"  installed {plan.version} → {core.tilde(dest)}")
    if args.wait:
        with contextlib.suppress(EOFError, KeyboardInterrupt):
            input("Press Enter to close…")
    return status


def run():
    sys.exit(main())


if __name__ == "__main__":
    run()

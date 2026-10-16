#!/usr/bin/env bash
# Build and install vcvplugin-install / vcvplugin-gui for the current user with Meson,
# and register the GUI as the default handler for *.vcvplugin files.
#   ./install-desktop-files.sh              install or update
#   ./install-desktop-files.sh --uninstall  remove everything this script installed
# Environment: PREFIX (default ~/.local)
set -euo pipefail

APP_ID=io.github.un1tz3r0.VcvPluginInstaller
MIME=application/x-vcvplugin
SRC=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
BUILD=$SRC/_build
PREFIX=${PREFIX:-$HOME/.local}

have() { command -v "$1" >/dev/null; }

if [[ ${1:-} == --uninstall ]]; then
  ninja -C "$BUILD" uninstall
  # Meson refreshes these caches after installing, but not after uninstalling.
  have update-mime-database && update-mime-database "$PREFIX/share/mime"
  have update-desktop-database && update-desktop-database -q "$PREFIX/share/applications"
  have gtk-update-icon-cache && gtk-update-icon-cache -qtf "$PREFIX/share/icons/hicolor" 2>/dev/null || true
  exit
fi

have meson || { echo "meson not found; install meson (it brings ninja), e.g. sudo apt install meson" >&2; exit 1; }
python3 - <<'EOF'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"Python 3.11+ required, found {sys.version.split()[0]}")
try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk
except (ImportError, ValueError) as e:
    sys.exit(f"{e}\nInstall PyGObject with GTK 4 and libadwaita, for example:\n"
             "  Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1\n"
             "  Fedora:        sudo dnf install python3-gobject gtk4 libadwaita\n"
             "  Arch:          sudo pacman -S python-gobject gtk4 libadwaita")
EOF
python3 -c 'import compression.zstd' 2>/dev/null || python3 -c 'import zstandard' 2>/dev/null || have zstd ||
  echo "warning: no zstd decoder found and Rack 2 packages are tar.zst; install the zstd package" >&2

meson setup $([[ -d $BUILD/meson-private ]] && echo --reconfigure) --prefix "$PREFIX" "$BUILD" "$SRC"
meson install -C "$BUILD"
have xdg-mime && xdg-mime default "$APP_ID.desktop" "$MIME"

echo "default handler for *.vcvplugin: $(have xdg-mime && xdg-mime query default "$MIME" || echo '(xdg-mime missing)')"
[[ :$PATH: == *":$PREFIX/bin:"* ]] || echo "note: $PREFIX/bin is not on PATH" >&2

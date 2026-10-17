"""VCV Rack 2 plugin package installer."""
import gettext
from pathlib import Path

__version__ = Path(__file__).with_name("VERSION").read_text().strip()

DOMAIN = "vcvplugin-installer"
# Meson installs this package to <prefix>/share/vcvplugin-installer/vcvplugin/ and the translations to <prefix>/share/locale/.
_localedir = Path(__file__).resolve().parents[2] / "locale"
_translation = gettext.translation(DOMAIN, _localedir if gettext.find(DOMAIN, _localedir) else None, fallback=True)
_, ngettext = _translation.gettext, _translation.ngettext


def N_(message: str) -> str:
    """Mark a string for translation, to be translated with _() where it is shown."""
    return message

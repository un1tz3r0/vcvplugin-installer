"""VCV Rack 2 plugin package installer."""
from pathlib import Path

__version__ = Path(__file__).with_name("VERSION").read_text().strip()

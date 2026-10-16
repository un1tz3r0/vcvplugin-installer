#!/usr/bin/env python3
"""Print the AppStream release notes for a version as Markdown; fail if the metainfo has no release for it.

    build-aux/release-notes.py [VERSION]     (default: the version in vcvplugin/VERSION)
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
METAINFO = SRC / "data" / "io.github.un1tz3r0.VcvPluginInstaller.metainfo.xml"


def text(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else (SRC / "vcvplugin" / "VERSION").read_text().strip()
    releases = ET.parse(METAINFO).findall("releases/release")
    if len(sys.argv) == 1 and releases and releases[0].get("version") != version:
        print(f"error: the newest release in {METAINFO.name} is {releases[0].get('version')}, not {version}; "
              "add a <release> for it at the top of <releases>", file=sys.stderr)
        return 1
    release = next((r for r in releases if r.get("version") == version), None)
    if release is None or release.find("description") is None:
        print(f"error: {METAINFO.name} has no <release> with a <description> for {version}", file=sys.stderr)
        return 1
    for block in release.find("description"):
        if block.tag == "p":
            print(text(block), end="\n\n")
        else:
            print("\n".join(f"- {text(li)}" for li in block.iter("li")), end="\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

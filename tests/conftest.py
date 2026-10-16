import io
import json
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from vcvplugin import core

ELF_X64 = b"\x7fELF" + bytes(14) + (0x3E).to_bytes(2, "little") + bytes(44)


def zstd_available() -> bool:
    try:
        import compression.zstd  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import zstandard  # noqa: F401
        return True
    except ImportError:
        return shutil.which("zstd") is not None


def _zstd_compress(data: bytes) -> bytes:
    try:
        from compression import zstd
        return zstd.compress(data)
    except ImportError:
        pass
    try:
        import zstandard
        return zstandard.ZstdCompressor().compress(data)
    except ImportError:
        return subprocess.run(["zstd", "-qc"], input=data, stdout=subprocess.PIPE, check=True).stdout


@pytest.fixture
def plugins_dir(tmp_path, monkeypatch) -> Path:
    """An empty Rack user folder; core's paths are fixed at import, so patch them."""
    rack = tmp_path / "Rack2"
    monkeypatch.setattr(core, "RACK_DIR", rack)
    monkeypatch.setattr(core, "PLUGINS_DIR", rack / f"plugins-{core.ARCH}")
    monkeypatch.setattr(core, "rack_running", lambda: False)
    return core.PLUGINS_DIR


@pytest.fixture
def make_package(tmp_path):
    """Build a plugin package; `files` maps paths under the plugin folder to contents."""
    def make(slug="TestPlugin", version="2.0.0", *, fmt="zip", root=None, arch="lin-x64", filename=None,
             manifest=None, files=None, dest=None) -> Path:
        root = slug if root is None else root
        manifest = {"slug": slug, "version": version} if manifest is None else manifest
        contents = {"plugin.json": json.dumps(manifest).encode(), "plugin.so": ELF_X64, **(files or {})}
        entries = {(f"{root}/{k}" if root else k): v for k, v in contents.items() if v is not None}
        path = (dest or tmp_path / "packages") / (filename or f"{slug}-{version}-{arch}.vcvplugin")
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "zip":
            with zipfile.ZipFile(path, "w") as z:
                for name, data in entries.items():
                    z.writestr(name, data)
            return path
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz" if fmt == "tar.gz" else "w") as tf:
            for name, data in entries.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o644
                tf.addfile(info, io.BytesIO(data))
        data = buf.getvalue()
        path.write_bytes(_zstd_compress(data) if fmt == "tar.zst" else data)
        return path

    return make


@pytest.fixture
def install_dir(plugins_dir):
    """Create an unpacked plugin as Rack would leave it."""
    def make(slug="TestPlugin", version="2.0.0", files=None) -> Path:
        d = plugins_dir / slug
        d.mkdir(parents=True)
        for name, data in {"plugin.json": json.dumps({"slug": slug, "version": version}).encode(),
                           "plugin.so": ELF_X64, **(files or {})}.items():
            (d / name).write_bytes(data)
        return d

    return make

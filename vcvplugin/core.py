"""Inspect VCV Rack 2 plugin packages, compare them with what is installed, and install them."""
from __future__ import annotations

import contextlib
import enum
import fcntl
import glob
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path, PurePosixPath
from typing import IO

ARCH = "lin-x64"
RACK_ABI_MAJOR = 2
RACK_DIR = Path(os.environ.get("RACK_USER_DIR", Path.home() / ".local/share/Rack2"))
PLUGINS_DIR = RACK_DIR / f"plugins-{ARCH}"
NAME_RE = re.compile(r"^(?P<slug>.+?)-(?P<version>\d[^/]*?)-(?P<arch>(?:lin|win|mac)-(?:x64|arm64))\.vcvplugin$")
SLUG_RE = re.compile(r"[A-Za-z0-9_-]+")
VERSION_RE = re.compile(r"\d+(\.\d+)*")
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
CHUNK = 1 << 20

Progress = Callable[[str, int, int], None]


class PackageError(Exception):
    pass


class Level(enum.IntEnum):
    INFO = 0
    WARN = 1
    ERROR = 2


class Action(enum.Enum):
    INSTALL = "new install"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    SAME = "already installed"
    SAME_DIFFERS = "same version, different files"


def version_key(v: str):
    core, _, pre = v.split("+", 1)[0].partition("-")
    nums = tuple(int(n) for n in re.findall(r"\d+", core))
    return nums + (0,) * (3 - len(nums)), (1,) if not pre else (0, pre)


def tilde(path: Path) -> str:
    home = str(Path.home())
    return "~" + str(path)[len(home):] if str(path).startswith(home + "/") else str(path)


def _unzstd(src: IO[bytes], dst: IO[bytes]):
    try:
        from compression.zstd import ZstdFile  # Python 3.14+
    except ImportError:
        pass
    else:
        return shutil.copyfileobj(ZstdFile(src), dst, CHUNK)
    try:
        import zstandard
    except ImportError:
        pass
    else:
        return zstandard.ZstdDecompressor().copy_stream(src, dst)
    try:
        subprocess.run(["zstd", "-dcq"], stdin=src, stdout=dst, stderr=subprocess.PIPE, check=True)
    except FileNotFoundError:
        raise PackageError("zstd archives need Python 3.14+, the 'zstandard' module or the zstd command") from None
    except subprocess.CalledProcessError as e:
        raise PackageError(f"zstd: {e.stderr.decode().strip()}") from None


@dataclass
class Entry:
    size: int
    mode: int
    open: Callable[[], IO[bytes]]


class Package:
    """A plugin archive (zip, or tar optionally zstd/gzip/xz compressed), keyed by paths relative to its plugin folder."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._stack = contextlib.ExitStack()
        try:
            self._load()
        except PackageError:
            self.close()
            raise
        except Exception as e:
            self.close()
            raise PackageError(f"unreadable archive: {e}") from e

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self._stack.close()

    def _members(self):
        with open(self.path, "rb") as f:
            magic = f.read(4)
        if magic == b"PK\x03\x04":
            zf = self._stack.enter_context(zipfile.ZipFile(self.path))
            for i in zf.infolist():
                mode = i.external_attr >> 16
                kind = "dir" if i.is_dir() else "other" if stat.S_ISLNK(mode) else "file"
                yield i.filename, kind, mode & 0o777, i.file_size, partial(zf.open, i)
            return
        if magic == ZSTD_MAGIC:
            buf = self._stack.enter_context(tempfile.TemporaryFile())
            with open(self.path, "rb") as src:
                _unzstd(src, buf)
            buf.seek(0)
            tf = self._stack.enter_context(tarfile.open(fileobj=buf))
        else:
            try:
                tf = self._stack.enter_context(tarfile.open(self.path))
            except tarfile.ReadError:
                raise PackageError("not a zip, tar or tar.zst archive") from None
        for m in tf.getmembers():
            kind = "file" if m.isfile() else "dir" if m.isdir() else "other"
            yield m.name, kind, m.mode & 0o777, m.size, partial(tf.extractfile, m)

    def _load(self):
        files, dirs = {}, set()
        for name, kind, mode, size, opener in self._members():
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts:
                raise PackageError(f"unsafe path in archive: {name}")
            if not p.parts:
                continue
            if kind == "other":
                raise PackageError(f"unsupported archive entry (link or device): {name}")
            if kind == "dir":
                dirs.add(str(p))
            else:
                files[str(p)] = Entry(size, (mode or 0o644) | 0o600, opener)

        if "plugin.json" in files:
            root = ""
        else:
            tops = {k.split("/", 1)[0] for k in files}
            root = tops.pop() if len(tops) == 1 else ""
            if f"{root}/plugin.json" not in files:
                raise PackageError("no plugin.json in package")
        cut = len(root) + 1 if root else 0
        self.root = root
        self.files = {k[cut:]: e for k, e in files.items()}
        self.dirs = sorted(d[cut:] for d in dirs if not root or d.startswith(root + "/"))

        try:
            manifest = json.loads(self.read("plugin.json"))
        except ValueError as e:
            raise PackageError(f"plugin.json is not valid JSON: {e}") from None
        slug, version = manifest.get("slug"), manifest.get("version")
        if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
            raise PackageError(f"plugin.json has an invalid or missing slug: {slug!r}")
        if not isinstance(version, str) or not VERSION_RE.match(version):
            raise PackageError(f"plugin.json has an invalid or missing version: {version!r}")
        self.manifest, self.slug, self.version = manifest, slug, version
        self.name = manifest.get("name") or slug

    def read(self, rel: str) -> bytes:
        with self.files[rel].open() as f:
            return f.read()

    def digests(self) -> dict[str, str]:
        out = {}
        for rel, e in self.files.items():
            with e.open() as f:
                out[rel] = hashlib.file_digest(f, "sha256").hexdigest()
        return out

    def platform_problem(self) -> str | None:
        if foreign := [n for n in ("plugin.dll", "plugin.dylib") if n in self.files]:
            return f"contains {foreign[0]}: this package is built for another operating system"
        if "plugin.so" not in self.files:
            return "package has no plugin.so"
        with self.files["plugin.so"].open() as f:
            elf = f.read(20)
        if elf[:4] != b"\x7fELF":
            return "plugin.so is not an ELF shared library"
        if (machine := int.from_bytes(elf[18:20], "little")) != 0x3E:
            return f"plugin.so is built for another CPU (ELF machine {machine:#x}, need x86-64)"
        return None


def dir_digests(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            with open(p, "rb") as f:
                out[p.relative_to(root).as_posix()] = hashlib.file_digest(f, "sha256").hexdigest()
    return out


@dataclass
class Installed:
    path: Path
    version: str | None

    @property
    def is_package(self) -> bool:
        return self.path.suffix == ".vcvplugin"

    def digests(self) -> dict[str, str]:
        if not self.is_package:
            return dir_digests(self.path)
        try:
            with Package(self.path) as pkg:
                return pkg.digests()
        except PackageError:
            return {}


def _manifest_version(path: Path) -> str | None:
    try:
        v = json.loads(path.read_text()).get("version")
        return v if isinstance(v, str) else None
    except (OSError, ValueError, AttributeError):
        return None


def find_installed(slug: str, exclude: Path | None = None) -> tuple[Installed | None, list[Installed]]:
    """Return (what Rack will load after its next start, packages awaiting extraction) for a slug."""
    pending = []
    for p in sorted(PLUGINS_DIR.glob(f"{glob.escape(slug)}-*.vcvplugin")):
        if exclude and exclude.exists() and p.samefile(exclude):
            continue
        try:
            with Package(p) as pkg:
                found, version = pkg.slug, pkg.version
        except PackageError:
            m = NAME_RE.match(p.name)
            found, version = (m["slug"] if m else None), None
        if found == slug:
            pending.append(Installed(p, version))
    d = PLUGINS_DIR / slug
    unpacked = Installed(d, _manifest_version(d / "plugin.json")) if os.path.lexists(d) else None
    return (pending[0] if pending else unpacked), pending


@dataclass
class Issue:
    level: Level
    text: str


@dataclass
class Diff:
    changed: list[str]
    added: list[str]
    removed: list[str]

    @classmethod
    def of(cls, new: dict[str, str], old: dict[str, str]) -> Diff:
        return cls(sorted(k for k in new.keys() & old.keys() if new[k] != old[k]),
                   sorted(new.keys() - old.keys()), sorted(old.keys() - new.keys()))

    def groups(self) -> list[tuple[str, list[str]]]:
        return [(label, names) for label, names in
                (("changed", self.changed), ("added", self.added), ("removed", self.removed)) if names]

    def __bool__(self):
        return bool(self.groups())

    def __str__(self):
        return ", ".join(f"{len(names)} {label}" for label, names in self.groups()) or "identical"


@dataclass(eq=False)
class Plan:
    source: Path
    slug: str = ""
    name: str = ""
    version: str = ""
    action: Action | None = None
    current: Installed | None = None
    pending: list[Installed] = field(default_factory=list)
    diff: Diff | None = None
    issues: list[Issue] = field(default_factory=list)

    def add(self, level: Level, text: str):
        self.issues.append(Issue(level, text))

    @property
    def blocked(self) -> bool:
        return any(i.level is Level.ERROR for i in self.issues)

    @property
    def needs_confirmation(self) -> bool:
        return not self.blocked and any(i.level is Level.WARN for i in self.issues)

    @property
    def noop(self) -> bool:
        return self.action is Action.SAME

    @property
    def title(self) -> str:
        return self.name or self.slug or self.source.name

    @property
    def summary(self) -> str:
        if self.blocked:
            return next(i.text for i in self.issues if i.level is Level.ERROR)
        versions = f"{self.current.version or '?'} → {self.version}" if self.current else self.version
        return f"{versions} · {self.action.value}"


def analyze(path: Path | str, *, defer: bool = False) -> Plan:
    """Inspect a package and decide what installing it would do. Never raises; problems become issues."""
    path = Path(path).expanduser().absolute()
    plan = Plan(path)
    m = NAME_RE.match(path.name)
    if m and m["arch"] != ARCH:
        plan.add(Level.ERROR, f"built for {m['arch']}, this system needs {ARCH}")
    try:
        with Package(path) as pkg:
            plan.slug, plan.version, plan.name = pkg.slug, pkg.version, pkg.name
            if problem := pkg.platform_problem():
                plan.add(Level.ERROR, problem)
            if pkg.root != pkg.slug:
                layout = f"top-level folder {pkg.root!r}" if pkg.root else "no top-level folder"
                if defer:
                    plan.add(Level.ERROR, f"package has {layout}; Rack would not unpack it into {pkg.slug}/")
                else:
                    plan.add(Level.INFO, f"package has {layout}; it will be installed into {pkg.slug}/")
            new = pkg.digests()
    except (OSError, PackageError) as e:
        plan.add(Level.ERROR, str(e))
        return plan

    if not m:
        plan.add(Level.INFO, f"file name does not follow <slug>-<version>-{ARCH}.vcvplugin")
    elif m["slug"] != plan.slug or m["version"] != plan.version:
        plan.add(Level.WARN, f"file name says {m['slug']} {m['version']} but plugin.json says {plan.slug} {plan.version}")
    if version_key(plan.version)[0][0] != RACK_ABI_MAJOR:
        plan.add(Level.WARN, f"version {plan.version} does not start with {RACK_ABI_MAJOR}.; Rack {RACK_ABI_MAJOR} will refuse to load it")

    plan.current, plan.pending = find_installed(plan.slug, exclude=path)
    cur = plan.current
    if len(plan.pending) > 1:
        plan.add(Level.WARN, f"{len(plan.pending)} packages for {plan.slug} are waiting for Rack to unpack them; all will be replaced")
    elif plan.pending:
        plan.add(Level.INFO, f"replaces {plan.pending[0].path.name}, which was waiting for Rack to unpack it")
    unpacked = PLUGINS_DIR / plan.slug
    if unpacked.is_symlink():
        plan.add(Level.WARN, f"installed {plan.slug} is a symlink to {tilde(unpacked.resolve())} (a development checkout?); it will be replaced")

    if cur is None:
        plan.action = Action.INSTALL
    elif cur.version is None:
        plan.action = Action.INSTALL
        plan.add(Level.WARN, f"existing {tilde(cur.path)} has no readable version; it will be replaced")
    else:
        old, new_key = version_key(cur.version), version_key(plan.version)
        plan.action = Action.UPGRADE if new_key > old else Action.DOWNGRADE if new_key < old else Action.SAME
    if cur:
        plan.diff = Diff.of(new, cur.digests())

    if plan.action is Action.DOWNGRADE:
        plan.add(Level.WARN, f"downgrade: installed version {cur.version} is newer than {plan.version}")
    elif plan.action is Action.SAME and plan.diff:
        plan.action = Action.SAME_DIFFERS
        plan.add(Level.WARN, f"version {plan.version} is already installed but the files differ ({plan.diff}); forgot to bump the version?")
    elif plan.action is Action.SAME:
        plan.add(Level.INFO, f"{plan.slug} {plan.version} is already installed with identical files")
    return plan


@contextlib.contextmanager
def _locked():
    RACK_DIR.mkdir(parents=True, exist_ok=True)
    with open(RACK_DIR / ".vcvplugin-installer.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _copy(src: IO[bytes], dst: IO[bytes], name: str, done: int, total: int, progress: Progress) -> int:
    progress(name, done, total)
    while chunk := src.read(CHUNK):
        dst.write(chunk)
        done += len(chunk)
        progress(name, done, total)
    return done


def _extract(plan: Plan, pending: list[Installed], progress: Progress) -> Path:
    target = PLUGINS_DIR / plan.slug
    with Package(plan.source) as pkg, tempfile.TemporaryDirectory(prefix=f".{plan.slug}.", dir=PLUGINS_DIR) as tmp:
        if (pkg.slug, pkg.version) != (plan.slug, plan.version):
            raise PackageError(f"{plan.source.name} changed since it was inspected")
        staged, retired = Path(tmp, "new"), Path(tmp, "old")
        staged.mkdir()
        for d in pkg.dirs:
            (staged / d).mkdir(parents=True, exist_ok=True)
        total, done = sum(e.size for e in pkg.files.values()), 0
        for rel, entry in pkg.files.items():
            dst = staged / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            with entry.open() as src, open(dst, "wb") as out:
                done = _copy(src, out, rel, done, total, progress)
            dst.chmod(entry.mode)
        if os.path.lexists(target):
            target.rename(retired)  # lands inside tmp, so the old version is deleted with it
        try:
            staged.rename(target)
        except BaseException:
            if os.path.lexists(retired):
                retired.rename(target)
            raise
    in_plugins_dir = plan.source.parent.resolve() == PLUGINS_DIR.resolve()
    for p in [*pending, *([Installed(plan.source, plan.version)] if in_plugins_dir else [])]:
        p.path.unlink(missing_ok=True)  # otherwise Rack would unpack it again over what we just installed
    return target


def _defer(plan: Plan, pending: list[Installed], progress: Progress) -> Path:
    dest = PLUGINS_DIR / f"{plan.slug}-{plan.version}-{ARCH}.vcvplugin"
    part = dest.with_name(f".{dest.name}.part")
    with open(plan.source, "rb") as src, open(part, "wb") as out:
        _copy(src, out, dest.name, 0, plan.source.stat().st_size, progress)
    for p in pending:
        if p.path != dest:
            p.path.unlink(missing_ok=True)
    part.replace(dest)
    return dest


def install(plan: Plan, *, defer: bool = False, progress: Progress = lambda name, done, total: None) -> Path:
    """Unpack the package into PLUGINS_DIR/<slug> atomically, or with defer=True copy it there for Rack to unpack."""
    if plan.blocked:
        raise PackageError(plan.summary)
    with _locked():
        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        _, pending = find_installed(plan.slug, exclude=plan.source)
        return (_defer if defer else _extract)(plan, pending, progress)


def rack_running() -> bool:
    for comm in Path("/proc").glob("[0-9]*/comm"):
        with contextlib.suppress(OSError):
            if comm.read_text().strip() == "Rack":
                return True
    return False


def find_rack() -> Path | None:
    home = Path.home()
    candidates = [
        *([Path(os.environ["RACK_EXECUTABLE"])] if "RACK_EXECUTABLE" in os.environ else []),
        *([Path(w)] if (w := shutil.which("Rack")) else []),
        *sorted(home.glob("Rack2*/Rack")), *sorted(home.glob("Applications/Rack2*/Rack")),
        *sorted(home.glob(".local/opt/Rack2*/Rack")), *sorted(Path("/opt").glob("Rack2*/Rack")),
    ]
    return next((p for p in candidates if p.is_file() and os.access(p, os.X_OK)), None)

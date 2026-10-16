#!/usr/bin/env python3
"""backup_verify - verify a pull-style backup folder. Stdlib only, Python 3.10+.

Exit codes: 0 = ok, 1 = warn, 2 = fail.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
import string
import sys
import time
from pathlib import Path

OK, WARN, FAIL = 0, 1, 2
NAMES = {OK: "OK", WARN: "WARN", FAIL: "FAIL"}
MANIFEST = "MANIFEST.sha256"
TMP = MANIFEST + ".tmp"
SKEW = 3600  # newest mtime more than this far in the future => clock skew warning


class ScanError(OSError):
    """A folder could not be read completely, so no verdict can be trusted."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def list_files(root: Path) -> list[str]:
    """Relative POSIX paths of regular files, manifest excluded, sorted.

    Raises ScanError if any directory cannot be read (os.walk would skip it silently).
    """
    out, errors = [], []
    for dirpath, _dirs, files in os.walk(root, onerror=errors.append):
        for name in files:
            p = Path(dirpath) / name
            if p.is_symlink() or not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if rel not in (MANIFEST, TMP):
                out.append(rel)
    if errors:
        e = errors[0]
        raise ScanError(f"cannot read {e.filename}: {e.strerror or e}")
    return sorted(out)


def escape(name: str) -> tuple[str, str]:
    """sha256sum style: a leading backslash on the line, and \\n / \\\\ inside the name."""
    if "\\" in name or "\n" in name:
        return "\\", name.replace("\\", "\\\\").replace("\n", "\\n")
    return "", name


def unescape(name: str) -> str:
    out, i = [], 0
    while i < len(name):
        c = name[i]
        if c == "\\":
            nxt = name[i + 1:i + 2]
            if nxt not in ("\\", "n"):
                raise ValueError("bad escape")
            out.append("\\" if nxt == "\\" else "\n")
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def build_manifest(root: Path) -> int:
    """Atomically write MANIFEST.sha256 (sha256sum format); return number of files."""
    final, tmp = root / MANIFEST, root / TMP
    if final.is_symlink():
        raise OSError(f"{final} is a symlink; refusing to write through it")
    files = list_files(root)
    lines = []
    for rel in files:
        prefix, shown = escape(rel)
        lines.append(f"{prefix}{sha256_file(root / rel)}  {shown}\n")
    if os.path.lexists(tmp):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write("".join(lines).encode("utf-8", "surrogateescape"))
        os.replace(tmp, final)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise
    return len(files)


def read_manifest(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    raw = (root / MANIFEST).read_bytes().decode("utf-8", "surrogateescape")
    for n, line in enumerate(raw.split("\n"), 1):
        if not line:
            continue
        escaped = line.startswith("\\")
        digest, sep, rel = (line[1:] if escaped else line).partition("  ")
        if not sep or len(digest) != 64 or not set(digest) <= set(string.hexdigits):
            raise ValueError(f"{MANIFEST} line {n} is malformed")
        try:
            rel = unescape(rel) if escaped else rel
        except ValueError:
            raise ValueError(f"{MANIFEST} line {n} is malformed") from None
        if not rel or rel in entries:
            raise ValueError(f"{MANIFEST} line {n} is malformed (empty or duplicate path)")
        entries[rel] = digest.lower()
    return entries


def verify(root: Path) -> tuple[int, list[str]]:
    """Compare folder with manifest. Missing/changed/unreadable = FAIL, extra = WARN."""
    mpath = root / MANIFEST
    if mpath.is_symlink() or not mpath.is_file():
        return FAIL, [f"no regular {MANIFEST} in {root} (run 'manifest' first)"]
    try:
        expected = read_manifest(mpath.parent)
        actual = set(list_files(root))
        problems, verdict = [], OK
        for rel, digest in sorted(expected.items()):
            if rel not in actual:
                problems.append(f"MISSING  {rel!r}")
                verdict = FAIL
            elif sha256_file(root / rel) != digest:
                problems.append(f"CHANGED  {rel!r}")
                verdict = FAIL
    except (ValueError, OSError) as e:
        return FAIL, [str(e)]
    for rel in sorted(actual - set(expected)):
        problems.append(f"EXTRA    {rel!r} (not in manifest)")
        verdict = max(verdict, WARN)
    if not expected and not actual:
        return WARN, ["nothing to verify (empty manifest, empty folder)"]
    return verdict, problems


def freshness(root: Path, hours: float, marker: Path | None = None,
              now: float | None = None) -> tuple[int, str]:
    now = time.time() if now is None else now
    if marker is not None:
        if not marker.is_file():
            return FAIL, f"marker file {marker} not found"
        newest, what = marker.stat().st_mtime, "marker"
    else:
        files = list_files(root)
        if not files:
            return FAIL, "no backup files found"
        newest, what = max((root / r).stat().st_mtime for r in files), "newest file"
    age_h = (now - newest) / 3600
    msg = f"{what} is {age_h:.1f} h old (limit {hours:g} h)"
    if age_h > hours:
        return FAIL, msg
    if newest - now > SKEW:
        return WARN, f"{what} is dated in the future ({-age_h:.1f} h): clock skew?"
    return OK, msg


def rsync_verdict(code: int) -> tuple[int, str]:
    """0 = ok; 24 (source files vanished mid-run) = warn; anything else = fail."""
    if code == 0:
        return OK, "rsync exit 0: clean run"
    if code == 24:
        return WARN, "rsync exit 24: some source files vanished during transfer (normal on live systems)"
    return FAIL, f"rsync exit {code}: treat as a failed run (see 'man rsync', EXIT VALUES)"


def fresh_checked(a) -> tuple[int, str]:
    try:
        return freshness(a.folder, a.hours, a.marker)
    except OSError as e:
        return FAIL, str(e)


def cmd_manifest(a) -> int:
    n = build_manifest(a.folder)
    print(f"wrote {a.folder / MANIFEST} ({n} files)")
    return OK


def cmd_verify(a) -> int:
    verdict, problems = verify(a.folder)
    for p in problems:
        print(p)
    print(f"verify: {NAMES[verdict]}")
    return verdict


def cmd_freshness(a) -> int:
    verdict, msg = fresh_checked(a)
    if a.rsync_exit is not None:
        rv, rmsg = rsync_verdict(a.rsync_exit)
        print(f"{NAMES[rv]}: {rmsg}")
        verdict = max(verdict, rv)
    print(f"{NAMES[verdict]}: {msg}")
    if verdict == FAIL:
        print("BACKUP STALE OR FAILED", file=sys.stderr)
    return verdict


def cmd_report(a) -> int:
    rows = []
    if (a.folder / MANIFEST).is_file():
        v, problems = verify(a.folder)
        rows.append(("checksums", v, f"{len(problems)} problem(s)" if problems else "all files match"))
        rows += [("", v, p) for p in problems[:5]]
    else:
        rows.append(("checksums", WARN, "no manifest yet"))
    v, msg = fresh_checked(a)
    rows.append(("freshness", v, msg))
    if a.rsync_exit is not None:
        v, msg = rsync_verdict(a.rsync_exit)
        rows.append(("last rsync", v, msg))
    overall = max(r[1] for r in rows)
    try:
        count = str(len(list_files(a.folder)))
    except OSError:
        count = "unknown"
    print(f"Backup status for {a.folder}  [{time.strftime('%Y-%m-%d %H:%M')}]")
    print("-" * 60)
    print(f"files: {count}")
    for name, v, msg in rows:
        print(f"{name:<10} {NAMES[v]:<5} {msg}")
    print("-" * 60)
    print(f"OVERALL: {NAMES[overall]}")
    return overall


def positive_hours(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"--hours must be a finite number > 0, got {text!r}")
    return value


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Verify a backup folder. Exit 0 ok / 1 warn / 2 fail.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, helptext in [
        ("manifest", cmd_manifest, "write a SHA-256 manifest"),
        ("verify", cmd_verify, "check files against the manifest"),
        ("freshness", cmd_freshness, "fail if newest file is too old"),
        ("report", cmd_report, "one-screen status of everything"),
    ]:
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("folder", type=Path)
        if name in ("freshness", "report"):
            sp.add_argument("--hours", type=positive_hours, default=30, help="max age (default 30)")
            sp.add_argument("--marker", type=Path, metavar="FILE",
                            help="use this file's mtime (written by the backup job) instead of the newest file")
            sp.add_argument("--rsync-exit", type=int, metavar="CODE",
                            help="exit code of the last rsync run (0 ok, 24 warn, other fail)")
        sp.set_defaults(fn=fn)
    a = p.parse_args(argv)  # argparse errors exit with status 2 (= FAIL)
    try:
        if not a.folder.is_dir():
            raise OSError(f"not a folder: {a.folder}")
        return a.fn(a)
    except Exception as e:  # never show a traceback or exit 1 for an operational failure
        print(f"error: {e}", file=sys.stderr)
        return FAIL


if __name__ == "__main__":
    sys.exit(main())

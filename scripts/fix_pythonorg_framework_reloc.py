#!/usr/bin/env python3
"""Rewrite absolute python.org framework paths to @loader_path-relative paths."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PREFIX = "/Library/Frameworks/Python.framework/Versions/3.11"


def _is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            magic = f.read(4)
    except OSError:
        return False
    return magic in (
        b"\xcf\xfa\xed\xfe",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xfe\xed\xfa\xce",
        b"\xca\xfe\xba\xbe",
    )


def _otool_lines(*cmd: str) -> list[str]:
    r = subprocess.run(list(cmd), check=False, capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return r.stdout.splitlines()


def _deps(path: Path) -> list[str]:
    out: list[str] = []
    for line in _otool_lines("otool", "-L", str(path)):
        line = line.strip()
        if not line.startswith(PREFIX):
            continue
        tok = line.split()[0]
        if tok.startswith(PREFIX):
            out.append(tok)
    return out


def _dylib_id(path: Path) -> str | None:
    for line in _otool_lines("otool", "-D", str(path)):
        s = line.strip()
        if s.startswith(PREFIX):
            return s.split()[0]
    return None


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: fix_pythonorg_framework_reloc.py /path/to/Versions/3.11", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    if Path(f"{PREFIX}/Python").is_file():
        return 0
    if not (root / "Python").is_file():
        print(f"not a framework version dir: {root}", file=sys.stderr)
        return 1
    if not shutil.which("install_name_tool"):
        print("install_name_tool not found", file=sys.stderr)
        return 1

    touched: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda p: str(p)):
        if not path.is_file() or not _is_macho(path):
            continue
        dep_map: dict[str, str] = {}
        for old in _deps(path):
            rest = old[len(PREFIX) :].lstrip("/")
            dest = root / rest
            if not dest.is_file():
                continue
            rel = os.path.relpath(dest, path.parent)
            new = "@loader_path/" + rel
            if new != old:
                dep_map[old] = new
        id_old = _dylib_id(path)
        id_new: str | None = None
        if id_old and id_old.startswith(PREFIX):
            rest = id_old[len(PREFIX) :].lstrip("/")
            dest = root / rest
            if dest.is_file():
                rel = os.path.relpath(dest, path.parent)
                cand = "@loader_path/" + rel
                if cand != id_old:
                    id_new = cand
        if not dep_map and id_new is None:
            continue
        if id_new is not None:
            subprocess.run(["install_name_tool", "-id", id_new, str(path)], check=True)
        for old, new in dep_map.items():
            subprocess.run(["install_name_tool", "-change", old, new, str(path)], check=True)
        touched.append(path)

    if touched:
        print(
            f"fix_pythonorg_framework_reloc: rewrote {len(touched)} Mach-O files under {root}",
            file=sys.stderr,
        )
        codesign = shutil.which("codesign")
        if codesign:
            for p in touched:
                subprocess.run(
                    [codesign, "--force", "-s", "-", str(p)],
                    check=False,
                    capture_output=True,
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Find locally installed BeamNG.drive copies and convert their levels.

This is the front door to `tools/steam-level.py`. It exists because a level
conversion needs three things that are easy to get wrong by hand: which
installs exist on this machine, which levels each one has, and which level the
game should boot into afterwards.

    python tools/gather-content.py --list
    python tools/gather-content.py --all
    python tools/gather-content.py --level gridmap_v2 --level smallgrid
    python tools/gather-content.py --all --start west_coast_usa

Installs are discovered from, in order of precedence:

  1. every `--install PATH` given on the command line
  2. `$BEAMNG_DIR`
  3. Steam's own library list (`steamapps/libraryfolders.vdf`), read from the
     Steam root found in the registry and from the usual install locations
  4. `<drive>/SteamLibrary/steamapps/common/BeamNG.drive` on every drive

Two eras of content are recognised. A modern install keeps zipped levels under
`content/levels/` and is what `steam-level.py` converts. A 2013-era build
(BeamNG 0.1) keeps Torque3D-native `levels/<name>/<name>.mis` trees instead;
those are already in this engine's format and are only reported, not converted.

WHAT THIS WRITES, AND WHAT IT MAY NOT DO

Everything it produces embeds BeamNG's licensed terrain, meshes and materials,
so it lands in the git-ignored `game-files/assets/` and must never be committed
or deployed. `--list` writes nothing at all. The licence clauses that require
this are quoted in docs/findings/beamng-redistribution-policy.md: the EULA
forbids distributing the Software "or part of it", and the modding guidelines
forbid using BeamNG's copyrighted content. Converting a copy you own, for your
own machine, is the use the EULA explicitly carves out.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import string
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CONVERTER = HERE / "steam-level.py"
LINK_SCRIPT = REPO / "scripts" / "link-game-files.cmd"
OUT_DIR = REPO / "game-files" / "assets"

INSTALL_RELATIVE = Path("steamapps") / "common" / "BeamNG.drive"

# Loaded rather than shelled out to for its pure helpers. The module only
# defines constants and functions at import time, so this is safe.
_spec = importlib.util.spec_from_file_location("steam_level", CONVERTER)
if _spec is None or _spec.loader is None:  # pragma: no cover - layout error
    sys.exit(f"error: cannot load {CONVERTER}")
steam_level = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(steam_level)


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

def steam_roots() -> list[Path]:
    """Steam install roots, from the registry and the usual locations."""
    roots: list[Path] = []

    try:
        import winreg  # Windows only
    except ImportError:
        winreg = None

    if winreg is not None:
        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        ):
            for value in ("SteamPath", "InstallPath"):
                try:
                    with winreg.OpenKey(hive, key) as handle:
                        path, _ = winreg.QueryValueEx(handle, value)
                except OSError:
                    continue
                if path:
                    roots.append(Path(path))

    for candidate in (
        Path(r"C:/Program Files (x86)/Steam"),
        Path(r"C:/Program Files/Steam"),
        Path.home() / ".steam" / "steam",
        Path.home() / ".local" / "share" / "Steam",
    ):
        roots.append(candidate)

    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def steam_libraries() -> list[Path]:
    """Every Steam library folder, i.e. each `steamapps` parent."""
    libraries: list[Path] = []

    for root in steam_roots():
        if not root.is_dir():
            continue
        libraries.append(root)

        vdf = root / "steamapps" / "libraryfolders.vdf"
        if not vdf.is_file():
            continue
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Two shapes exist: `"path" "D:\\SteamLibrary"` in current clients, and
        # a bare `"1" "D:\\SteamLibrary"` in older ones. Matching both quoted
        # strings that look like paths covers either without a VDF parser.
        for value in re.findall(r'"([^"]*[\\/][^"]*)"', text):
            candidate = Path(value.replace("\\\\", "\\"))
            if candidate.is_dir():
                libraries.append(candidate)

    # A library can also sit somewhere Steam has never been told about.
    for letter in string.ascii_uppercase:
        for relative in ("SteamLibrary", "Steam", "Games/SteamLibrary"):
            candidate = Path(f"{letter}:/") / relative
            if (candidate / "steamapps").is_dir():
                libraries.append(candidate)

    seen: set[str] = set()
    unique: list[Path] = []
    for library in libraries:
        key = str(library).lower()
        if key not in seen:
            seen.add(key)
            unique.append(library)
    return unique


def candidate_installs(explicit: list[str]) -> list[Path]:
    """BeamNG.drive install directories, in precedence order."""
    found: list[Path] = []

    for value in explicit:
        found.append(Path(value))
    if os.environ.get("BEAMNG_DIR"):
        found.append(Path(os.environ["BEAMNG_DIR"]))
    for library in steam_libraries():
        found.append(library / INSTALL_RELATIVE)

    seen: set[str] = set()
    unique: list[Path] = []
    for install in found:
        if not install.is_dir():
            continue
        key = str(install).lower()
        if key not in seen:
            seen.add(key)
            unique.append(install)
    return unique


# ---------------------------------------------------------------------------
# what each install contains
# ---------------------------------------------------------------------------

def modern_levels(install: Path) -> dict[str, int]:
    """`content/levels/*.zip` -> size in bytes. The convertible era."""
    levels: dict[str, int] = {}
    directory = install / "content" / "levels"
    if not directory.is_dir():
        return levels
    for zip_path in sorted(directory.glob("*.zip")):
        try:
            levels[zip_path.stem] = zip_path.stat().st_size
        except OSError:
            continue
    return levels


def legacy_levels(install: Path) -> list[str]:
    """`levels/<name>/<name>.mis` -> names. The 2013, Torque3D-native era.

    Already in this engine's format, so they are reported but not converted.
    """
    names: list[str] = []
    directory = install / "levels"
    if not directory.is_dir():
        return names
    for child in sorted(directory.iterdir()):
        if child.is_dir() and (child / f"{child.name}.mis").is_file():
            names.append(child.name)
    return names


def converted_levels() -> set[str]:
    """Level ids already written to game-files/assets/<module>/levels/."""
    done: set[str] = set()
    if not OUT_DIR.is_dir():
        return done
    for module_dir in OUT_DIR.iterdir():
        levels_dir = module_dir / "levels"
        if not levels_dir.is_dir():
            continue
        for mis in levels_dir.glob("*.mis"):
            done.add(mis.stem)
    return done


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def report(installs: list[tuple[Path, dict[str, int], list[str]]]) -> None:
    done = converted_levels()

    if not installs:
        print("No BeamNG.drive install found.")
        print()
        print("Point at one explicitly:")
        print("  python tools/gather-content.py --install \"D:/path/to/BeamNG.drive\" --list")
        return

    for install, modern, legacy in installs:
        print(f"{install}")
        if modern:
            total = sum(modern.values())
            print(f"  content/levels/  {len(modern)} levels, {human(total)}")
            width = max(len(name) for name in modern)
            for name, size in modern.items():
                level_id = steam_level.level_id_for(name)
                mark = "converted" if level_id in done else "          "
                print(f"    {name:<{width}}  {human(size):>9}  {mark}")
        else:
            print("  content/levels/  none")
        if legacy:
            print(f"  levels/          {len(legacy)} Torque3D-native, not converted:")
            print(f"    {', '.join(legacy)}")
        print()

    if done:
        print(f"{len(done)} level(s) already converted in "
              f"{OUT_DIR.relative_to(REPO)}")


# ---------------------------------------------------------------------------
# converting
# ---------------------------------------------------------------------------

def convert(level: str, install: Path, args) -> bool:
    """Run one conversion through the converter's own command line."""
    command = [sys.executable, str(CONVERTER), level, "--steam", str(install)]
    if args.autoclose is not None:
        command += ["--autoclose", f"{args.autoclose:g}"]
    if args.no_autostart:
        command += ["--no-autostart"]

    print(f"== converting {level} from {install}")
    result = subprocess.run(command, cwd=REPO)
    if result.returncode != 0:
        print(f"error: conversion of {level} failed "
              f"(exit {result.returncode})", file=sys.stderr)
        return False
    return True


def relink() -> None:
    """Re-point the junction at game-files/assets after writing."""
    if os.name != "nt":
        print("note: not Windows; run scripts/link-game-files.cmd yourself, "
              "or point the engine at game-files/assets")
        return
    print("== re-linking the converted content into the game tree")
    subprocess.run(["cmd", "/c", str(LINK_SCRIPT)], cwd=REPO)


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--install", action="append", default=[], metavar="PATH",
                        help="a BeamNG.drive install to use; repeatable, and "
                             "takes precedence over auto-detection")
    parser.add_argument("--level", action="append", default=[], metavar="NAME",
                        help="convert this level; repeatable. Use --list for "
                             "names")
    parser.add_argument("--all", action="store_true",
                        help="convert every level in every install found")
    parser.add_argument("--start", metavar="NAME",
                        help="level the game should boot into. Converted last, "
                             "because the most recently converted level is the "
                             "one the generated module starts")
    parser.add_argument("--list", action="store_true",
                        help="report what is installed and what is already "
                             "converted, then stop. Writes nothing")
    parser.add_argument("--autoclose", type=float, default=None, metavar="SECONDS",
                        help="passed through to the converter; 0 disables")
    parser.add_argument("--no-autostart", action="store_true",
                        help="passed through: leave the game menu-driven")
    args = parser.parse_args()

    if not CONVERTER.is_file():
        print(f"error: {CONVERTER} is missing", file=sys.stderr)
        return 2

    installs = candidate_installs(args.install)
    inventory = [(path, modern_levels(path), legacy_levels(path))
                 for path in installs]

    if args.list or not (args.level or args.all or args.start):
        report(inventory)
        if not (args.level or args.all or args.start):
            print()
            print("Nothing to do. Add --all or --level NAME to convert.")
        return 0

    if not inventory:
        print("error: no BeamNG.drive install found; see --list", file=sys.stderr)
        return 2

    # First install that has the level wins, so an explicit --install shadows
    # an auto-detected copy without needing extra flags.
    def locate(level: str) -> Path | None:
        for path, modern, _ in inventory:
            if level in modern:
                return path
        return None

    if args.all:
        wanted = [name for _, modern, _ in inventory for name in modern]
    else:
        wanted = list(args.level)

    if args.start and args.start not in wanted:
        wanted.append(args.start)
    elif args.start:
        # Converted last on purpose: the generated module boots the level that
        # was converted most recently.
        wanted.remove(args.start)
        wanted.append(args.start)

    if not wanted:
        print("error: no levels selected", file=sys.stderr)
        return 2

    converted = 0
    for level in wanted:
        install = locate(level)
        if install is None:
            print(f"warning: '{level}' is not in any install found; skipping",
                  file=sys.stderr)
            continue
        if convert(level, install, args):
            converted += 1

    print()
    if converted:
        relink()
        print(f"== {converted} level(s) converted into "
              f"{OUT_DIR.relative_to(REPO)}")
        print("   BeamNG content: never commit it, never deploy it.")
    else:
        print("== nothing converted")
    return 0 if converted else 1


if __name__ == "__main__":
    sys.exit(main())

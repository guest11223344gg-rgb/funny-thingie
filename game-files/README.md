# game-files/

Converted game content. **This directory is a build artefact, not source.**

Everything under `assets/` is produced by `tools/gather-content.py` and
`tools/steam-level.py` from a BeamNG.drive installation the user already owns
locally. It embeds BeamNG's licensed terrain, meshes, materials and sky, so it
is **never committed and never deployed** — see
[`docs/findings/beamng-redistribution-policy.md`](../docs/findings/beamng-redistribution-policy.md)
for the licence clauses that require this.

## How that is enforced

A rule that says "do not commit this" is only as good as the moment someone is
tired and runs `git add -A`. `.gitignore` therefore carries two independent
layers:

1. **The directories conversion writes to** — `assets/`, `game-files/*` (with
   `README.md` re-included), and `content/`, in case a level zip is ever
   unpacked inside the tree.
2. **BeamNG's own file formats** — `*.ter`, `*.materials.json`,
   `*.terrain.json`, `*.forestbrushes.json`, `*.cdae`, `*.tsmesh`, `*.prefab`,
   `*.jbeam`, `*.pc`, `items.level.json`. These do not appear in this repository
   legitimately, so they are ignored **wherever they land**, which catches a
   stray copy outside the directories above.

Note that `.gitignore` has no trailing comments — a `#` after a pattern becomes
part of the pattern — so the comments in that file are all on their own lines.

## Why it is not inside `third_party/`

It used to be, at
`third_party/Torque3D/My Projects/BaseGame/game/data/BeamNGMaps/`. That was
wrong for two reasons:

1. `third_party/Torque3D` is fetched by `scripts/fetch-torque3d.sh` and treated
   as a disposable checkout. A re-clone would silently delete ~280 MB of
   conversion work.
2. It is git-ignored wholesale, so nothing recorded that the content had been
   generated at all.

Keeping the output at the repository root makes it obvious that it is ours to
delete and regenerate, and it is a single command to do so.

## Regenerating

`tools/gather-content.py` is the front door. It finds the BeamNG.drive copies
installed on this machine — Steam's library folders, `$BEAMNG_DIR`, and any
`--install` you pass — and converts levels out of them.

```
scripts/build.sh gather --list                       # what is available; writes nothing
scripts/build.sh gather --all                        # convert every level found
scripts/build.sh gather --level gridmap_v2           # one level
scripts/build.sh gather --all --start west_coast_usa # ...and boot into this one
```

A single level can also be converted directly, without the discovery step:

```
python tools/steam-level.py gridmap_v2
```

Both routes write here, and the level the game boots into is whichever was
converted **most recently** — that is what `--start` exists to control.

The converter defaults to booting straight into the level and quitting after 60
seconds, so an unattended run cannot hang. For normal play, pass
`--no-autostart --autoclose 0`.

## Making it visible to the engine

The engine cannot be pointed at this directory. `Platform::FS::getAssetDir()`
(`Engine/source/platformWin32/winVolume.cpp:742`) returns the directory holding
the executable, and `platformVolume.cpp:47` mounts that as `game:` — every
relative path in `main.tscript` (`core`, `data`, `tools`) resolves against it.
The module must additionally be reachable as `data/<module>` for
`ModuleDatabase.scanModules("data", false)` to find it.

So a directory junction bridges the two:

```
scripts\link-game-files.cmd
```

That script is idempotent and safe to re-run; run it again after any re-fetch of
`third_party/Torque3D`, which would otherwise leave the link missing. It refuses
to touch the link path if a real directory is found there.

## Layout

```
game-files/
  README.md                 tracked — this file
  assets/                   ignored — all of it is BeamNG-derived
    BeamNGMaps/
      BeamNGMaps.module     module definition
      BeamNGMaps.tscript    module lifecycle script + the boot/quit timers
      levels/
        SteamGridMap.mis        terrain only
        SteamGridmapV2.mis      terrain, props, sky (the default boot level)
        SteamSmallgrid.mis      terrain only
        SteamAutotest.mis       terrain only
        <LevelId>/              the .ter and copied .dae meshes for each
```

# game-files/

Converted game content. **This directory is a build artefact, not source.**

Everything under `assets/` is produced by `tools/steam-level.py` from a
BeamNG.drive installation the user already owns locally. It embeds BeamNG's
licensed terrain, meshes, materials and sky, so it is **never committed and
never deployed** — see
[`docs/findings/beamng-redistribution-policy.md`](../docs/findings/beamng-redistribution-policy.md)
for the licence clauses that require this.

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

```
python tools/steam-level.py gridmap_v2          # a level from the local install
```

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
      BeamNGMaps.tscript    module lifecycle script
      levels/
        SteamGridMap/       terrain only
        SteamGridmapV2/     terrain, props, sky
```

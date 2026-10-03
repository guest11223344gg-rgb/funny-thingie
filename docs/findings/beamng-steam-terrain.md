# Modern BeamNG.drive levels: what the terrain costs

**Question.** Can this engine load a map from a current Steam install of
BeamNG.drive, rather than only from the 2013-era BeamNG 0.1 build?

**Short answer.** The *ground surface* loads directly, with one byte of
engine change. Nothing else in a modern level does — props, roads, materials and
vehicles are BeamNG's own formats and would each need a converter.

This document records the measurements behind that answer. It is an M2-scope
spike; nothing here is wired into the build beyond the terrain patch and
`tools/steam-level.py`.

---

## The two eras of BeamNG content

BeamNG.drive 0.1 (2013) is a Torque3D 3.5 game. Its levels are Torque3D levels:

```
levels/dry_rock_island/dry_rock_island.mis      TorqueScript mission
levels/dry_rock_island/dry_rock_island.ter      TerrainBlock terrain
levels/dry_rock_island/dry_rock_island.forest   Forest
levels/GridMap/art/shapes/buildings/*.dae       COLLADA meshes
```

A modern Steam level is a zip of BeamNG's own format:

```
levels/gridmap_v2/theTerrain.ter                terrain      <- the one survivor
levels/gridmap_v2/theTerrain.terrain.json       terrain metadata
levels/gridmap_v2/map.json, info.json           scene description
levels/gridmap_v2/main.materials.json           JSON material system
levels/gridmap_v2/art/Prefabs/*.prefab          BeamNG prefab scenes
levels/gridmap_v2/art/**/*.cdae, *.tsmesh       BeamNG meshes
```

Only the `.ter` is shared.

## Finding: BeamNG's terrain version 9 *is* Torque3D's version 7

`TerrainFile::load()` (`Engine/source/terrain/terrFile.cpp`) reads a version
byte and rejects anything above `FILE_VERSION`, which upstream sets to 7. A
modern BeamNG terrain is stamped **9**.

But version 9 uses the version 7 binary layout exactly. Measured, byte for byte,
across five stock Steam levels:

| level | `.ter` bytes | declared size | version 7 layout | material names | trailing |
| --- | --- | --- | --- | --- | --- |
| `GridMap` | 3,145,800 | 1024 | 3,145,737 | 63 | 0 |
| `template` | 3,145,775 | 1024 | 3,145,737 | 38 | 0 |
| `gridmap_v2` | 12,582,975 | 2048 | 12,582,921 | 54 | 0 |
| `Utah` | 12,583,057 | 2048 | 12,582,921 | 136 | 0 |
| `east_coast_usa` | 12,583,053 | 2048 | 12,582,921 | 132 | 0 |

"version 7 layout" is `1 + 4 + size²·2 + size² + 4` bytes: version, size, a
`U16` height map, a `U8` layer-index map, and the material-name count. Every
file is that size plus its length-prefixed material names, with **no trailing
bytes**. The material names read back correctly:

```
gridmap_v2:  Grass, Grass2, Mud, Dirt, Asphalt, Rock, Concrete, BeachSand
GridMap:     Asphalt, RockyDirt, Grass, Rock, Mud, BeachSand, Ice, asphalt_prepped
```

The same probe on the 2013 build returns version **7**:

| source | level | version byte |
| --- | --- | --- |
| BeamNG 0.1 | `gridmap.ter` | 7 |
| BeamNG 0.1 | `dry_rock_island.ter` | 7 |
| BeamNG 0.1 | `Industrial.ter` | 7 |
| Steam | `GridMap.ter` | **9** |

So the format has been stable for the twelve years between those builds. The
version number moved; the layout did not.

**Caveat.** The terrain's `.terrain.json` sidecar advertises a
`layerTextureMap` field between the layer map and the material names:

```json
"binaryFormat": "version(char), size(unsigned int), heightMap(...), layerMap(...), layerTextureMap(...), materialNames"
```

No stock file we measured actually contains one — the sizes above prove the
bytes are not there. If a future revision adds it, the four bytes we read as the
material count become texture data. The patch guards against that rather than
trusting the layout blindly.

## The patch

`patches/torque3d/0002-terrain-accept-beamng-v8-v9.patch`:

- `terrFile.h` — adds `BEAMNG_FILE_VERSION = 9` alongside `FILE_VERSION = 7`.
- `terrFile.cpp` `load()` — accepts up to `BEAMNG_FILE_VERSION`.
- `terrFile.cpp` `_load()` — refuses an implausible material count (> 1024) by
  falling back to the warning material instead of allocating it, and warns if
  the version 7 layout did not consume the file exactly.

It is applied by `scripts/apply-patches.sh`, which `scripts/build.sh native` and
`scripts/build.sh web` both run.

## What still does not load

| asset | format | status |
| --- | --- | --- |
| Terrain | `.ter`, version 9 | **loads** with patch 0002 |
| Sky, sun, fog | `SkyBox`/`Sun`/`LevelInfo` in a `Scene` | authored by the generator |
| Props, buildings, roads | `.prefab` + `.cdae`/`.tsmesh` | not converted |
| Materials | BeamNG `*.materials.json` | not converted; terrain layers fall back to the warning material |
| Forest / vegetation | `main.forestbrushes*.json` | not converted |
| Vehicles | `.pc` / `.jbeam` | out of scope here |

## Producing a level

```bash
python tools/steam-level.py GridMap
python tools/steam-level.py --steam "D:/SteamLibrary/steamapps/common/BeamNG.drive" Utah
```

The tool reads the level zip, extracts the `.ter`, measures its height range to
place the block so its lowest point sits at z = 0 with the camera spawn above
its highest point, and writes a self-contained BaseGame module under
`data/BeamNGMaps/`:

```
data/BeamNGMaps/BeamNGMaps.module
data/BeamNGMaps/BeamNGMaps.tscript
data/BeamNGMaps/levels/<LevelId>.asset.taml          LevelAsset
data/BeamNGMaps/levels/<LevelId>.mis                 Scene + TerrainBlock
data/BeamNGMaps/levels/<LevelId>/<terrain>.ter       the BeamNG terrain
data/BeamNGMaps/levels/<LevelId>/<LevelId>Terrain.asset.taml
```

`BeamNGMaps/` is written into the game directory, which is git-ignored, so no
BeamNG content enters the repository. The level appears in the level list as
`<name> (Steam)`.

## Legal

Unchanged from the README: this is a personal project, BeamNG content is read
from a locally installed, purchased copy, and none of it is committed.

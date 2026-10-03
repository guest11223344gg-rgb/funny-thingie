#!/usr/bin/env python3
"""Generate a BaseGame level that loads a stock BeamNG.drive level's terrain.

A modern BeamNG.drive level ships as a zip under `content/levels/`. Almost all
of it is BeamNG's own format -- `.prefab` scenes, a JSON material system,
`.cdae`/`.tsmesh` meshes -- and none of that is converted here.

The one exception is the terrain. BeamNG stamps its `.ter` files with version 8
and 9 while keeping the version 7 binary layout that Torque3D reads (see
`patches/torque3d/0002-terrain-accept-beamng-v8-v9.patch`). So the drivable
ground surface of any stock Steam map loads as-is; this tool extracts it and
writes the small amount of Torque3D scaffolding needed to put it in the level
list:

    data/<module>/<module>.module
    data/<module>/<module>.tscript
    data/<module>/levels/<LevelId>.asset.taml          LevelAsset
    data/<module>/levels/<LevelId>.mis                 Scene + TerrainBlock
    data/<module>/levels/<LevelId>/<terrain>.ter       the BeamNG terrain
    data/<module>/levels/<LevelId>/<LevelId>Terrain.asset.taml

Terrain materials are not converted. BeamNG names its layers ("Grass", "Asphalt"
...) and Torque3D resolves an unknown name to its warning material, so the
terrain renders with the warning texture. The geometry, and therefore the map's
shape, is correct.

Usage:
    python tools/steam-level.py GridMap
    python tools/steam-level.py --steam "D:/SteamLibrary/steamapps/common/BeamNG.drive" Utah
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import zipfile
from pathlib import Path

DEFAULT_STEAM = "D:/SteamLibrary/steamapps/common/BeamNG.drive"
DEFAULT_GAME = "third_party/Torque3D/My Projects/BaseGame/game"
DEFAULT_MODULE = "BeamNGMaps"

# BeamNG's terrain height is 11.5 fixed point, same as Torque3D's.
FIXED_POINT_SCALE = 32.0


class TerrainError(Exception):
    pass


def read_terrain(blob: bytes) -> dict:
    """Parse a BeamNG/Torque3D `.ter` header, height range and material list."""
    if len(blob) < 5:
        raise TerrainError("terrain file is shorter than its header")

    version = blob[0]
    (size,) = struct.unpack_from("<I", blob, 1)
    if size == 0 or (size & (size - 1)) != 0:
        raise TerrainError(f"terrain size {size} is not a power of two")

    samples = size * size
    height_end = 5 + samples * 2
    layer_end = height_end + samples
    if len(blob) < layer_end + 4:
        raise TerrainError(
            f"terrain file is {len(blob)} bytes but a {size}x{size} heightmap "
            f"plus layer map needs at least {layer_end + 4}"
        )

    heights = struct.unpack_from(f"<{samples}H", blob, 5)

    (material_count,) = struct.unpack_from("<I", blob, layer_end)
    offset = layer_end + 4
    materials: list[str] = []
    for _ in range(material_count):
        if offset >= len(blob):
            raise TerrainError("terrain material list runs past end of file")
        (length,) = struct.unpack_from("<B", blob, offset)
        offset += 1
        materials.append(blob[offset:offset + length].decode("latin-1"))
        offset += length

    trailing = len(blob) - offset

    return {
        "version": version,
        "size": size,
        "min_height": min(heights) / FIXED_POINT_SCALE,
        "max_height": max(heights) / FIXED_POINT_SCALE,
        "materials": materials,
        "trailing": trailing,
    }


def find_level_zip(steam: Path, level: str) -> Path:
    levels_dir = steam / "content" / "levels"
    if not levels_dir.is_dir():
        raise TerrainError(f"no levels directory at {levels_dir}")

    wanted = level.lower()
    for entry in sorted(levels_dir.glob("*.zip")):
        if entry.stem.lower() == wanted:
            return entry

    available = ", ".join(sorted(p.stem for p in levels_dir.glob("*.zip")))
    raise TerrainError(f"no level named '{level}' in {levels_dir}\navailable: {available}")


def pick_terrain(archive: zipfile.ZipFile, level: str) -> tuple[str, dict | None]:
    """Return the terrain entry name and its JSON sidecar, if there is one."""
    sidecar_name = None
    for name in archive.namelist():
        if name.lower().endswith(".terrain.json"):
            sidecar_name = name
            break

    sidecar = None
    if sidecar_name:
        try:
            sidecar = json.loads(archive.read(sidecar_name).decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            sidecar = None

    if sidecar and sidecar.get("datafile"):
        # e.g. "/levels/gridmap_v2/theTerrain.ter"
        wanted = sidecar["datafile"].lstrip("/").lower()
        for name in archive.namelist():
            if name.lower() == wanted:
                return name, sidecar
        for name in archive.namelist():
            if name.lower().endswith(wanted.split("/")[-1]):
                return name, sidecar

    # Fall back to the largest .ter in the archive.
    ters = [n for n in archive.namelist() if n.lower().endswith(".ter")]
    if not ters:
        raise TerrainError(f"no .ter terrain file inside the '{level}' archive")
    return max(ters, key=lambda n: archive.getinfo(n).file_size), sidecar


def level_id_for(stem: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", stem) if w]
    return "Steam" + "".join(w[:1].upper() + w[1:] for w in words)


def write_module(module_dir: Path, module: str) -> None:
    module_dir.mkdir(parents=True, exist_ok=True)

    module_file = module_dir / f"{module}.module"
    module_file.write_text(
        f"""<ModuleDefinition
    ModuleId="{module}"
    VersionId="1"
    Group="Game"
    scriptFile="{module}.tscript"
    CreateFunction="onCreate"
    DestroyFunction="onDestroy">
    <DeclaredAssets
        Extension="asset.taml"
        Recurse="true"/>
</ModuleDefinition>
""",
        encoding="utf-8",
    )

    script_file = module_dir / f"{module}.tscript"
    script_file.write_text(
        f"""// Levels generated by tools/steam-level.py. See that script for what is
// and is not converted from a stock BeamNG.drive level.
function {module}::onCreate(%this)
{{
}}

function {module}::onDestroy(%this)
{{
}}
""",
        encoding="utf-8",
    )


def write_level_asset(path: Path, level_id: str, level_name: str) -> None:
    path.write_text(
        f"""<LevelAsset
    AssetName="{level_id}"
    AssetDescription="Ground surface lifted from the stock BeamNG.drive level '{level_name}'. Terrain only -- no props, roads or vehicles."
    LevelFile="@assetFile={level_id}.mis"
    LevelName="{level_name} (Steam)"
    gameModesNames="ExampleGameMode"
    VersionId="1"/>
""",
        encoding="utf-8",
    )


def write_terrain_asset(path: Path, asset_name: str, terrain_file: str) -> None:
    path.write_text(
        f"""<TerrainAsset
    AssetName="{asset_name}"
    terrainFile="@assetFile={terrain_file}"
    VersionId="1"/>
""",
        encoding="utf-8",
    )


def write_mission(path: Path, level_id: str, terrain_asset: str, terrain: dict) -> None:
    size = terrain["size"]
    half = size // 2
    # Place the terrain so its lowest point sits at z = 0 and the camera spawns
    # above its highest point.
    base_z = -terrain["min_height"]
    spawn_z = (terrain["max_height"] - terrain["min_height"]) + 25.0

    path.write_text(
        f"""//--- OBJECT WRITE BEGIN ---
new Scene({level_id}) {{
   isEditing = "0";
   gameModes = "ExampleGameMode";
      enabled = "1";

   new LevelInfo(theLevelInfo) {{
      FogColor = "0.6 0.6 0.7 1";
      fogDensityOffset = "700";
      canvasClearColor = "0 0 0 255";
      ambientLightBlendCurve = "2.69146e+20 0";
      soundAmbience = "AudioAmbienceDefault";
         enabled = "1";
   }};
   new SkyBox(theSky) {{
      MaterialAsset = "Core_Rendering:BlankSkyMat";
         dirtyGameObject = "0";
   }};
   new Sun(theSun) {{
      azimuth = "230.396";
      elevation = "45";
      color = "0.968628 0.901961 0.901961 1";
      ambient = "0.337255 0.533333 0.619608 1";
      texSize = "2048";
      overDarkFactor = "3000 1500 750 250";
      shadowDistance = "200";
      shadowSoftness = "0.25";
      logWeight = "0.9";
      fadeStartDistance = "0";
         bias = "0.1";
         Blur = "1";
         dirtyGameObject = "0";
         dynamicRefreshFreq = "8";
         enabled = "1";
         height = "1024";
         lightBleedFactor = "0.8";
         minVariance = "0";
         pointShadowType = "PointShadowType_Paraboloid";
         shadowBox = "-100 -100 -100 100 100 100";
         splitFadeDistances = "1 1 1 1";
         staticRefreshFreq = "250";
         width = "3072";
   }};
   new TerrainBlock({level_id}Terrain) {{
      terrainAsset = "{terrain_asset}";
      castShadows = "1";
      squareSize = "1";
      baseTexSize = "1024";
      baseTexFormat = "PNG";
      lightMapSize = "256";
      screenError = "16";
      position = "-{half} -{half} {base_z:.4f}";
      rotation = "1 0 0 0";
   }};
   new SimGroup(CameraSpawnPoints) {{
         enabled = "1";

      new SpawnSphere(DefaultCameraSpawnSphere) {{
         radius = "1";
         sphereWeight = "1";
         indoorWeight = "1";
         outdoorWeight = "1";
         dataBlock = "SpawnSphereMarker";
         position = "0 0 {spawn_z:.4f}";
            enabled = "1";
            homingCount = "0";
            lockCount = "0";
      }};
   }};
}};
//--- OBJECT WRITE END ---
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("level", help="level name, matching content/levels/<name>.zip (case-insensitive)")
    parser.add_argument("--steam", default=os.environ.get("BEAMNG_DIR", DEFAULT_STEAM),
                        help=f"BeamNG.drive install directory (default: {DEFAULT_STEAM})")
    parser.add_argument("--game", default=DEFAULT_GAME,
                        help=f"BaseGame 'game' directory (default: {DEFAULT_GAME})")
    parser.add_argument("--module", default=DEFAULT_MODULE,
                        help=f"module to write the level into (default: {DEFAULT_MODULE})")
    args = parser.parse_args()

    steam = Path(args.steam)
    game = Path(args.game)

    if not (game / "main.tscript").is_file():
        print(f"error: {game} does not look like a BaseGame 'game' directory", file=sys.stderr)
        return 2

    try:
        zip_path = find_level_zip(steam, args.level)
        with zipfile.ZipFile(zip_path) as archive:
            terrain_entry, sidecar = pick_terrain(archive, args.level)
            terrain_blob = archive.read(terrain_entry)
    except (TerrainError, zipfile.BadZipFile, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        terrain = read_terrain(terrain_blob)
    except TerrainError as exc:
        print(f"error: {terrain_entry}: {exc}", file=sys.stderr)
        return 2

    level_id = level_id_for(zip_path.stem)
    terrain_file = Path(terrain_entry).name
    terrain_asset = f"{args.module}:{level_id}Terrain"

    module_dir = game / "data" / args.module
    levels_dir = module_dir / "levels"
    level_dir = levels_dir / level_id

    write_module(module_dir, args.module)
    level_dir.mkdir(parents=True, exist_ok=True)
    (level_dir / terrain_file).write_bytes(terrain_blob)
    write_terrain_asset(level_dir / f"{level_id}Terrain.asset.taml", f"{level_id}Terrain", terrain_file)
    write_mission(levels_dir / f"{level_id}.mis", level_id, terrain_asset, terrain)
    write_level_asset(levels_dir / f"{level_id}.asset.taml", level_id, zip_path.stem)

    print(f"level      {args.level}  <- {zip_path}")
    print(f"terrain    {terrain_entry}  ({len(terrain_blob):,} bytes)")
    print(f"format     version {terrain['version']}, {terrain['size']}x{terrain['size']}, "
          f"{len(terrain['materials'])} layers, {terrain['trailing']} trailing bytes")
    print(f"height     {terrain['min_height']:.1f} .. {terrain['max_height']:.1f}")
    print(f"materials  {', '.join(terrain['materials']) or '(none)'}")
    print()
    print(f"wrote {levels_dir / (level_id + '.asset.taml')}")
    print(f"      {levels_dir / (level_id + '.mis')}")
    print(f"      {level_dir / terrain_file}")
    print(f"      {level_dir / (level_id + 'Terrain.asset.taml')}")
    print()
    print(f"load it from the level list as '{zip_path.stem} (Steam)'")
    return 0


if __name__ == "__main__":
    sys.exit(main())

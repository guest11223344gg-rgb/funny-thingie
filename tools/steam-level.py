#!/usr/bin/env python3
"""Convert a stock BeamNG.drive level into a playable BaseGame level.

A modern BeamNG.drive level ships as a zip under `content/levels/`. BeamNG's
engine is a Torque3D descendant, so more of it survives than the format names
suggest. This tool converts what it can:

| BeamNG | this tool |
| --- | --- |
| `theTerrain.ter` (version 9) | loaded as-is; the layout is version 7 |
| `art/terrains/main.materials.json` | TerrainMaterial + ImageAsset per layer |
| `main/MissionGroup/**/items.level.json` | Scene objects |
| `TSStatic` | `TSStatic` (`.dae` shape) |
| `Prefab` instance | its `.prefab` expanded, transformed, inlined |
| `ScatterSky` / `LevelInfo` / `CloudLayer` | same classes |
| `DecalRoad`, `River`, `GroundCover`, `BeamNG*` | skipped |
| `.dae` meshes | copied; mesh textures are **not** converted |

BeamNG's terrain is version 9 but uses the version 7 binary layout Torque3D
reads (see `patches/torque3d/0002-terrain-accept-beamng-v8-v9.patch`).

Output goes to `game-files/assets/<module>/` at the repository root, not into
the game tree -- that tree lives under the disposable `third_party/` checkout
and is git-ignored wholesale. `scripts/link-game-files.cmd` junctions the output
back to the `data/<module>` path the engine resolves against its own executable.
The converted content embeds BeamNG's licensed terrain and meshes and must never
be committed; see `docs/findings/beamng-redistribution-policy.md`.

Usage:
    python tools/steam-level.py gridmap_v2
    python tools/steam-level.py --steam "D:/SteamLibrary/steamapps/common/BeamNG.drive" utah
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import struct
import sys
import zipfile
from pathlib import Path

DEFAULT_STEAM = "D:/SteamLibrary/steamapps/common/BeamNG.drive"
DEFAULT_GAME = "third_party/Torque3D/My Projects/BaseGame/game"
# Converted output goes to the repository root, not into the game tree. The
# game tree lives under third_party/, which is a disposable checkout that
# scripts/fetch-torque3d.sh may re-clone, and which is git-ignored wholesale.
# See game-files/README.md and docs/findings/beamng-redistribution-policy.md.
DEFAULT_OUT = "game-files/assets"
DEFAULT_MODULE = "BeamNGMaps"

# Seconds after startup at which the generated module quits the game. An
# unattended run has no way to close the window, so this is on by default; pass
# --autoclose 0 for normal play.
DEFAULT_AUTOCLOSE = 60.0

# BeamNG's terrain height is 11.5 fixed point, same as Torque3D's.
FIXED_POINT_SCALE = 32.0

# The engine drops the camera at the world origin, not at any spawn marker the
# level provides. Templates/BaseGame/game/core/clientServer/scripts/server/
# connectionToClient.tscript:167 defaults `%client.spawnLocation = "0 0 0"`, and
# no shipped module overrides it, so that is where the camera goes. The level is
# therefore re-based so the ground at the origin sits this far below it.
SPAWN_CLEARANCE = 40.0

# Scene classes we translate. Anything else is dropped.
KEPT_CLASSES = {"TSStatic", "Prefab", "ScatterSky", "LevelInfo", "CloudLayer"}


class ConvertError(Exception):
    pass


# ---------------------------------------------------------------------------
# terrain
# ---------------------------------------------------------------------------

def read_terrain(blob: bytes) -> dict:
    """Parse a BeamNG/Torque3D `.ter` header, height range and material list."""
    if len(blob) < 5:
        raise ConvertError("terrain file is shorter than its header")

    version = blob[0]
    (size,) = struct.unpack_from("<I", blob, 1)
    if size == 0 or (size & (size - 1)) != 0:
        raise ConvertError(f"terrain size {size} is not a power of two")

    samples = size * size
    height_end = 5 + samples * 2
    layer_end = height_end + samples
    if len(blob) < layer_end + 4:
        raise ConvertError(
            f"terrain file is {len(blob)} bytes but a {size}x{size} heightmap "
            f"plus layer map needs at least {layer_end + 4}"
        )

    heights = struct.unpack_from(f"<{samples}H", blob, 5)

    (material_count,) = struct.unpack_from("<I", blob, layer_end)
    offset = layer_end + 4
    materials: list[str] = []
    for _ in range(material_count):
        if offset >= len(blob):
            raise ConvertError("terrain material list runs past end of file")
        (length,) = struct.unpack_from("<B", blob, offset)
        offset += 1
        materials.append(blob[offset:offset + length].decode("latin-1"))
        offset += length

    return {
        "version": version,
        "size": size,
        "min_height": min(heights) / FIXED_POINT_SCALE,
        "max_height": max(heights) / FIXED_POINT_SCALE,
        # Height at the middle sample. The block is centred on the origin, so
        # this is the ground height at world (0, 0) -- which is exactly where
        # the engine drops the camera. Indexing the middle row and column is
        # correct whichever way round the engine reads the rows.
        "center_height": heights[(size // 2) * size + (size // 2)] / FIXED_POINT_SCALE,
        "materials": materials,
        "trailing": len(blob) - offset,
    }


# ---------------------------------------------------------------------------
# linear algebra: BeamNG stores rotations as row-major 3x3 matrices; Torque's
# `rotation` field is TypeMatrixRotation, which parses axis-angle only.
# ---------------------------------------------------------------------------

IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def mat_mul(a, b):
    return tuple(
        sum(a[i * 3 + k] * b[k * 3 + j] for k in range(3))
        for i in range(3) for j in range(3)
    )


def mat_apply(m, v):
    return tuple(sum(m[i * 3 + k] * v[k] for k in range(3)) for i in range(3))


def mat_to_axis_angle(m):
    """Row-major 3x3 -> (x, y, z, degrees), the string Torque's rotation wants."""
    trace = m[0] + m[4] + m[8]
    cos_angle = max(-1.0, min(1.0, (trace - 1.0) * 0.5))
    angle = math.acos(cos_angle)

    if angle < 1e-6:
        return (1.0, 0.0, 0.0, 0.0)

    if abs(math.pi - angle) < 1e-3:
        # 180 degrees: the skew part vanishes, recover the axis from the
        # symmetric part instead.
        x = math.sqrt(max(0.0, (m[0] + 1.0) * 0.5))
        y = math.sqrt(max(0.0, (m[4] + 1.0) * 0.5))
        z = math.sqrt(max(0.0, (m[8] + 1.0) * 0.5))
        if m[1] < 0.0:
            y = -y
        if m[2] < 0.0:
            z = -z
        norm = math.sqrt(x * x + y * y + z * z) or 1.0
        return (x / norm, y / norm, z / norm, 180.0)

    s = math.sin(angle)
    axis = ((m[7] - m[5]) / (2.0 * s),
            (m[2] - m[6]) / (2.0 * s),
            (m[3] - m[1]) / (2.0 * s))
    norm = math.sqrt(sum(c * c for c in axis)) or 1.0
    return (axis[0] / norm, axis[1] / norm, axis[2] / norm, math.degrees(angle))


def rotation_string(matrix):
    x, y, z, angle = mat_to_axis_angle(matrix or IDENTITY)
    return f"{x:.6g} {y:.6g} {z:.6g} {angle:.6g}"


def vec3(value, fallback=(0.0, 0.0, 0.0)):
    if not value:
        return fallback
    return tuple(float(c) for c in value[:3])


def torque_value(value):
    """Render a JSON value as the string Torque would parse from a .mis file."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return f"{value:.6g}"
    if isinstance(value, list):
        return " ".join(torque_value(v) for v in value)
    return str(value)


# ---------------------------------------------------------------------------
# scene
# ---------------------------------------------------------------------------

def level_root_from(terrain_entry: str) -> str:
    """`levels/GridMap/GridMap.ter` -> `levels/GridMap`."""
    return str(Path(terrain_entry).parent).replace("\\", "/")


def _parse_jsonl(text: str) -> list[dict]:
    objects = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            objects.append(json.loads(line))
        except ValueError:
            continue
    return objects


def load_scene(archive: zipfile.ZipFile, root: str) -> list[dict]:
    """Every scene object, across both layouts BeamNG ships.

    Older modern levels keep a Torque-shaped `main/MissionGroup/**/items.level.json`
    tree plus `art/Prefabs/*.prefab`. The newest ones drop the tree and store
    each scenario as a `*.prefab.json` at the level root. Both are JSON, one
    object per line.
    """
    objects: list[dict] = []

    prefix = f"{root}/main/MissionGroup/"
    for name in sorted(archive.namelist()):
        if name.startswith(prefix) and name.endswith("/items.level.json"):
            objects += _parse_jsonl(archive.read(name).decode("utf-8-sig", "replace"))

    for name in sorted(archive.namelist()):
        if name.startswith(f"{root}/") and name.endswith(".prefab.json"):
            objects += _parse_jsonl(archive.read(name).decode("utf-8-sig", "replace"))

    return objects


PREFAB_OBJECT_RE = re.compile(r"new\s+(\w+)\s*\(\s*[^)]*\)\s*\{(.*?)\}\s*;", re.S)
PREFAB_FIELD_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def load_prefab(archive: zipfile.ZipFile, path: str) -> list[dict]:
    """Parse a BeamNG `.prefab`, which is TorqueScript with TSStatic entries."""
    try:
        text = archive.read(path.lstrip("/")).decode("utf-8-sig", "replace")
    except KeyError:
        return []

    found = []
    for cls, body in PREFAB_OBJECT_RE.findall(text):
        if cls != "TSStatic":
            continue
        found.append(dict(PREFAB_FIELD_RE.findall(body)))
    return found


def as_float_list(value):
    if isinstance(value, list):
        return [float(v) for v in value]
    if isinstance(value, str):
        return [float(v) for v in value.split()]
    return None


def emit_tsstatic(fields: dict, indent: str) -> list[str]:
    """One TSStatic. `fields` is already in world space."""
    shape = fields.get("shapeName") or fields.get("shape")
    if not shape:
        return []

    lines = [f"{indent}new TSStatic() {{",
             f'{indent}   shapeName = "{shape}";',
             f'{indent}   position = "{fields.get("position", "0 0 0")}";',
             f'{indent}   rotation = "{fields.get("rotation", "1 0 0 0")}";',
             f'{indent}   scale = "{fields.get("scale", "1 1 1")}";']
    if fields.get("collisionType"):
        lines.append(f'{indent}   collisionType = "{fields["collisionType"]}";')
    lines.append(f"{indent}}};")
    return lines


def transform_object(obj: dict, parent_pos, parent_rot, parent_scale=1.0):
    """Place a prefab-internal object into world space."""
    local_pos = as_float_list(obj.get("position")) or [0.0, 0.0, 0.0]
    # .prefab files give the matrix as a space-separated string, .prefab.json
    # as a list; as_float_list takes both.
    local_rot = as_float_list(obj.get("rotationMatrix"))

    world_pos = tuple(parent_pos[i] + mat_apply(parent_rot, local_pos)[i]
                      for i in range(3))
    world_rot = mat_mul(parent_rot, tuple(local_rot)) if local_rot else parent_rot

    return {
        "shapeName": (obj.get("shapeName") or "").lstrip("/"),
        "position": " ".join(f"{c:.6g}" for c in world_pos),
        "rotation": rotation_string(world_rot),
        "scale": obj.get("scale") or "1 1 1",
        "collisionType": obj.get("collisionType"),
    }


# ---------------------------------------------------------------------------
# emitters
# ---------------------------------------------------------------------------

def emit_scene_objects(objects, archive, prefix_rewrite, z_offset=0.0) -> tuple[list[str], set[str]]:
    """Scene tree -> TorqueScript lines, plus the meshes they reference.

    z_offset re-bases every object into the converted world. The terrain block
    is moved so the ground at the origin is below the camera, and the props have
    to move with it or they float clear of the ground they were placed on.
    """
    lines: list[str] = []
    meshes: set[str] = set()

    def pos_str(pos) -> str:
        return " ".join(f"{c:.6g}" for c in (pos[0], pos[1], pos[2] + z_offset))

    for obj in objects:
        cls = obj.get("class")
        if cls not in KEPT_CLASSES:
            continue

        if cls == "TSStatic":
            shape = (obj.get("shapeName") or "").lstrip("/")
            if not shape:
                continue
            entry = {
                "shapeName": prefix_rewrite(shape),
                "position": pos_str(vec3(obj.get("position"))),
                "rotation": rotation_string(obj.get("rotationMatrix")),
                "scale": " ".join(f"{c:.6g}" for c in vec3(obj.get("scale"), (1.0, 1.0, 1.0))),
                "collisionType": obj.get("collisionType"),
            }
            lines += emit_tsstatic(entry, "   ")
            meshes.add(shape)

        elif cls == "Prefab":
            filename = (obj.get("filename") or "").lstrip("/")
            if not filename:
                continue
            instance_pos = vec3(obj.get("position"))
            instance_rot = tuple(float(v) for v in as_float_list(obj.get("rotationMatrix")) or IDENTITY)
            for inner in load_prefab(archive, filename):
                entry = transform_object(inner, instance_pos, instance_rot)
                if not entry["shapeName"]:
                    continue
                entry["shapeName"] = prefix_rewrite(entry["shapeName"])
                entry["position"] = pos_str(tuple(float(c) for c in entry["position"].split()))
                lines += emit_tsstatic(entry, "   ")
                meshes.add(inner["shapeName"])

    return lines, meshes


def emit_sky(objects: list[dict]) -> tuple[list[str], list[str]]:
    """ScatterSky / LevelInfo / CloudLayer, mapped onto their Torque names."""
    lines: list[str] = []
    notes: list[str] = []

    by_class: dict[str, dict] = {}
    for obj in objects:
        cls = obj.get("class")
        if cls in ("ScatterSky", "LevelInfo", "CloudLayer") and cls not in by_class:
            by_class[cls] = obj

    info = by_class.get("LevelInfo")
    if info:
        lines += ["   new LevelInfo(theLevelInfo) {",
                  f'      fogColor = "{torque_value(info.get("fogColor", [0.6, 0.6, 0.7, 1]))}";',
                  f'      visibleDistance = "{torque_value(info.get("visibleDistance", 2000))}";',
                  f'      canvasClearColor = "{torque_value(info.get("canvasClearColor", [0, 0, 0, 255]))}";',
                  '      soundAmbience = "AudioAmbienceDefault";',
                  "   };"]
    else:
        lines += ["   new LevelInfo(theLevelInfo) {",
                  '      fogColor = "0.6 0.6 0.7 1";',
                  '      visibleDistance = "2000";',
                  '      canvasClearColor = "0 0 0 255";',
                  "   };"]

    sky = by_class.get("ScatterSky")
    if sky:
        # Only the fields Torque3D's ScatterSky actually has; BeamNG adds its
        # own gradient-file and flare properties, which are dropped.
        wanted = ["azimuth", "elevation", "sunScale", "ambientScale", "fogScale",
                  "colorize", "skyBrightness", "mieScattering", "rayleighScattering",
                  "nightColor", "nightFogColor", "brightness", "moonScale",
                  "moonLightColor", "exposure", "flareScale", "useNightCubemap",
                  "shadowDistance", "texSize", "overDarkFactor", "logWeight"]
        body = ["   new ScatterSky(theSky) {"]
        for key in wanted:
            if key in sky:
                body.append(f'      {key} = "{torque_value(sky[key])}";')
        body.append("   };")
        lines += body
    else:
        lines += ['   new ScatterSky(theSky) {',
                  '      azimuth = "35";',
                  '      elevation = "45";',
                  '      brightness = "1";',
                  "   };"]

    clouds = by_class.get("CloudLayer")
    if clouds:
        notes.append("CloudLayer skipped: it references BeamNG sky-normal textures")

    return lines, notes


# ---------------------------------------------------------------------------
# terrain materials
# ---------------------------------------------------------------------------

def material_textures(archive: zipfile.ZipFile, root: str) -> dict[str, dict]:
    """layer name -> {diffuse, normal} archive paths, from main.materials.json."""
    wanted = f"{root}/art/terrains/main.materials.json"
    if wanted not in archive.namelist():
        return {}

    try:
        data = json.loads(archive.read(wanted).decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return {}

    out: dict[str, dict] = {}
    for entry in data.values():
        if not isinstance(entry, dict) or entry.get("class") != "TerrainMaterial":
            continue
        name = entry.get("internalName")
        if not name:
            continue
        # Prefer the detail maps: they tile, which is what Torque's diffuse and
        # normal slots expect. The "base" maps are a single map-wide stretch.
        out[name] = {
            "diffuse": entry.get("baseColorDetailTex") or entry.get("baseColorBaseTex"),
            "normal": entry.get("normalDetailTex") or entry.get("normalBaseTex"),
            "diffuseSize": entry.get("diffuseSize", 50),
            "detailSize": entry.get("detailSize", 2),
        }
    return out


def emit_terrain_materials(materials: dict[str, dict], layer_names, module, level_id,
                           archive, level_dir, root, prefix_rewrite) -> tuple[list[str], list[str]]:
    """Write ImageAsset + TerrainMaterialAsset per terrain layer."""
    written: list[str] = []
    textures_dir = level_dir / "terrains"
    textures_dir.mkdir(parents=True, exist_ok=True)

    for layer in layer_names:
        info = materials.get(layer)
        if not info or not info.get("diffuse"):
            continue

        # Copy the diffuse texture next to the material.
        source = info["diffuse"].lstrip("/")
        if source not in archive.namelist():
            continue
        texture_name = Path(source).name
        (textures_dir / texture_name).write_bytes(archive.read(source))

        image_asset = f"{level_id}_{sanitize(layer)}_image"
        (textures_dir / f"{image_asset}.asset.taml").write_text(
            f'<ImageAsset\n    AssetName="{image_asset}"\n'
            f'    imageFile="@assetFile={texture_name}"/>\n',
            encoding="utf-8",
        )
        written.append(f"terrains/{image_asset}.asset.taml")

        mat_asset = f"{level_id}_{sanitize(layer)}_terrainMat"
        # Both the object name and materialDefinitionName must be the terrain
        # layer name verbatim: TerrainMaterial::findOrCreate matches on it, and
        # the name comes out of the .ter file.
        (textures_dir / f"{mat_asset}.tscript").write_text(
            f'singleton TerrainMaterial({layer})\n'
            "{\n"
            f'   diffuseMapAsset = "{module}:{image_asset}";\n'
            f'   diffuseSize = "{torque_value(info.get("diffuseSize", 50))}";\n'
            f'   detailSize = "{torque_value(info.get("detailSize", 2))}";\n'
            f'   internalName = "{layer}";\n'
            "};\n",
            encoding="utf-8",
        )
        written.append(f"terrains/{mat_asset}.tscript")

        (textures_dir / f"{mat_asset}.asset.taml").write_text(
            f'<TerrainMaterialAsset\n'
            f'    AssetName="{mat_asset}"\n'
            f'    scriptFile="@assetFile={mat_asset}.tscript"\n'
            f'    materialDefinitionName="{layer}"/>\n',
            encoding="utf-8",
        )
        written.append(f"terrains/{mat_asset}.asset.taml")

    return written, []


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


# ---------------------------------------------------------------------------
# level scaffold
# ---------------------------------------------------------------------------

def write_module(module_dir: Path, module: str, autoclose_seconds: float = 0.0,
                 start_level_asset: str | None = None) -> None:
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir / f"{module}.module").write_text(
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

    # Both of these are dev-harness behaviour, so they are generated rather than
    # hand-written: re-running the converter is the only way they change, and
    # `--autostart off --autoclose 0` produces a stock, menu-driven game.
    #
    # The schedules live in onCreate because that is the module lifecycle hook
    # the engine calls. They are deferred rather than called inline because
    # StartGame() is defined by Core_ClientServer, which main.tscript loads
    # *after* this module's Game group.
    create_body: list[str] = []
    helpers: list[str] = []

    if start_level_asset:
        create_body.append(
            '   // Boot straight into the converted level. Without this the game\n'
            '   // stops at the main menu and waits for input that an unattended\n'
            '   // run never provides.\n'
            '   schedule(3000, 0, "beamngwebAutoStart");'
        )
        helpers.append(f"""
function beamngwebAutoStart()
{{
   echo("### BeamNGWeb: auto-starting {start_level_asset}");
   StartGame("{start_level_asset}", "SinglePlayer");
}}
""")

    if autoclose_seconds > 0:
        create_body.append(
            f'   // Quit so an unattended run cannot hang.\n'
            f'   schedule({int(autoclose_seconds * 1000)}, 0, "beamngwebAutoClose");'
        )
        helpers.append(f"""
function beamngwebAutoClose()
{{
   echo("### BeamNGWeb: auto-closing after {autoclose_seconds:g}s");
   quit();
}}
""")

    body = "\n".join(create_body)
    tail = "".join(helpers)

    (module_dir / f"{module}.tscript").write_text(
        f"""// Levels generated by tools/steam-level.py. See that script for what is
// and is not converted from a stock BeamNG.drive level.
function {module}::onCreate(%this)
{{
{body}
}}
{tail}
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
    AssetDescription="Converted from the stock BeamNG.drive level '{level_name}'."
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


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def find_level_zip(steam: Path, level: str) -> Path:
    levels_dir = steam / "content" / "levels"
    if not levels_dir.is_dir():
        raise ConvertError(f"no levels directory at {levels_dir}")

    wanted = level.lower()
    for entry in sorted(levels_dir.glob("*.zip")):
        if entry.stem.lower() == wanted:
            return entry

    available = ", ".join(sorted(p.stem for p in levels_dir.glob("*.zip")))
    raise ConvertError(f"no level named '{level}' in {levels_dir}\navailable: {available}")


def pick_terrain(archive: zipfile.ZipFile) -> str:
    sidecar_name = None
    for name in archive.namelist():
        if name.lower().endswith(".terrain.json"):
            sidecar_name = name
            break

    if sidecar_name:
        try:
            sidecar = json.loads(archive.read(sidecar_name).decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            sidecar = None
        if sidecar and sidecar.get("datafile"):
            wanted = sidecar["datafile"].lstrip("/").lower()
            for name in archive.namelist():
                if name.lower() == wanted:
                    return name

    ters = [n for n in archive.namelist() if n.lower().endswith(".ter")]
    if not ters:
        raise ConvertError("no .ter terrain file in the archive")
    return max(ters, key=lambda n: archive.getinfo(n).file_size)


def level_id_for(stem: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", stem) if w]
    return "Steam" + "".join(w[:1].upper() + w[1:] for w in words)


def same_path(a: Path, b: Path) -> bool:
    """True when two paths resolve to the same place.

    Used to check whether the engine-visible data/<module> path is a junction
    onto the real output directory. os.path.realpath resolves Windows directory
    junctions (Python 3.8+), whereas Path.is_symlink() does not -- a junction
    carries IO_REPARSE_TAG_MOUNT_POINT, not the symlink tag.
    """
    try:
        return Path(os.path.realpath(a)) == Path(os.path.realpath(b))
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("level", help="level name, matching content/levels/<name>.zip")
    parser.add_argument("--steam", default=os.environ.get("BEAMNG_DIR", DEFAULT_STEAM),
                        help=f"BeamNG.drive install directory (default: {DEFAULT_STEAM})")
    parser.add_argument("--game", default=DEFAULT_GAME,
                        help=f"BaseGame 'game' directory, checked for the "
                             f"engine-visible link (default: {DEFAULT_GAME})")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"directory to write the converted module into "
                             f"(default: {DEFAULT_OUT})")
    parser.add_argument("--module", default=DEFAULT_MODULE,
                        help=f"module to write the level into (default: {DEFAULT_MODULE})")
    parser.add_argument("--terrain-only", action="store_true",
                        help="convert just the terrain, as the first version did")
    parser.add_argument("--autoclose", type=float, default=DEFAULT_AUTOCLOSE,
                        metavar="SECONDS",
                        help=f"make the game quit this many seconds after "
                             f"startup, so an unattended run cannot hang; "
                             f"0 disables (default: {DEFAULT_AUTOCLOSE:g})")
    parser.add_argument("--autostart", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="boot straight into the converted level instead "
                             "of stopping at the main menu (default: on; "
                             "disable with --no-autostart)")
    args = parser.parse_args()

    steam = Path(args.steam)
    game = Path(args.game)
    out = Path(args.out)
    if not (game / "main.tscript").is_file():
        print(f"error: {game} does not look like a BaseGame 'game' directory", file=sys.stderr)
        return 2

    try:
        zip_path = find_level_zip(steam, args.level)
    except ConvertError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    level_id = level_id_for(zip_path.stem)
    module_dir = out / args.module
    levels_dir = module_dir / "levels"
    level_dir = levels_dir / level_id
    level_dir.mkdir(parents=True, exist_ok=True)
    write_module(module_dir, args.module,
                 autoclose_seconds=args.autoclose,
                 start_level_asset=f"{args.module}:{level_id}" if args.autostart else None)

    # The engine resolves data/<module> against its own executable, so the
    # output directory has to be reachable from there. Warn rather than fail:
    # the conversion is still valid, it just will not be found at runtime.
    visible = game / "data" / args.module
    if not same_path(visible, module_dir):
        print(f"warning: {visible} does not resolve to {module_dir}.",
              file=sys.stderr)
        print("         The level will not load until it does. Run:",
              file=sys.stderr)
        print("           scripts\\link-game-files.cmd", file=sys.stderr)

    notes: list[str] = []

    with zipfile.ZipFile(zip_path) as archive:
        terrain_entry = pick_terrain(archive)
        terrain_blob = archive.read(terrain_entry)
        try:
            terrain = read_terrain(terrain_blob)
        except ConvertError as exc:
            print(f"error: {terrain_entry}: {exc}", file=sys.stderr)
            return 2

        # Re-base the whole world so the camera's fixed spawn point lands above
        # the ground. Everything -- terrain and props alike -- shifts by this.
        base_z = -(terrain["center_height"] + SPAWN_CLEARANCE)

        terrain_file = Path(terrain_entry).name
        terrain_asset = f"{args.module}:{level_id}Terrain"
        (level_dir / terrain_file).write_bytes(terrain_blob)
        write_terrain_asset(level_dir / f"{level_id}Terrain.asset.taml",
                            f"{level_id}Terrain", terrain_file)

        scene_root = level_root_from(terrain_entry)
        objects: list[dict] = []
        object_lines: list[str] = []
        meshes: set[str] = set()

        if scene_root and not args.terrain_only:
            objects = load_scene(archive, scene_root)

            def rewrite(path: str) -> str:
                # `levels/<src>/art/...` -> `data/<module>/levels/<id>/art/...`
                marker = f"{scene_root}/"
                if path.startswith(marker):
                    path = path[len(marker):]
                return f"data/{args.module}/levels/{level_id}/{path}"

            object_lines, meshes = emit_scene_objects(objects, archive, rewrite,
                                                      z_offset=base_z)

            # Copy the meshes the scene references.
            copied = 0
            for shape in sorted(meshes):
                if shape not in archive.namelist():
                    continue
                target = level_dir / shape
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(shape))
                copied += 1
            notes.append(f"copied {copied} of {len(meshes)} referenced meshes")

        sky_lines, sky_notes = emit_sky(objects)
        notes += sky_notes

        written_materials: list[str] = []
        if scene_root and not args.terrain_only:
            materials = material_textures(archive, scene_root)
            written_materials, mat_notes = emit_terrain_materials(
                materials, terrain["materials"], args.module, level_id,
                archive, level_dir, scene_root, lambda p: p)
            notes += mat_notes
            notes.append(f"terrain materials: {len(written_materials) // 3} of "
                         f"{len(terrain['materials'])} layers")

    size = terrain["size"]
    half = size // 2

    mission = [
        "//--- OBJECT WRITE BEGIN ---",
        f"new Scene({level_id}) {{",
        '   isEditing = "0";',
        '   gameModes = "ExampleGameMode";',
        '      enabled = "1";',
        "",
    ]
    mission += sky_lines
    mission += [
        f"   new TerrainBlock({level_id}Terrain) {{",
        f'      terrainAsset = "{terrain_asset}";',
        '      castShadows = "1";',
        '      squareSize = "1";',
        '      baseTexSize = "1024";',
        '      baseTexFormat = "PNG";',
        '      lightMapSize = "256";',
        '      screenError = "16";',
        f'      position = "-{half} -{half} {base_z:.4f}";',
        '      rotation = "1 0 0 0";',
        "   };",
        "   new SimGroup(CameraSpawnPoints) {",
        '         enabled = "1";',
        "      new SpawnSphere(DefaultCameraSpawnSphere) {",
        '         radius = "1";',
        '         sphereWeight = "1";',
        '         indoorWeight = "1";',
        '         outdoorWeight = "1";',
        '         dataBlock = "SpawnSphereMarker";',
        # Documentation only: the engine ignores this and drops the camera at
        # the world origin. It is written at the origin so the two agree.
        f'         position = "0 0 0";',
        '            enabled = "1";',
        "      };",
        "   };",
    ]
    mission += object_lines
    mission += ["};", "//--- OBJECT WRITE END ---", ""]

    (levels_dir / f"{level_id}.mis").write_text("\n".join(mission), encoding="utf-8")
    write_level_asset(levels_dir / f"{level_id}.asset.taml", level_id, zip_path.stem)

    print(f"level      {args.level}  <- {zip_path}")
    print(f"terrain    {terrain_entry}  ({len(terrain_blob):,} bytes)")
    print(f"format     version {terrain['version']}, {terrain['size']}x{terrain['size']}, "
          f"{len(terrain['materials'])} layers")
    print(f"height     {terrain['min_height']:.1f} .. {terrain['max_height']:.1f}"
          f"  (origin {terrain['center_height']:.1f})")
    print(f"rebase     {base_z:.1f}  -> ground at the camera spawn sits at "
          f"{-SPAWN_CLEARANCE:.0f}")
    print(f"scene      {len(objects)} objects, {len(object_lines)} script lines")
    print(f"layers     {', '.join(terrain['materials'])}")
    for note in notes:
        print(f"note       {note}")
    print()
    print(f"wrote {levels_dir / (level_id + '.mis')}")
    print(f"load it from the level list as '{zip_path.stem} (Steam)'")
    return 0


if __name__ == "__main__":
    sys.exit(main())

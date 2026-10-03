#!/usr/bin/env bash
# Torque3D incremental wasm compile matrix — sweep driver (M0a Task 8 probe).
#
# Compiles a representative set of Torque3D translation units to wasm objects
# with emcc directly, bypassing Torque3D's CMake entirely: its configure fails
# under Emscripten. See docs/findings/m0-emscripten-configure.md.
#
# Writes one log per file and echoes a one-line verdict per row. Verdicts:
#   PASS  object file produced
#   INCL  stopped on a missing #include (usually a missing -I, see below)
#   FAIL  compiled and produced diagnostics
#
# Usage:  bash m0-compile-matrix-harness.sh [directory-label]     (no arg = all)
#         T8_WORKDIR=/somewhere bash m0-compile-matrix-harness.sh
#
# An INCL row is NOT a portability finding until you have checked whether the
# header exists somewhere in the tree; if it does, add an -I and re-run that row.
# The COLLADA path in INC below was found exactly that way.
set -u

EMCC="${EMCC:-/c/emsdk/upstream/emscripten/emcc}"
T3D="${T3D_ROOT:-/i/BeamNGWeb/third_party/Torque3D}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTDIR="${T8_WORKDIR:-$ROOT/build/t3d-wasm-matrix}"   # build/ is git-ignored
LOGDIR="$OUTDIR/logs"
mkdir -p "$LOGDIR"

# An inherited CC shadows emcc and silently wins, producing confusing host errors.
unset CC CXX

INC=(-I"$T3D/Engine/source" -I"$T3D/Engine/source/platform" -I"$T3D/Engine/lib/sdl/include"
     -I"$T3D/My Projects/BaseGame/source" -I"$T3D/Engine/source/ts/vhacd"
     -I"$T3D/Engine/lib/tinyxml2" -I"$T3D/Engine/lib/glad/include"
     -I"$T3D/Engine/lib/openal-soft/include" -I"$T3D/Engine/lib/assimp/include"
     -I"$T3D/Engine/lib/lpng" -I"$T3D/Engine/lib/squish" -I"$T3D/Engine/lib/opcode"
     -I"$T3D/Engine/lib/opcode/Ice" -I"$T3D/Engine/lib/pcre"
     -I"$T3D/Engine/lib/convexMath" -I"$T3D/Engine/lib/bullet/src"
     -I"$T3D/Engine/lib/recast/Detour/Include" -I"$T3D/Engine/lib/recast/Recast/Include"
     -I"$T3D/Engine/lib/recast/DebugUtils/Include" -I"$T3D/Engine/lib/nativeFileDialogs"
     -I"$T3D/Engine/lib/zlib" -I"$T3D/Engine/lib" -I"$T3D/Engine/lib/collada/include"
     -I"$T3D/Engine/lib/collada/include/1.4")

# -Dlinux / -D__linux__ is a deliberate choice: it selects the Linux paths, which
# is the half of the configure's Windows-host/Linux-target hybrid that Emscripten
# would take. Rows are conditional on it.
#
# -D__x86_64__ is *probe scaffolding*, not what a real wasm build uses: emcc
# defines __wasm32__ / __EMSCRIPTEN__ and does NOT define __x86_64__. It was
# present to test the "configure classifies the target as Linux-x86" hypothesis.
# Override the whole set with T8_DEF to re-baseline against emcc's real defines
# (see docs/findings/m0b-define-baseline.md).
if [ -n "${T8_DEF:-}" ]; then
  read -r -a DEF <<< "$T8_DEF"
else
  DEF=(-Dlinux -D__x86_64__ -D__linux__ -DTORQUE_OPENGL -DTORQUE_SDL
       -DTORQUE_ADVANCED_LIGHTING -DTORQUE_BASIC_LIGHTING -DTORQUE_OGGVORBIS
       -DTORQUE_OGGTHEORA -DTORQUE_RELEASE -DTORQUE_ENABLE_ASSERTS
       -DTORQUE_DEBUG_GFX_MODE)
fi

# The compiler standard is likewise overridable: the plan pins C++17, and the
# C++23 run exists only as a control.
if [ -n "${T8_STD:-}" ]; then
  read -r -a STD <<< "$T8_STD"
else
  STD=(-std=c++23)
fi

compile_one() {
  local LABEL="$1" REL="$2"
  local SRC="$T3D/Engine/source/$REL"
  local BASE SLUG LOG
  BASE="$(basename "$REL")"
  SLUG="$(echo "$LABEL" | tr '/' '_')"
  LOG="$LOGDIR/${SLUG}__${BASE}.log"

  {
    echo "### cmd: emcc -c $REL ${STD[*]} ${INC[*]} ${DEF[*]} -pthread"
    "$EMCC" -c "$SRC" -o "$OUTDIR/o.o" "${STD[@]}" "${INC[@]}" "${DEF[@]}" -pthread 2>&1
    echo "### exit: $?"
  } > "$LOG" 2>&1

  if grep -q '^### exit: 0$' "$LOG"; then
    echo "PASS  $LABEL/$BASE"
  elif grep -q "fatal error: .* file not found" "$LOG"; then
    echo "INCL  $LABEL/$BASE  $(grep -m1 -o 'fatal error: .* file not found' "$LOG")"
  else
    echo "FAIL  $LABEL/$BASE  (errors=$(grep -c 'error:' "$LOG"))  $(grep -m1 -o 'error:.*' "$LOG")"
  fi
}

FILTER="${1:-}"

FILES=(
"core|core/tokenizer.cpp"
"core|core/stringTable.cpp"
"core|core/frameAllocator.cpp"
"core|core/util/refBase.cpp"
"core|core/stream/fileStream.cpp"
"core|core/util/zip/zipArchive.cpp"
"math|math/mMatrix.cpp"
"math|math/mMath_C.cpp"
"math|math/mMathSSE.cpp"
"math|math/mRandom.cpp"
"math|math/mQuat.cpp"
"util|util/settings.cpp"
"util|util/noise2d.cpp"
"util|util/sampler.cpp"
"util|util/quadTreeTracer.cpp"
"console|console/console.cpp"
"console|console/consoleInternal.cpp"
"console|console/consoleObject.cpp"
"console|console/consoleTypes.cpp"
"console|console/engineExports.cpp"
"console|console/torquescript/parser.cpp"
"platform|platform/platform.cpp"
"platform|platform/platformFileIO.cpp"
"platform|platform/platformTimer.cpp"
"platform|platform/platformNet.cpp"
"platform|platform/platformMemory.cpp"
"platform|platform/platformCPU.cpp"
"platform|platform/platformFont.cpp"
"platformSDL|platformSDL/sdlPlatform.cpp"
"platformSDL|platformSDL/sdlPlatformGL.cpp"
"platformSDL|platformSDL/sdlInput.cpp"
"platformSDL|platformSDL/sdlCPUInfo.cpp"
"platformSDL|platformSDL/sdlMsgBox.cpp"
"platformPOSIX|platformPOSIX/POSIXFileio.cpp"
"platformPOSIX|platformPOSIX/POSIXConsole.cpp"
"platformPOSIX|platformPOSIX/POSIXTime.cpp"
"platformPOSIX|platformPOSIX/POSIXUtils.cpp"
"platformPOSIX|platformPOSIX/POSIXMath.cpp"
"platformPOSIX|platformPOSIX/POSIXGL.client.cpp"
"windowManager|windowManager/platformWindow.cpp"
"windowManager|windowManager/platformInterface.cpp"
"windowManager|windowManager/sdl/sdlWindow.cpp"
"windowManager|windowManager/platformCursorController.cpp"
"gfx/gl|gfx/gl/gfxGLDevice.cpp"
"gfx/gl|gfx/gl/gfxGLShader.cpp"
"gfx/gl|gfx/gl/gfxGLTextureObject.cpp"
"gfx/gl|gfx/gl/gfxGLStateBlock.cpp"
"gfx/gl|gfx/gl/sdl/gfxGLDevice.sdl.cpp"
"gfx/gl|gfx/gl/tGL/tGL.cpp"
"shaderGen|shaderGen/shaderGen.cpp"
"shaderGen|shaderGen/shaderOp.cpp"
"shaderGen|shaderGen/GLSL/shaderGenGLSL.cpp"
"shaderGen|shaderGen/featureMgr.cpp"
"materials|materials/materialDefinition.cpp"
"materials|materials/matInstance.cpp"
"materials|materials/materialManager.cpp"
"materials|materials/processedShaderMaterial.cpp"
"scene|scene/sceneObject.cpp"
"scene|scene/sceneManager.cpp"
"scene|scene/sceneRenderState.cpp"
"scene|scene/sgUtil.cpp"
"ts|ts/tsShape.cpp"
"ts|ts/tsMesh.cpp"
"ts|ts/tsShapeInstance.cpp"
"ts|ts/tsMaterialList.cpp"
"terrain|terrain/terrData.cpp"
"terrain|terrain/terrRender.cpp"
"terrain|terrain/terrCell.cpp"
"sfx|sfx/sfxSystem.cpp"
"sfx|sfx/sfxBuffer.cpp"
"sfx|sfx/sfxDevice.cpp"
"sfx|sfx/sfxSound.cpp"
"app|app/game.cpp"
"app|app/mainLoop.cpp"
"app|app/version.cpp"
"main|main/main.cpp"
"gui|gui/core/guiCanvas.cpp"
"gui|gui/core/guiControl.cpp"
"gui|gui/controls/guiTextCtrl.cpp"
"gui|gui/controls/guiListBoxCtrl.cpp"
"T3D|T3D/Scene.cpp"
"T3D|T3D/gameFunctions.cpp"
"T3D|T3D/camera.cpp"
"T3D|T3D/gameBase/gameConnection.cpp"
)

for entry in "${FILES[@]}"; do
  L="${entry%%|*}"; F="${entry##*|}"
  if [ -n "$FILTER" ] && [ "$L" != "$FILTER" ]; then continue; fi
  compile_one "$L" "$F"
done

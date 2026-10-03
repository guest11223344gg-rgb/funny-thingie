#!/usr/bin/env bash
# scripts/env-check.sh — verify the M0 toolchain is present and pinned.
# Exits non-zero with a named failure if anything is missing.
set -uo pipefail

# Resolve the Emscripten SDK through its env script rather than relying on PATH,
# because C:\emsdk is installed but not activated in a fresh shell.
EMSDK_DIR="${EMSDK_DIR:-/c/emsdk}"
if [ -f "$EMSDK_DIR/emsdk_env.sh" ]; then
  # shellcheck disable=SC1091
  source "$EMSDK_DIR/emsdk_env.sh" >/dev/null 2>&1 || true
fi

fail() { echo "FAIL: $*" >&2; exit 1; }

# 1. Emscripten at the pinned upstream version.
command -v emcc >/dev/null 2>&1 || fail "emcc not found. Run: $EMSDK_DIR/emsdk.bat install 4.0.9 && $EMSDK_DIR/emsdk.bat activate 4.0.9"
EMCC_VERSION=$(emcc --version 2>/dev/null | head -1)
case "$EMCC_VERSION" in
  *4.0.9*) ;;
  *) fail "emcc is not 4.0.9 (got: $EMCC_VERSION)" ;;
esac

# 2. CMake. Not on PATH here; fall back to the winget-installed copy.
if command -v cmake >/dev/null 2>&1; then
  CMAKE_BIN=$(command -v cmake)
else
  CMAKE_BIN=$(ls "/c/Program Files/CMake/bin/cmake.exe" 2>/dev/null | head -1)
  [ -n "$CMAKE_BIN" ] || fail "cmake not found on PATH or in C:\\Program Files\\CMake"
fi
"$CMAKE_BIN" --version >/dev/null 2>&1 || fail "cmake at $CMAKE_BIN does not run"

# 3. MSVC toolset, via vswhere.
VSWHERE="/c/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe"
[ -x "$VSWHERE" ] || fail "vswhere not found at $VSWHERE"
VS_PATH=$("$VSWHERE" -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>/dev/null)
[ -n "$VS_PATH" ] || fail "no VS install with the C++ workload found"

# 4. Pinned Torque3D checkout.
T3D="third_party/Torque3D"
[ -d "$T3D/.git" ] || fail "$T3D is not a git checkout. Run scripts/fetch-torque3d.sh"
PIN=$(cat third_party/Torque3D.pin 2>/dev/null)
[ -n "$PIN" ] || fail "third_party/Torque3D.pin missing"
ACTUAL=$(git -C "$T3D" rev-parse HEAD)
[ "$PIN" = "$ACTUAL" ] || fail "Torque3D at $ACTUAL, expected pinned $PIN"

echo "OK: emcc $EMCC_VERSION"
echo "OK: cmake $CMAKE_BIN"
echo "OK: MSVC via $VS_PATH"
echo "OK: Torque3D pinned at $PIN"

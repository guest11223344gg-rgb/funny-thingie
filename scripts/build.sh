#!/usr/bin/env bash
# scripts/build.sh -- one entry point for every build stage in this repository.
#
# Each stage delegates to the script that already owns that job rather than
# re-implementing it, so this file and the per-stage scripts cannot drift apart.
#
#   scripts/build.sh [stage] [stage-arg]
#
# With no argument it prints the stage list. Run it from anywhere; it changes to
# the repository root itself.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Overridable so a second checkout can run its own server without a collision.
# 8080 rather than 8000: 8000 is commonly taken by other local tooling.
# Exported so `npx playwright test` resolves relative URLs against the same
# port the server was started on.
PORT="${PORT:-8080}"
export PORT

# Torque3D writes the executable into the SOURCE tree, not the build directory,
# so the "My Projects" segment (with its space) is expected, not a mistake.
NATIVE_EXE_DIR="third_party/Torque3D/My Projects/BaseGame/game"

die() { echo "ERROR: $*" >&2; exit 1; }
note() { echo "== $*"; }

usage() {
  cat <<'EOF'
scripts/build.sh -- build stages for BeamNGWeb

  check     Verify the toolchain: emcc 4.0.9, cmake, the MSVC toolset, and that
            third_party/Torque3D is at the pinned commit. Cheap; run it first.

  fetch     Clone Torque3D at the pinned commit into the git-ignored
            third_party/. Idempotent -- a no-op if already at the pin. Also
            applies the tracked patches in patches/torque3d/.

  patch     Re-apply the tracked Torque3D patches. Idempotent; a no-op when the
            tree already carries them. Run after any edit to patches/.

  link      Re-create the junction that makes game-files/assets visible to the
            engine as data/BeamNGMaps. Idempotent. Needed after any re-fetch of
            third_party/Torque3D, which removes the link with the old checkout.
            Run automatically by "native".

  gather [args]
            Find every BeamNG.drive install on this machine and convert levels
            from them into game-files/assets. Arguments pass straight through,
            so "scripts/build.sh gather --list" reports what is available and
            writes nothing, and "scripts/build.sh gather --all" converts
            everything. Only git-ignored content is written; see
            tools/gather-content.py.

  native    Configure and build the Windows game (Torque3D BaseGame).
            Slow on a cold run: Torque3D bootstraps its own vcpkg checkout and
            builds six audio codec libraries first.

  web [t]   Build an Emscripten target. t defaults to "smoke", the M0a browser
            harness. This is NOT the engine -- Torque3D does not build for wasm
            yet; see docs/findings/m0-summary.md.

  run       Launch the native game executable built by the "native" stage.

  serve     Serve build/web on http://localhost:PORT (PORT=8080) with the
            COOP/COEP headers SharedArrayBuffer requires. Foreground.

  test      Start the dev server, run the Playwright browser tests against it,
            then stop it. Self-contained.

  all       native, then web.

Environment:
  PORT      Dev server port (default 8080). Also used by "test".
  EMSDK_DIR Emscripten SDK location (default /c/emsdk).
EOF
}

stage_check() {
  bash scripts/env-check.sh
}

stage_fetch() {
  bash scripts/fetch-torque3d.sh
}

stage_patch() {
  bash scripts/apply-patches.sh
}

# The engine resolves data/<module> against its own executable (see
# game-files/README.md), so the converted output at game-files/assets has to be
# junctioned into the game tree. Best-effort here: a checkout with no converted
# content yet is a normal state, not an error, so a missing target is not fatal
# -- link-game-files.cmd reports it and this stage moves on.
stage_link() {
  [ -d "third_party/Torque3D/My Projects/BaseGame/game/data" ] || return 0
  if [ ! -d game-files/assets/BeamNGMaps ]; then
    note "no converted content yet; skipping the game-files junction"
    note "  generate some with: scripts/build.sh gather --all"
    return 0
  fi
  cmd //c "scripts\\link-game-files.cmd"
}

# Content gathering lives in Python because it has to read Steam's
# libraryfolders.vdf and walk a few hundred megabytes of level zips; this stage
# only forwards arguments so the two do not drift.
stage_gather() {
  python tools/gather-content.py "$@"
}

stage_native() {
  [ -f third_party/Torque3D/CMakeLists.txt ] \
    || die "third_party/Torque3D is missing. Run: scripts/build.sh fetch"
  # The checkout is git-ignored and disposable, so the tracked patches are the
  # only thing that makes an upstream edit survive a re-fetch. Re-assert them
  # here as well as in the web build.
  if [ -d third_party/Torque3D/.git ]; then bash scripts/apply-patches.sh; fi
  # A re-fetch takes the junction with it, so re-create it before the build.
  stage_link
  # MSBuild is a .NET tool and stores the child environment in a case-sensitive
  # dictionary, but Windows environment variables are case-insensitive. If both
  # HTTP_PROXY and http_proxy (or the HTTPS pair) are present, MSBuild aborts the
  # compiler test with MSB6001 ("Item has already been added"), and CMake then
  # reports the misleading "No CMAKE_C_COMPILER could be found". Many tools export
  # the lowercase forms alongside Windows' uppercase ones, so drop the duplicate.
  # Only the lowercase copy is removed, so proxy configuration is preserved.
  if [ -n "${HTTPS_PROXY:-}" ] && [ -n "${https_proxy:-}" ]; then unset https_proxy; fi
  if [ -n "${HTTP_PROXY:-}" ]  && [ -n "${http_proxy:-}"  ]; then unset http_proxy;  fi
  # //c, not /c: MSYS2 rewrites a single leading slash into a Windows path.
  cmd //c "scripts\\build-native.cmd"
}

stage_web() {
  bash scripts/build-web.sh "${1:-smoke}"
}

stage_run() {
  local exe
  exe="$(find "$NATIVE_EXE_DIR" -maxdepth 1 -name 'BaseGame*.exe' 2>/dev/null | head -1)"
  [ -n "$exe" ] || die "no BaseGame*.exe under $NATIVE_EXE_DIR. Run: scripts/build.sh native"
  note "launching $exe"
  # Torque3D resolves its data relative to the working directory, so run from
  # the game directory rather than the repository root.
  ( cd "$NATIVE_EXE_DIR" && ./"$(basename "$exe")" )
}

stage_serve() {
  [ -f build/web/index.html ] \
    || die "build/web/index.html not found. Run: scripts/build.sh web"
  exec python tools/serve.py "$PORT" build/web
}

# Start the dev server in the background and block until it accepts connections,
# so the test run cannot race the server's startup.
SERVER_PID=""
start_server() {
  python tools/serve.py "$PORT" build/web >/dev/null 2>&1 &
  SERVER_PID=$!
  trap 'stop_server' EXIT

  local i
  for i in $(seq 1 50); do
    if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
      exec 3>&-
      return 0
    fi
    # A server that died on startup will never come up; fail now rather than
    # after the full timeout so the real error is not buried.
    kill -0 "$SERVER_PID" 2>/dev/null || die "dev server exited during startup"
    sleep 0.2
  done
  die "dev server did not accept connections on port $PORT"
}

stop_server() {
  [ -n "$SERVER_PID" ] || return 0
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
  SERVER_PID=""
}

stage_test() {
  [ -f build/web/index.html ] \
    || die "build/web/index.html not found. Run: scripts/build.sh web first."
  [ -d node_modules ] \
    || die "node_modules missing. Run: npm install"

  note "starting dev server on port $PORT"
  start_server
  note "running Playwright"
  npx playwright test
}

stage_all() {
  stage_native
  stage_web
}

main() {
  local stage="${1:-}"
  case "$stage" in
    "")       usage ;;
    check)    stage_check ;;
    fetch)    stage_fetch ;;
    patch)    stage_patch ;;
    link)     stage_link ;;
    gather)   shift; stage_gather "$@" ;;
    native)   stage_native ;;
    web)      shift; stage_web "$@" ;;
    run)      stage_run ;;
    serve)    stage_serve ;;
    test)     stage_test ;;
    all)      stage_all ;;
    -h|--help|help) usage ;;
    *)        usage; die "unknown stage '$stage'" ;;
  esac
}

main "$@"

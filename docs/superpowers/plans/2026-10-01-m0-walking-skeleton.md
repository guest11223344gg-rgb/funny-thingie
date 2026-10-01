# M0a: Torque3D Browser Toolchain and Porting Probes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the native and browser build environments, prove the browser toolchain renders through WebGL2 with working threading, and produce a categorised record of exactly how Torque3D resists Emscripten — so the porting work can be planned against facts instead of guesses.

**Scope note:** This is plan M0a, the first half of the spec's M0. It does **not** complete M0: Torque3D does not boot in a browser tab when this plan ends. That is M0b, which cannot be planned until Tasks 7 and 8 below produce the findings they exist to produce. See "What M0a Deliberately Does Not Do" at the end.

**Architecture:** Torque3D 4.0 already uses SDL2 as its universal platform layer on every platform (`Engine/source/CMakeLists.txt:32`, `set(TORQUE_SDL ON) # we need sdl to do our platform interop`), and the vendored SDL2 in `Engine/lib/sdl/` already contains a complete Emscripten backend. M0 exploits this: rather than writing a platform layer, we add an Emscripten toolchain and a GLES3 profile path, then let SDL2's existing Emscripten backend carry windowing, input, and audio. Rendering targets GLES 3.0, which Emscripten maps onto WebGL2.

**Tech Stack:** C++17, CMake ≥ 3.21.0, MSVC 14.44 (VS2022 Community), Emscripten 4.0.9, SDL2 (vendored), OpenGL ES 3.0 / WebGL2, Python 3.14 (dev server), Node 24 + Playwright (browser test harness).

**Spec:** `docs/superpowers/specs/2026-10-01-beamng-browser-port-design.md`

## Global Constraints

- C++ standard is **C++17** — set by upstream at `CMakeLists.txt:4` (`set (CMAKE_CXX_STANDARD 17)`). Do not raise it.
- CMake minimum is **3.21.0** — upstream `CMakeLists.txt:1`.
- `TORQUE_APP_NAME` **must** be set on the CMake command line or configure fails with `Please set TORQUE_APP_NAME first` (`CMakeLists.txt:15`). Use `BaseGame` throughout M0.
- Torque3D is pinned at commit **`4c44642aab32cf79be4f66966d49fd74ab18e221`** (branch `development`), recorded in `third_party/Torque3D.pin`. Never build against a floating `development`.
- `third_party/` is **git-ignored**. Torque3D is a fetched dependency, not vendored source. Local modifications to it are applied through `cmake/torque3d-emscripten.cmake` via `-DCMAKE_PROJECT_INCLUDE=`, so upstream's tree stays pristine and our changes stay reviewable in a tracked file.
- `assets/` is **git-ignored** and holds licensed BeamNG content. Nothing from it may be committed or served publicly. M0 does not use it at all.
- The native PC build must keep working after every task. If a change breaks the PC build, that is a task failure, not a follow-up item.
- Web output is served over **localhost with COOP/COEP headers**. `SharedArrayBuffer` is unavailable without them, and pthreads depend on `SharedArrayBuffer`.
- `core/` as defined in the spec does not exist yet in M0. M0 adds no `core/` code; it establishes the two build targets that `core/` will later be linked into.

## Review Focus

M0 is infrastructure: its failure modes are environmental and silent rather than logical. The five most likely to bite a person using this work:

1. **A stale or mismatched Emscripten SDK.** `C:\emsdk` exists but has *no SDK version installed* (`emsdk list` shows 4.0.9 available, nothing active). Building before `emsdk install`/`activate` fails in confusing ways. Expect `emcc --version` to report 4.0.9, not to be absent.
2. **A browser opened without COOP/COEP headers.** Everything works until a thread is created, then dies with `SharedArrayBuffer is not defined`. The header must be verified, not assumed.
3. **The native build silently using a different toolchain than intended.** `cmake` is not on `PATH`; if a shell picks up a different one, the "native build works" claim is unverified. Expect the configure log to name the MSVC toolset explicitly.
4. **Building against a moving upstream.** If someone re-clones without checking out `Torque3D.pin`, results become unreproducible. Expect a version check in the build script.
5. **Torque3D is modified by editing it in place rather than through the tracked override file.** Upstream's checkout is git-ignored and disposable; if a change is made there instead of in `cmake/torque3d-emscripten.cmake`, it vanishes on the next fetch and the build breaks with no visible cause. Expect that file to be the only tracked place Torque3D's build is altered.

---

## Task 1: Verify and complete the build environment

The environment is partly present. MSVC 14.44 and VS2022 Community are installed; `cmake` and `vcpkg` are not on `PATH`; `C:\emsdk` exists but has no SDK installed. This task ends with a script that proves the environment is good, so later tasks fail loudly and early rather than obscurely.

**Files:**
- Create: `scripts/env-check.sh`
- Create: `docs/build-environment.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `scripts/env-check.sh`, exiting 0 when the environment is complete. Every later task assumes it passes.

- [ ] **Step 1: Write the environment check script**

```bash
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

# 2. CMake. Not on PATH here; fall back to the VS-bundled copy.
if command -v cmake >/dev/null 2>&1; then
  CMAKE_BIN=$(command -v cmake)
else
  CMAKE_BIN=$(ls "/c/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe" 2>/dev/null | head -1)
  [ -n "$CMAKE_BIN" ] || fail "cmake not found on PATH or in the VS2022 install"
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
```

- [ ] **Step 2: Run it and confirm it fails on Emscripten**

Run: `bash scripts/env-check.sh`
Expected: FAIL — `emcc not found`, because no SDK is installed in `C:\emsdk`.

- [ ] **Step 3: Install and activate the Emscripten SDK**

Run:
```bash
/c/emsdk/emsdk.bat install 4.0.9
/c/emsdk/emsdk.bat activate 4.0.9
```

- [ ] **Step 4: Run the check again to confirm it passes**

Run: `bash scripts/env-check.sh`
Expected: four `OK:` lines, exit 0. If `cmake` is still reported missing, install it with `winget install Kitware.CMake` and re-run.

- [ ] **Step 5: Document the environment**

Create `docs/build-environment.md` recording the exact versions this was verified against (emcc 4.0.9, MSVC 14.44.35207, VS2022 Community, Node 24.20.0, Python 3.14.5), plus the `C:\emsdk` activation requirement and the fact that `cmake`/`vcpkg` are not on `PATH`.

- [ ] **Step 6: Commit**

```bash
git add scripts/env-check.sh docs/build-environment.md
git commit -m "build: add environment check for M0 toolchain"
```

---

## Task 2: Fetch script for the pinned Torque3D

Right now `third_party/Torque3D` exists only because it was cloned by hand. It must be reproducible, and it is git-ignored, so a fresh clone of this repo would have no engine.

**Files:**
- Create: `scripts/fetch-torque3d.sh`
- Modify: `.gitignore` (confirm `third_party/` is ignored)

**Interfaces:**
- Consumes: `scripts/env-check.sh` conventions from Task 1.
- Produces: `third_party/Torque3D` at the pinned commit, and `third_party/Torque3D.pin`.

- [ ] **Step 1: Write the fetch script**

```bash
#!/usr/bin/env bash
# scripts/fetch-torque3d.sh — clone Torque3D at the pinned commit.
# Idempotent: if already at the pin, does nothing.
set -euo pipefail

REPO="https://github.com/TorqueGameEngines/Torque3D.git"
BRANCH="development"
DEST="third_party/Torque3D"
PIN_FILE="third_party/Torque3D.pin"
PIN="${TORQUE3D_PIN:-4c44642aab32cf79be4f66966d49fd74ab18e221}"

mkdir -p third_party

if [ -d "$DEST/.git" ]; then
  CURRENT=$(git -C "$DEST" rev-parse HEAD)
  if [ "$CURRENT" = "$PIN" ]; then
    echo "already at $PIN"
    echo "$PIN" > "$PIN_FILE"
    exit 0
  fi
  echo "checking out $PIN (was $CURRENT)"
  git -C "$DEST" fetch --depth 1 origin "$PIN"
  git -C "$DEST" checkout --detach "$PIN"
else
  echo "cloning $BRANCH"
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$DEST"
  CURRENT=$(git -C "$DEST" rev-parse HEAD)
  if [ "$CURRENT" != "$PIN" ]; then
    echo "NOTE: branch head is $CURRENT, pinning to $PIN instead"
    git -C "$DEST" fetch --depth 1 origin "$PIN"
    git -C "$DEST" checkout --detach "$PIN"
  fi
fi

git -C "$DEST" rev-parse HEAD > "$PIN_FILE"
echo "pinned at $(cat "$PIN_FILE")"
```

- [ ] **Step 2: Verify it is idempotent against the existing checkout**

Run: `bash scripts/fetch-torque3d.sh`
Expected: `already at 4c44642aab32cf79be4f66966d49fd74ab18e221` — no re-clone, no download. The local checkout is already at the pin, so this must be a no-op.

- [ ] **Step 3: Verify the pin file was written**

Run: `cat third_party/Torque3D.pin`
Expected: `4c44642aab32cf79be4f66966d49fd74ab18e221`

- [ ] **Step 4: Confirm third_party is ignored**

Run: `git check-ignore -v third_party/Torque3D`
Expected: output naming `.gitignore`. If nothing is printed, add `third_party/` to `.gitignore` and commit that as part of this task.

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch-torque3d.sh .gitignore
git commit -m "build: add pinned Torque3D fetch script"
```

---

## Task 3: Native PC baseline build

Establishes that upstream Torque3D builds and runs on this machine *before* any modification. This is the reference the browser target is compared against, and the debugging surface the spec relies on ("fix in the native build, verify in the browser").

Torque3D's CMake requires a template project. `Templates/BaseGame` is the stock one and is what `TORQUE_APP_NAME=BaseGame` selects.

**Files:**
- Create: `scripts/build-native.cmd`
- Create: `docs/build-native.md`

**Interfaces:**
- Consumes: `third_party/Torque3D` at the pin, from Task 2.
- Produces: a runnable `BaseGame` executable, plus the exact CMake invocation later tasks reuse for the Emscripten target.

- [ ] **Step 1: Write the native build script**

`cmd` rather than `bash`, because MSVC toolchain discovery and the backslash paths in Torque3D's CMake both behave better outside MSYS path translation.

```
@echo off
REM scripts/build-native.cmd — configure and build Torque3D BaseGame for Windows.
setlocal

set T3D=third_party\Torque3D
set BUILD=build\native

if not exist "%T3D%\CMakeLists.txt" (
  echo ERROR: %T3D% not found. Run scripts/fetch-torque3d.sh first.
  exit /b 1
)

cmake -S "%T3D%" -B "%BUILD%" -G "Visual Studio 17 2022" -A x64 ^
  -DTORQUE_APP_NAME=BaseGame ^
  -DTORQUE_TESTING=ON ^
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
if errorlevel 1 exit /b 1

cmake --build "%BUILD%" --config RelWithDebInfo --parallel
if errorlevel 1 exit /b 1

echo Built to %BUILD%
```

- [ ] **Step 2: Run it and confirm configure fails on missing vcpkg dependencies**

Run: `cmd //c scripts\build-native.cmd`
Expected: configure fails at `find_package(Ogg CONFIG REQUIRED)` — `vcpkg.json` declares `libogg`, `libvorbis`, `libflac`, `opus`, `libtheora`, `libsndfile`, and no vcpkg is installed.

- [ ] **Step 3: Install vcpkg and its dependencies for this project**

Run:
```bash
git clone https://github.com/microsoft/vcpkg.git /c/vcpkg
/c/vcpkg/bootstrap-vcpkg.sh
/c/vcpkg/vcpkg.exe install --triplet x64-windows
```
The last command reads `vcpkg.json` from the current directory, so run it from the repo root. This is the only vcpkg use in the project — the six audio codec libraries. Everything else (SDL2, Bullet, assimp, zlib, PNG, OpenAL) is vendored under `Engine/lib/`.

- [ ] **Step 4: Add the vcpkg toolchain to the build script**

Insert before the `cmake -S` line:

```
set VCPKG_ROOT=C:\vcpkg
if not exist "%VCPKG_ROOT%\scripts\buildsystems\vcpkg.cmake" (
  echo ERROR: vcpkg not found at %VCPKG_ROOT%. See docs/build-native.md.
  exit /b 1
)
```
and add to the `cmake -S` argument list:
```
  -DCMAKE_TOOLCHAIN_FILE=%VCPKG_ROOT%\scripts\buildsystems\vcpkg.cmake ^
```

- [ ] **Step 5: Build and confirm the executable is produced**

Run: `cmd //c scripts\build-native.cmd`
Expected: build completes; an executable exists under `build/native/`. Confirm with:
```bash
find build/native -name "*.exe" -newer build/native/CMakeCache.txt | head
```

- [ ] **Step 6: Run it and confirm a window opens and renders**

Run the produced executable from the repo root (it resolves `game/` paths relative to the working directory). Expected: a Torque3D window opens and renders the BaseGame scene. Close it manually.

Record in `docs/build-native.md`: the exact executable path, the exact configure command line, and the MSVC toolset version the configure log reported. That toolset version is how a future reader verifies the right compiler was used (Review Focus item 3).

- [ ] **Step 7: Commit**

```bash
git add scripts/build-native.cmd docs/build-native.md
git commit -m "build: add native Windows build script and baseline docs"
```

---

## Task 4: Dev server with COOP/COEP headers

`SharedArrayBuffer` requires cross-origin isolation, which requires the `Cross-Origin-Opener-Policy` and `Cross-Origin-Embedder-Policy` headers. Without them pthreads fail at runtime with `SharedArrayBuffer is not defined`, which is Review Focus item 2. Building the server as its own task means later tasks can treat "the server serves COOP/COEP" as a verified fact.

**Files:**
- Create: `tools/serve.py`
- Create: `web/index.html` (placeholder, replaced in Task 5)
- Test: `tests/web/server.spec.js`

**Interfaces:**
- Consumes: nothing.
- Produces: `python tools/serve.py [port] [root]` — serves `root` (default `build/web`) on `port` (default `8080`) with COOP/COEP and correct `application/wasm` MIME type. Every later web task serves through this.

- [ ] **Step 1: Write the dev server**

```python
#!/usr/bin/env python3
"""Local dev server for the browser target.

Sets the cross-origin isolation headers that SharedArrayBuffer requires,
and serves .wasm with the correct MIME type. Localhost only — this
deliberately has no bind option, because the served content includes
locally built binaries and, in later milestones, licensed assets.

Usage: python tools/serve.py [port] [root]
"""
import http.server
import socketserver
import sys
from functools import partial

DEFAULT_PORT = 8080
DEFAULT_ROOT = "build/web"


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".wasm": "application/wasm",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
    }

    def end_headers(self):
        # Cross-origin isolation: required for SharedArrayBuffer, which
        # pthreads depend on. Removing these breaks threading at runtime.
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        # Never cache during development; stale wasm is a confusing failure.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    root = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ROOT
    handler = partial(Handler, directory=root)
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"serving {root} at http://localhost:{port}/ (COOP/COEP on)")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the placeholder page**

`web/index.html`, minimal for now — Task 5 replaces it with the real smoke app:

```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>BeamNGWeb M0</title></head>
<body><h1>BeamNGWeb M0</h1><p id="status">loading</p></body>
</html>
```

- [ ] **Step 3: Initialise the Playwright harness**

`package.json`:

```json
{
  "name": "beamngweb-tests",
  "private": true,
  "scripts": {
    "test": "playwright test"
  },
  "devDependencies": {
    "@playwright/test": "^1.49.0"
  }
}
```

`playwright.config.js` — one worker and no retries, because these tests drive a real GPU-backed browser and parallel workers contend for the port:

```javascript
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/web',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  timeout: 60000,
  use: {
    // The WebGL context must be real, not SwiftShader, or the frame
    // contents differ and the render assertions are meaningless.
    launchOptions: {
      args: ['--use-gl=angle', '--enable-unsafe-swiftshader'],
    },
  },
});
```

Run:
```bash
npm install
npx playwright install chromium
```

Expected: `node_modules/` populated and a Chromium build downloaded. If `--use-gl=angle` produces a blank canvas on this machine, drop it and let Chromium pick; the smoke test in Task 5 will tell you, because it asserts on a non-uniform frame rather than on GL being present.

- [ ] **Step 4: Write the failing test**

`tests/web/server.spec.js`:

```javascript
const { test, expect } = require('@playwright/test');

// Proves the server sets the headers SharedArrayBuffer needs. If this
// fails, pthreads cannot work later regardless of what the build does.
test('server sends cross-origin isolation headers', async ({ request }) => {
  const res = await request.get('http://localhost:8080/');
  expect(res.status()).toBe(200);
  expect(res.headers()['cross-origin-opener-policy']).toBe('same-origin');
  expect(res.headers()['cross-origin-embedder-policy']).toBe('require-corp');
});

test('page reports crossOriginIsolated as true', async ({ page }) => {
  await page.goto('http://localhost:8080/');
  expect(await page.evaluate(() => self.crossOriginIsolated)).toBe(true);
});
```

- [ ] **Step 5: Run the test to verify it fails**

Run:
```bash
python tools/serve.py 8080 web &
npx playwright test tests/web/server.spec.js
```
Expected: FAIL — a 404 on `/`, because Task 5 has not published anything to `build/web` yet. The point of this step is that the harness runs and reports, not that the page loads.

- [ ] **Step 6: Point the server at a directory that exists, and re-run**

Run: `python tools/serve.py 8080 web` (serving `web/` directly), then re-run the test.
Expected: PASS — both tests green, and `crossOriginIsolated` is `true`, which is the actual proof the headers work.

- [ ] **Step 7: Commit**

```bash
git add tools/serve.py web/index.html tests/web/server.spec.js package.json playwright.config.js
git commit -m "feat: add localhost dev server with cross-origin isolation"
```

---

## Task 5: Emscripten GLES3 smoke test

Before pointing Emscripten at 20,000 files of Torque3D, prove the toolchain produces a WebGL2 context and renders. This isolates "does emcc + GLES3 + WebGL2 work here" from "does Torque3D compile", so a later failure has an obvious owner.

**Files:**
- Create: `cmake/toolchains/emscripten.cmake`
- Create: `platform/web/smoke/CMakeLists.txt`
- Create: `platform/web/smoke/main.cpp`
- Create: `scripts/build-web.sh`
- Test: `tests/web/smoke.spec.js`

**Interfaces:**
- Consumes: `tools/serve.py` from Task 4.
- Produces: `build/web/index.html`, `build/web/smoke.js`, `build/web/smoke.wasm`, and the toolchain file `cmake/toolchains/emscripten.cmake` that Task 7 reuses for Torque3D itself.

- [ ] **Step 1: Write the Emscripten toolchain file**

```cmake
# cmake/toolchains/emscripten.cmake
# Wraps the toolchain that ships inside the Emscripten SDK, so callers do not
# need to know where the SDK was activated.
if(NOT DEFINED ENV{EMSDK})
    message(FATAL_ERROR "EMSDK is not set. Source emsdk_env.sh, or run from emcmdprompt.")
endif()

include("$ENV{EMSDK}/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake")

# WebGL2 == OpenGL ES 3.0. Torque3D's shader generator must emit ES 3.00
# source, so pin the whole project to that level rather than letting SDL or
# Emscripten negotiate something weaker.
set(CMAKE_CXX_STANDARD 17 CACHE STRING "" FORCE)
add_compile_options(-sMIN_WEBGL_VERSION=2 -sMAX_WEBGL_VERSION=2)
```

- [ ] **Step 2: Write the smoke application**

`platform/web/smoke/main.cpp` — clears to a known colour and draws one triangle, so the test can assert on both "a context exists" and "geometry rasterises":

```cpp
// Minimal GLES3 + Emscripten smoke test.
// Exists to prove the toolchain, not to be useful. Delete once Torque3D
// renders under Emscripten.
#include <GLES3/gl3.h>
#include <emscripten.h>
#include <emscripten/html5.h>
#include <cstdio>
#include <cstdint>

static GLuint g_program = 0;

static const char* kVertexShader =
    "#version 300 es\n"
    "layout(location=0) in vec2 position;\n"
    "out vec2 uv;\n"
    "void main() {\n"
    "    uv = position * 0.5 + 0.5;\n"
    "    gl_Position = vec4(position, 0.0, 1.0);\n"
    "}\n";

static const char* kFragmentShader =
    "#version 300 es\n"
    "precision highp float;\n"
    "in vec2 uv;\n"
    "out vec4 fragColor;\n"
    "void main() {\n"
    // Deliberately asymmetric so a black or blank frame is distinguishable
    // from a correctly rendered one.
    "    fragColor = vec4(uv.x, uv.y, 0.25, 1.0);\n"
    "}\n";

static GLuint compile(GLenum type, const char* source) {
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &source, nullptr);
    glCompileShader(shader);
    GLint ok = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(shader, sizeof(log), nullptr, log);
        printf("shader compile failed: %s\n", log);
    }
    return shader;
}

static void init() {
    printf("GL_VERSION  = %s\n", glGetString(GL_VERSION));
    printf("GL_RENDERER = %s\n", glGetString(GL_RENDERER));

    GLuint vs = compile(GL_VERTEX_SHADER, kVertexShader);
    GLuint fs = compile(GL_FRAGMENT_SHADER, kFragmentShader);

    g_program = glCreateProgram();
    glAttachShader(g_program, vs);
    glAttachShader(g_program, fs);
    glLinkProgram(g_program);

    GLint linked = GL_FALSE;
    glGetProgramiv(g_program, GL_LINK_STATUS, &linked);
    if (!linked) {
        char log[1024];
        glGetProgramInfoLog(g_program, sizeof(log), nullptr, log);
        printf("program link failed: %s\n", log);
    }
    glDeleteShader(vs);
    glDeleteShader(fs);

    // One triangle covering roughly the whole viewport.
    static const float verts[] = {-1.0f, -1.0f, 3.0f, -1.0f, -1.0f, 3.0f};
    GLuint vbo = 0;
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, nullptr);

    printf("smoke init complete\n");
    EM_ASM({ window.__smokeReady = true; });
}

static void frame() {
    int w = 0, h = 0;
    emscripten_get_canvas_element_size("#canvas", &w, &h);
    glViewport(0, 0, w, h);
    glClearColor(0.05f, 0.05f, 0.08f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(g_program);
    glDrawArrays(GL_TRIANGLES, 0, 3);
}

int main() {
    // Ask for GLES3 explicitly; the default is GLES2, which cannot compile
    // the "#version 300 es" shaders above.
    EmscriptenWebGLContextAttributes attrs;
    emscripten_webgl_init_context_attributes(&attrs);
    attrs.majorVersion = 2;   // WebGL2
    attrs.minorVersion = 0;
    attrs.alpha = false;
    attrs.depth = true;
    attrs.antialias = false;

    EMSCRIPTEN_WEBGL_CONTEXT_HANDLE ctx =
        emscripten_webgl_create_context("#canvas", &attrs);
    if (ctx <= 0) {
        printf("failed to create WebGL2 context (%d)\n", (int)ctx);
        return 1;
    }
    emscripten_webgl_make_context_current(ctx);

    init();
    emscripten_set_main_loop(frame, 0, 0);
    return 0;
}
```

- [ ] **Step 3: Write the smoke CMake target**

`platform/web/smoke/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.21.0)
project(beamngweb_smoke CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(smoke main.cpp)

target_link_options(smoke PRIVATE
    -sMIN_WEBGL_VERSION=2
    -sMAX_WEBGL_VERSION=2
    -sALLOW_MEMORY_GROWTH=1
    -sSTACK_SIZE=5242880
    --shell-file "${CMAKE_CURRENT_SOURCE_DIR}/shell.html"
    -o "${CMAKE_BINARY_DIR}/index.html"
)
set_target_properties(smoke PROPERTIES
    OUTPUT_NAME "smoke"
    SUFFIX ".js"
)
```

- [ ] **Step 4: Write the shell page**

`platform/web/smoke/shell.html` — the canvas the C++ reaches for by id:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>BeamNGWeb M0 smoke</title>
  <style>
    html, body { margin: 0; height: 100%; background: #0d0d12; overflow: hidden; }
    #canvas { width: 100vw; height: 100vh; display: block; }
    #hud {
      position: fixed; top: 8px; left: 8px; color: #9f9;
      font: 12px/1.4 ui-monospace, monospace; white-space: pre;
    }
  </style>
</head>
<body>
  <canvas id="canvas" oncontextmenu="event.preventDefault()"></canvas>
  <div id="hud"></div>
  <script>
    // Surface engine-side printf to the test harness via the DOM.
    var hud = document.getElementById('hud');
    Module = {
      print: function (t) { hud.textContent += t + '\n'; console.log(t); },
      printErr: function (t) { hud.textContent += t + '\n'; console.error(t); },
    };
  </script>
  {{{ SCRIPT }}}
</body>
</html>
```

- [ ] **Step 5: Write the build script**

`scripts/build-web.sh`:

```bash
#!/usr/bin/env bash
# scripts/build-web.sh — build the Emscripten target into build/web.
set -euo pipefail

EMSDK_DIR="${EMSDK_DIR:-/c/emsdk}"
# shellcheck disable=SC1091
source "$EMSDK_DIR/emsdk_env.sh" >/dev/null 2>&1 || {
  echo "ERROR: could not source $EMSDK_DIR/emsdk_env.sh" >&2
  echo "Run: $EMSDK_DIR/emsdk.bat activate 4.0.9" >&2
  exit 1
}

TARGET="${1:-smoke}"

case "$TARGET" in
  smoke)
    SRC="platform/web/smoke"
    BUILD="build/web"
    ;;
  *)
    echo "ERROR: unknown target '$TARGET' (known: smoke)" >&2
    exit 1
    ;;
esac

emcmake cmake -S "$SRC" -B "$BUILD" \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/emscripten.cmake" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo

cmake --build "$BUILD" --parallel

echo "built $TARGET into $BUILD"
```

- [ ] **Step 6: Write the failing test**

`tests/web/smoke.spec.js`:

```javascript
const { test, expect } = require('@playwright/test');

// Proves emcc produced a working WebGL2 build, not merely a build.
test('smoke app creates a WebGL2 context and renders geometry', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('http://localhost:8080/');
  await page.waitForFunction(() => window.__smokeReady === true, { timeout: 20000 });

  expect(errors).toEqual([]);

  const hud = await page.textContent('#hud');
  expect(hud).toContain('smoke init complete');
  // Emscripten reports WebGL2 as "OpenGL ES 3.0 ..." — if this says 2.0,
  // the context attributes were not honoured and shaders will not compile.
  expect(hud).toMatch(/OpenGL ES 3\.0/);
});

test('rendered frame is not blank', async ({ page }) => {
  await page.goto('http://localhost:8080/');
  await page.waitForFunction(() => window.__smokeReady === true, { timeout: 20000 });
  await page.waitForTimeout(500); // let a few frames run

  // Sample the centre of the canvas. A blank or failed render is uniform;
  // a drawn triangle has a gradient across it.
  const variance = await page.evaluate(() => {
    const c = document.getElementById('canvas');
    const gl = c.getContext('webgl2');
    const px = new Uint8Array(4 * 16);
    gl.readPixels(c.width / 2 - 2, c.height / 2 - 2, 4, 4,
                  gl.RGBA, gl.UNSIGNED_BYTE, px);
    let min = 255, max = 0;
    for (let i = 0; i < px.length; i += 4) {
      min = Math.min(min, px[i]);
      max = Math.max(max, px[i]);
    }
    return max - min;
  });
  expect(variance).toBeGreaterThan(0);
});
```

- [ ] **Step 7: Run the build and confirm the smoke app builds**

Run: `bash scripts/build-web.sh smoke`
Expected: `build/web/index.html`, `build/web/smoke.js`, `build/web/smoke.wasm` all exist. If CMake reports `EMSDK is not set`, Task 1's activate step was not run.

- [ ] **Step 8: Run the tests and confirm they pass**

Run:
```bash
python tools/serve.py 8080 build/web &
npx playwright test tests/web/smoke.spec.js
```
Expected: PASS — no console errors, HUD contains `smoke init complete`, GL version reports `OpenGL ES 3.0`, and the frame has non-zero variance.

This is the milestone that de-risks the whole port: it proves emcc, GLES3, WebGL2, the header-isolated server, and the browser test harness all work together before Torque3D is involved.

- [ ] **Step 9: Commit**

```bash
git add cmake/toolchains/emscripten.cmake platform/web/smoke scripts/build-web.sh tests/web/smoke.spec.js
git commit -m "feat: add Emscripten GLES3 smoke target and browser test"
```

---

## Task 6: Emscripten threading smoke test

Torque3D's `platformSDL/threads/{thread,mutex,semaphore}.cpp` are SDL2 wrappers, and SDL2's Emscripten backend maps them onto pthreads, which need `SharedArrayBuffer`. This task proves the threading path in isolation, so a failure here is unambiguously threading rather than Torque3D's job system.

**Files:**
- Modify: `platform/web/smoke/main.cpp`
- Modify: `platform/web/smoke/CMakeLists.txt`
- Test: `tests/web/threads.spec.js`

**Interfaces:**
- Consumes: everything from Task 5.
- Produces: a verified `-pthread -sPTHREAD_POOL_SIZE` build configuration, and the `SharedArrayBuffer` round-trip that Task 7's Torque3D build will rely on.

- [ ] **Step 1: Write the failing test**

`tests/web/threads.spec.js`:

```javascript
const { test, expect } = require('@playwright/test');

// Proves SharedArrayBuffer is usable under the server's isolation headers
// and that a pthread can actually be created and joined.
test('pthread writes through SharedArrayBuffer and main thread reads it', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('http://localhost:8080/');
  await page.waitForFunction(() => window.__smokeReady === true, { timeout: 20000 });
  await page.waitForFunction(() => window.__threadTestDone === true, { timeout: 20000 });

  expect(errors).toEqual([]);
  const hud = await page.textContent('#hud');
  expect(hud).toContain('thread roundtrip ok');
});
```

Run: `npx playwright test tests/web/threads.spec.js`
Expected: FAIL — the page never sets `window.__threadTestDone`, because no thread code exists yet.

- [ ] **Step 2: Add the threading code to the smoke app**

Append to `platform/web/smoke/main.cpp` (before `main`):

```cpp
// --- threading probe -------------------------------------------------------
// Writes a value to a shared buffer from a worker thread and reads it back on
// the main thread. This is the exact mechanism the vehicle simulation will use
// to publish transforms, reduced to its smallest testable form.
#include <atomic>
#include <thread>
#include <chrono>

static std::atomic<int> g_threadResult{0};

static void threadProbe() {
    std::thread worker([] {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        g_threadResult.store(4242, std::memory_order_release);
    });
    worker.join();  // joining forces the pthread machinery to be real
}

static void checkThreadProbe() {
    if (g_threadResult.load(std::memory_order_acquire) == 4242) {
        printf("thread roundtrip ok\n");
        EM_ASM({ window.__threadTestDone = true; });
    } else {
        printf("thread roundtrip FAILED\n");
        EM_ASM({ window.__threadTestDone = true; });
    }
}
```

And change `main` from `emscripten_set_main_loop(frame, 0, 0);` to:

```cpp
    init();
    threadProbe();
    checkThreadProbe();
    emscripten_set_main_loop(frame, 0, 0);
```

- [ ] **Step 3: Enable threading in the CMake target**

Modify `platform/web/smoke/CMakeLists.txt`, replacing the `target_link_options` block:

```cmake
target_link_options(smoke PRIVATE
    -sMIN_WEBGL_VERSION=2
    -sMAX_WEBGL_VERSION=2
    -sALLOW_MEMORY_GROWTH=1
    -sSTACK_SIZE=5242880
    # Threading. PTHREAD_POOL_SIZE pre-spawns workers because the main
    # thread cannot block on a new thread in a browser.
    -pthread
    -sPTHREAD_POOL_SIZE=4
    -sPROXY_TO_PTHREAD=0
    --shell-file "${CMAKE_CURRENT_SOURCE_DIR}/shell.html"
    -o "${CMAKE_BINARY_DIR}/index.html"
)
```

- [ ] **Step 4: Rebuild and run the test**

Run:
```bash
bash scripts/build-web.sh smoke
python tools/serve.py 8080 build/web &
npx playwright test tests/web/threads.spec.js
```
Expected: PASS — HUD contains `thread roundtrip ok`, no console errors.

If it fails with `SharedArrayBuffer is not defined`, the server headers from Task 4 are not reaching the page; re-run `tests/web/server.spec.js` to isolate.

- [ ] **Step 5: Confirm the smoke tests still pass after the changes**

Run: `npx playwright test tests/web/smoke.spec.js tests/web/threads.spec.js`
Expected: all green — threading must not have broken rendering.

- [ ] **Step 6: Commit**

```bash
git add platform/web/smoke tests/web/threads.spec.js
git commit -m "feat: verify pthread and SharedArrayBuffer support in browser target"
```

---

## Task 7: Probe — configure Torque3D's CMake under Emscripten

This task and the next are **probes, not ports**. The deliverable is knowledge: a categorised record of exactly how upstream Torque3D's build resists Emscripten. That record is what makes a real porting plan possible — a bite-sized plan cannot be written for "compile 20,714 files" until we know which of them emcc rejects and why.

Do not attempt to fix things in this task. Capture, categorise, and stop.

**Files:**
- Create: `cmake/torque3d-emscripten.cmake`
- Create: `docs/findings/m0-emscripten-configure.md`

**Interfaces:**
- Consumes: `cmake/toolchains/emscripten.cmake` (Task 5), `third_party/Torque3D` at the pin (Task 2).
- Produces: a written findings document, and either a successful configure or an enumerated blocker list. Task 8 consumes both.

- [ ] **Step 1: Attempt a configure with no patches**

Run:
```bash
source /c/emsdk/emsdk_env.sh
emcmake cmake -S third_party/Torque3D -B build/web-t3d \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/emscripten.cmake" \
  -DTORQUE_APP_NAME=BaseGame \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo 2>&1 | tee /tmp/t3d-configure.log
```

- [ ] **Step 2: Capture and categorise every failure**

Read the log and group failures by cause. The categories to expect, based on the source read of `Engine/source/CMakeLists.txt`:

- **vcpkg audio dependencies** — `find_package(Ogg CONFIG REQUIRED)` and the five siblings at `Engine/source/CMakeLists.txt:8+`. These are host-built binaries and cannot link into a wasm target. Expected fix: bypass vcpkg for Emscripten and use Emscripten's own ports (`-sUSE_OGG=1 -sUSE_VORBIS=1 -sUSE_FLAC=1`).
- **Platform detection** — `if(WIN32)` / `elseif(UNIX)` branches at `Engine/source/CMakeLists.txt:40-62`. Emscripten defines neither, so it falls through to `platformX11` or nothing.
- **`find_package(Freetype REQUIRED)`** at `Engine/source/CMakeLists.txt:60`, in the `UNIX AND NOT APPLE` branch.
- **`nativeFileDialogs`** — `Engine/lib/nativeFileDialogs/CMakeLists.txt`, a Win32/Cocoa library with no browser equivalent.
- **`TORQUE_D3D11` paths** — `Engine/source/CMakeLists.txt:116`, Windows-only, should already be off.
- **Anything else.** Record it verbatim; do not paraphrase error text.

Write the result to `docs/findings/m0-emscripten-configure.md` with one section per category: the exact error text, the file and line that produced it, and your assessment of the fix. Include the raw log at the end.

- [ ] **Step 3: Add the Emscripten CMake overrides and re-run**

Create `cmake/torque3d-emscripten.cmake` containing only the overrides needed to get configure to complete: at minimum, `TORQUE_SDL` on, D3D off, `nativeFileDialogs` excluded, and a Freetype bypass. Include it with `-DCMAKE_PROJECT_INCLUDE=` on the configure line and re-run Step 1.

Record in the findings doc whether configure now completes, and which overrides were required.

- [ ] **Step 4: Commit the findings — including a failed configure**

```bash
git add cmake/torque3d-emscripten.cmake docs/findings/m0-emscripten-configure.md
git commit -m "docs: record Torque3D CMake behaviour under Emscripten"
```

An honest record of a configure that does not yet complete is a successful outcome for this task. Do not paper over failures to make the commit look better; the next task depends on this being accurate.

---

## Task 8: Probe — incremental wasm compile matrix

Second probe. Compiles Torque3D's source tree to wasm one subsystem at a time, recording which compile and which do not. The output is a matrix that directly determines task order for the real porting plan.

**Files:**
- Modify: `cmake/torque3d-emscripten.cmake`
- Create: `docs/findings/m0-compile-matrix.md`

**Interfaces:**
- Consumes: Task 7's `cmake/torque3d-emscripten.cmake` and findings doc.
- Produces: a per-subsystem compile matrix, and a committed Emscripten build configuration that compiles the largest set of Torque3D subsystems achievable in M0.

- [ ] **Step 1: Compile the foundation subsystems**

Torque3D's `Engine/source/CMakeLists.txt` adds source directories in dependency order. Compile the lowest layers first, since they have fewest platform dependencies. In order: `core`, `math`, `util`, then `console`.

For each, add only that source directory to the Emscripten build and compile.

Run:
```bash
source /c/emsdk/emsdk_env.sh
emcmake cmake -S third_party/Torque3D -B build/web-t3d \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/emscripten.cmake" \
  -DCMAKE_PROJECT_INCLUDE="$PWD/cmake/torque3d-emscripten.cmake" \
  -DTORQUE_APP_NAME=BaseGame 2>&1 | tail -20
cmake --build build/web-t3d --parallel 2>&1 | tee /tmp/t3d-build.log | tail -40
```

- [ ] **Step 2: Record the result for each subsystem**

For every source directory, record in `docs/findings/m0-compile-matrix.md`: the directory, whether it compiled, and for failures the first error verbatim plus the file and line. One row per directory. Cover all of: `core`, `math`, `util`, `console`, `platform`, `platformSDL`, `platformPOSIX`, `windowManager`, `gfx/gl`, `shaderGen`, `materials`, `scene`, `ts`, `terrain`, `sfx`, `app`, `main`, `gui`, `T3D`.

Expected areas of difficulty, based on the source read — verify rather than assume:
- `platformSDL/sdlPlatformGL.cpp` and `gfx/gl/sdl/gfxGLDevice.sdl.cpp` — SDL GL context attributes are desktop-GL shaped; ES needs a different profile request.
- `gfx/gl/tGL/tWGL.h` and `tXGL.h` — loaders for Windows and X11 GL. Emscripten needs a third path; this is likely the single largest item.
- `shaderGen/GLSL/shaderGenGLSL.cpp` — emits desktop GLSL. `#version 300 es`, precision qualifiers, and `out`/`in` in place of `varying`/`attribute` are the expected changes.
- `app/game.cpp`, `main/main.cpp` — a `while` main loop must become `emscripten_set_main_loop`.

- [ ] **Step 3: Commit the configuration and the matrix**

```bash
git add cmake/torque3d-emscripten.cmake docs/findings/m0-compile-matrix.md
git commit -m "docs: record Torque3D wasm compile matrix and working Emscripten config"
```

---

## Task 9: Findings handoff

M0's terminal deliverable is the pair of findings documents, because they are the input to the plan that actually ports the engine. This task turns them into a decision.

**Files:**
- Create: `docs/findings/m0-summary.md`

**Interfaces:**
- Consumes: `docs/findings/m0-emscripten-configure.md` (Task 7) and `docs/findings/m0-compile-matrix.md` (Task 8).
- Produces: `docs/findings/m0-summary.md`, stating whether the port is viable at the pinned revision, which subsystems need rework and roughly how much, and whether the pinned revision or a different T3D version is the better base.

- [ ] **Step 1: Write the summary**

Answer four questions explicitly, citing the matrix:

1. Does Torque3D configure and compile to wasm at the pinned revision, and what fraction of subsystems? 
2. What is the largest single work item, and is it bounded (a known quantity of mechanical change) or unbounded (unknown blockers still surfacing)?
3. Does the spec's M1 milestone remain correctly scoped, or did the probes change what comes next?
4. Was the choice to port upstream Torque3D rather than write a renderer validated, or did the probes reveal that the GL loader and shader generator together cost more than writing a GLES3 renderer from scratch? The spec already commits to replacing Torque3D's renderer at M2, so this question decides whether M1 is worth doing at all.

- [ ] **Step 2: Report to the human partner and stop**

Present the findings and the recommendation from Step 1. Do not begin M0b. The next milestone gets its own plan, written against these findings, and approved before implementation starts.

- [ ] **Step 3: Commit**

```bash
git add docs/findings/m0-summary.md
git commit -m "docs: summarise M0 findings and recommend M1 scope"
```

---

## What M0a Deliberately Does Not Do

Stated so the boundary is not mistaken for an omission:

- No `core/` library, no frozen interfaces from spec section 4.2, no BeamNG content, no JBeam parsing, no soft-body solver, no UI. Those are M1 onward.
- **Torque3D does not boot in a browser tab.** At the end of this plan the engine compiles to wasm in part and does not run. Getting it running is M0b.
- No attempt to fix the compile failures found in Tasks 7 and 8. Fixing them is the next plan's job, and doing it here would mean writing that plan blind.
- No GLSL ES conversion work in `shaderGen`, and no `tGL` Emscripten loader. Task 8 measures them; it does not build them.

The reason for stopping here rather than planning the whole port: a bite-sized plan requires knowing which files fail and how. Tasks 7 and 8 produce that knowledge. Writing the renderer-porting plan before those results exist would mean inventing the failures, and the resulting plan would be fiction that costs real time to discover is wrong.

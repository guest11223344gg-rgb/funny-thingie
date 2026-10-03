# BeamNGWeb

A BeamNG.drive-style soft-body vehicle simulation that builds for **both Windows
and the browser from a single codebase**, on top of upstream
[Torque3D](https://github.com/TorqueGameEngines/Torque3D) (MIT, pinned to an
exact commit).

The target experience is BeamNG.drive's free-roam mode: pick a vehicle, load a
map, drive, crash, and watch the body deform — plus a parts and vehicle selector
built on BeamNG's own `.pc` part configuration files. Content is read from a
locally installed BeamNG.drive copy. See [Legal](#legal) — no BeamNG content is
in this repository.

---

## Status

This repository sits at the end of **M0a, a toolchain and evidence milestone**.
It is deliberately blunt about where it stands, because the documents in
`docs/findings/` are the input to the next milestone's plan and a flattering
summary would corrupt that input.

> **The engine does not build for the browser yet.** That is milestone M0b, and
> it has not been started. M0a's job was to find out what porting Torque3D to
> wasm actually costs, before committing to it.

| Capability | State |
| --- | --- |
| Native Windows build of the Torque3D game | **Works** — builds, opens a window, renders the main menu |
| Emscripten / GLES3 smoke target | **Works** — builds, and initializes a real WebGL2 context in a real browser |
| pthreads + `SharedArrayBuffer` in the browser | **Works**, under cross-origin isolation |
| Localhost dev server with COOP/COEP headers | **Works** |
| Torque3D's own CMake configure under Emscripten | **Fails.** Root cause isolated, not yet fixed |
| Torque3D compiled to wasm | **Not done.** 80 of 84 sampled translation units compile in isolation; nothing is linked, nothing is run |
| BeamNG assets, physics, gameplay, UI | **Not started** |

`platform/web/smoke/` is a **test harness, not the game**. It exists to prove the
browser toolchain, the GL context and threading work before anything depends on
them.

### Two findings worth knowing before you read anything else

**1. Torque3D's `S64` and `U64` are 32 bits wide under wasm32.** This is silent.

`Engine/source/platform/types.gcc.h:33` guards on `TORQUE_X86`, and that macro
appears exactly once in the entire `Engine/` tree — at that `#if`. Nothing
defines it, so the `#else` branch (`typedef signed long S64`) always wins. That
is accidentally correct under LP64 and wrong under wasm32's ILP32. It produces
*warnings*, not errors — a build succeeds and misbehaves. Every timestamp, file
offset and GUID wraps at 32 bits. A compile-error-only sweep misses it entirely.

**2. Torque3D's CMake does not configure under Emscripten.**

CMake initialises `WIN32=1` from the host *before* `project()` and `UNIX=1`
*after* it. `Tools/CMake/torque_configs.cmake` is included before `project()`, so
it selects a Windows vcpkg triplet and defaults D3D11 on, while `Engine/` then
assembles for X11 Linux. The configure is a Windows-host / Linux-target hybrid —
neither half describes a browser.

Full detail, with raw logs and reproduction commands:
[`docs/findings/m0-emscripten-configure.md`](docs/findings/m0-emscripten-configure.md),
[`docs/findings/m0-compile-matrix.md`](docs/findings/m0-compile-matrix.md), and the
synthesis in [`docs/findings/m0-summary.md`](docs/findings/m0-summary.md).

---

## Requirements

- **Windows 10/11** (the native target; the browser target builds from an MSYS2
  Git Bash shell)
- **Visual Studio 2022** with the "Desktop development with C++" workload
- **CMake** on `PATH`, or at `C:\Program Files\CMake\bin\cmake.exe`
- **Emscripten SDK 4.0.9** — the version is asserted, not suggested
- **Python 3** (dev server)
- **Node.js 18+** (browser tests, Playwright)
- **Git**

Disk: Torque3D is a ~900 MB checkout and is *not* vendored here — the fetch
script clones it into the git-ignored `third_party/`.

## Quick start

```bash
# from the repository root, in Git Bash
./scripts/build.sh check     # verify every tool is present and pinned correctly
./scripts/build.sh fetch     # clone Torque3D at the pinned commit
./scripts/build.sh native    # build and run the Windows game
./scripts/build.sh web       # build the browser smoke target
./scripts/build.sh serve     # serve build/web on http://localhost:8080
./scripts/build.sh test      # start the server, run the browser tests, stop it
```

`./scripts/build.sh` with no argument prints the available stages.

The native build takes a while on a cold vcpkg (Torque3D bootstraps its own
vcpkg checkout and builds six audio codec libraries). The web smoke target is
small and builds in seconds.

### Browser requirements

The browser target needs `SharedArrayBuffer`, which needs cross-origin
isolation. `tools/serve.py` sets `Cross-Origin-Opener-Policy: same-origin` and
`Cross-Origin-Embedder-Policy: require-corp` for exactly this reason. **Opening
`index.html` from the filesystem will not work** — the pthread tests will fail
with `SharedArrayBuffer is not defined`. Serve it.

---

## Repository layout

```
core/                 portable C++, no platform or graphics dependencies
  assets/               IAssetSource, ZipVFS, DAE parser, DDS, materials
  sim/                  JBeam parser, node/beam solver, Vehicle, SimWorld
  scene/                transforms, visibility, RenderQueue building
  game/                 .pc part configuration, gameplay glue
render/
  t3d/                  adapter onto Torque3D's renderer (PC always; browser
                        through M0-M1)
  webgl2/               purpose-built GLSL ES 3.00 renderer (browser, lands M2)
platform/
  pc/                   Torque3D integration
  web/                  Emscripten main loop, pthread pool, SAB, VFS
  web/smoke/            the M0a browser smoke harness -- not the game
ui/                   HUD, garage, vehicle selector
cmake/                Emscripten toolchain and Torque3D configure overrides
scripts/              build, fetch, environment check
tools/                dev server
tests/web/            Playwright browser tests
docs/                 design spec, implementation plans, M0 findings
third_party/          git-ignored Torque3D checkout (+ its tracked pin file)
assets/               git-ignored BeamNG content
```

`core/` is the only code linked by both targets. That is what makes the PC and
browser builds share one physics implementation and one asset pipeline, and what
makes core bugs reproducible natively, where a real debugger and sanitizers are
available. **Note:** `core/`, `render/` and `ui/` are the intended layout from
the design spec — they do not exist yet. The spec is at
[`docs/superpowers/specs/2026-10-01-beamng-browser-port-design.md`](docs/superpowers/specs/2026-10-01-beamng-browser-port-design.md).

## Scripts

| Script | Purpose |
| --- | --- |
| `scripts/build.sh` | One entry point. Stages: `check`, `fetch`, `native`, `web`, `serve`, `test`, `all` |
| `scripts/env-check.sh` | Asserts emcc 4.0.9, CMake, the MSVC toolset, and that Torque3D is at the pinned commit |
| `scripts/fetch-torque3d.sh` | Clones Torque3D at the pin. Idempotent |
| `scripts/build-native.cmd` | Configures and builds the Windows game |
| `scripts/build-web.sh` | Builds an Emscripten target (`smoke`) |
| `tools/serve.py` | Localhost static server with COOP/COEP |
| `docs/findings/m0-compile-matrix-harness.sh` | Re-runs the 84-file wasm compile sweep |

The compile sweep is the most useful thing here to re-run if you doubt the
findings — it is self-contained and writes only into the git-ignored `build/`:

```bash
source /c/emsdk/emsdk_env.sh
unset CC CXX
bash docs/findings/m0-compile-matrix-harness.sh          # all 84 rows
bash docs/findings/m0-compile-matrix-harness.sh gfx      # one directory
```

## Testing

Browser tests use Playwright and drive a real headless Chrome with a real GL
backend. They are *not* self-contained: start the dev server first, or use
`./scripts/build.sh test`, which does both.

```bash
./scripts/build.sh test
```

```
tests/web/server.spec.js    COOP/COEP headers are actually set
tests/web/smoke.spec.js     WebGL2 context, shader compile, drawn frame
tests/web/threads.spec.js   pthreads and SharedArrayBuffer under isolation
```

The native side has Torque3D's own vendored GoogleTest suite. Note that
`-DTORQUE_TESTING=ON` does **not** build the game — it links `unitTesting.cpp`,
which supplies `main()` and forces a console subsystem, producing a GoogleTest
console runner that opens no window. Use `OFF` for the real windowed build.

---

## Legal

This is a personal project and is **not a distribution of BeamNG.drive**.

- BeamNG's engine is closed and is not used here. `github.com/BeamNG/Torque3D`
  was checked and is a stock upstream Torque3D 3.5.1 mirror from 2014 with no
  BeamNG-specific commits.
- The physics solver is a reimplementation from the publicly documented JBeam
  format, not BeamNG's proprietary solver.
- **No BeamNG content is committed to this repository.** `assets/` is
  git-ignored. Assets are read from a locally installed, purchased copy of
  BeamNG.drive, served over localhost for personal use only.
- Torque3D is MIT-licensed and is fetched at a pinned commit rather than
  vendored — `third_party/` is git-ignored except for the pin file.

## Documentation

| Document | What it covers |
| --- | --- |
| [`docs/superpowers/specs/`](docs/superpowers/specs/) | The design spec: architecture, milestones, risks |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | The M0a implementation plan |
| [`docs/findings/m0-emscripten-configure.md`](docs/findings/m0-emscripten-configure.md) | What Torque3D's CMake does under Emscripten, with raw logs |
| [`docs/findings/m0-compile-matrix.md`](docs/findings/m0-compile-matrix.md) | The 84-translation-unit wasm compile sweep |
| [`docs/findings/m0-summary.md`](docs/findings/m0-summary.md) | M0 synthesis and the recommendation for what comes next |
| [`docs/build-native.md`](docs/build-native.md) | Native build notes and observed behaviour |
| [`docs/build-environment.md`](docs/build-environment.md) | The toolchain M0a was developed against |

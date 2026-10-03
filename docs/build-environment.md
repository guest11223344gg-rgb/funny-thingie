# Build environment

Verified on 2026-10-01. `scripts/env-check.sh` asserts these requirements and exits
non-zero with a named failure if any is missing. Every M0 task assumes it passes.

## Versions

| Tool | Version | Notes |
| --- | --- | --- |
| Emscripten (`emcc`) | 4.0.9 | Pinned upstream SDK. |
| MSVC toolset | 14.44.35207 | |
| Visual Studio | 2022 Community | C++ workload (`Microsoft.VisualStudio.Component.VC.Tools.x86.x64`) installed. |
| Node.js | 24.20.0 | Host Node on `PATH` (`C:\Program Files\nodejs`). |
| Python | 3.14.5 | Host Python at `C:\msys64\ucrt64\bin\python`. |

Emscripten ships its own bundled Node (22.16.0) and Python (3.13.3) under `C:\emsdk`;
`emsdk_env.sh` puts those on `PATH` while it is sourced. The host versions above are
the ones the rest of the tooling (e.g. the browser test harness) uses.

## C:\emsdk activation requirement

`C:\emsdk` exists but is **not** activated in a fresh shell, so `emcc` is not on `PATH`
until the SDK is activated. `scripts/env-check.sh` handles this itself by sourcing
`C:\emsdk\emsdk_env.sh`; other scripts that need `emcc` must do the same (or source it
manually) in each new shell, because shell state does not persist between invocations.

To install and activate the pinned SDK:

```bash
/c/emsdk/emsdk.bat install 4.0.9
/c/emsdk/emsdk.bat activate 4.0.9
```

From Git Bash, invoke the batch file through `cmd.exe` with a doubled slash to stop
MSYS from rewriting the `/c` argument:

```bash
cmd.exe //c "C:\emsdk\emsdk.bat install 4.0.9"
cmd.exe //c "C:\emsdk\emsdk.bat activate 4.0.9"
```

## cmake and vcpkg are not on PATH

- **cmake** is not on `PATH`. CMake 4.4.3 was installed via
  `winget install Kitware.CMake` and lives at `C:\Program Files\CMake\bin\cmake.exe`.
  `scripts/env-check.sh` falls back to that location when `cmake` is not on `PATH`.
- **vcpkg** is not installed system-wide and is not on `PATH`. The Torque3D
  build does not need one installed by hand: `Tools/CMake/torque_configs.cmake`
  bootstraps its own checkout under `build/native/vcpkg` (see
  `docs/build-native.md`).

## Torque3D checkout

The engine is pinned in `third_party/Torque3D.pin` and checked out under
`third_party/Torque3D`. `scripts/env-check.sh` verifies the checkout's `HEAD` matches
the pin.

## Torque3D patches

`third_party/Torque3D` is git-ignored and disposable, so it is **never edited by hand**.
Every change to upstream source lives in a numbered patch under `patches/torque3d/`,
applied by `scripts/apply-patches.sh`:

```bash
./scripts/build.sh patch        # or: bash scripts/apply-patches.sh
```

The script is idempotent — a patch already present is skipped — and it is called
automatically by `scripts/fetch-torque3d.sh` (after checkout) and by
`scripts/build-web.sh` (before configuring), so a build cannot run against a pristine
tree. A patch that neither applies nor is already applied is a hard error, because
silently continuing would build the wrong tree. Patch order is filename order; keep the
numeric prefixes sequential.

| Patch | What it fixes |
| --- | --- |
| `0001-refbase-getpointer-not-constexpr.patch` | `core/util/refBase.h` — drops an ill-formed `constexpr` that blocks 77 of 84 wasm compile rows at the pinned C++17. Measured effect: the sweep goes from **7** compiling rows to **80** (3 FAIL, 1 INCL), i.e. identical to the C++23 control run. |


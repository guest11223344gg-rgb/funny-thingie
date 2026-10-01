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
- **vcpkg** is not installed. It is not needed for M0.

## Torque3D checkout

The engine is pinned in `third_party/Torque3D.pin` and checked out under
`third_party/Torque3D`. `scripts/env-check.sh` verifies the checkout's `HEAD` matches
the pin.

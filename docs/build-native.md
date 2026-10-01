# Native build

How to configure and build upstream Torque3D `BaseGame` for Windows. This is the
baseline the browser target is compared against: `scripts/build-native.cmd`
builds it unmodified, so any later breakage in the browser port can be bisected
against a build that is known to work here.

Verified on 2026-10-01 at Torque3D pin `4c44642aab32cf79be4f66966d49fd74ab18e221`.

## Prerequisites

| Requirement | Value on this machine |
| --- | --- |
| CMake | 4.4.3, at `C:\Program Files\CMake\bin\cmake.exe` (not on `PATH`) |
| Visual Studio | 2022 Community 17.14.37710.0, with the C++ workload |
| MSVC toolset | 14.44.35207 |
| git | on `PATH` |
| Torque3D checkout | `third_party/Torque3D`, from `scripts/fetch-torque3d.sh` |

`scripts/build-native.cmd` resolves CMake itself (`PATH` first, then
`C:\Program Files\CMake\bin\cmake.exe`) and fails with a named error if neither
is present, because CMake is not on `PATH` on this machine.

## Build

Run from the repository root:

```
cmd //c scripts\build-native.cmd
```

The script performs exactly this configure step, then builds it:

```
cmake -S third_party\Torque3D -B build\native -G "Visual Studio 17 2022" -A x64 ^
  -DTORQUE_APP_NAME=BaseGame ^
  -DTORQUE_TESTING=ON ^
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build\native --config RelWithDebInfo --parallel
```

This is the invocation later tasks reuse for the Emscripten target, with the
generator and toolchain swapped.

## vcpkg and the audio codec libraries

`third_party/Torque3D/vcpkg.json` declares six dependencies — `libogg`,
`libvorbis`, `libflac`, `opus`, `libtheora` and `libsndfile` — and
`Engine/source/CMakeLists.txt` does `find_package(Ogg CONFIG REQUIRED)` and
friends. Everything else (SDL2, Bullet, assimp, zlib, PNG, OpenAL) is vendored
under `Engine/lib/`.

No manual vcpkg install is required. `Tools/CMake/torque_configs.cmake` (lines
2-44) checks `%VCPKG_ROOT%` and, when it is unset, clones and bootstraps its own
vcpkg into `build/native/vcpkg`, then points `CMAKE_TOOLCHAIN_FILE` at it and
installs the manifest with the project's own overlay ports and its
`x64-windows-mixed` triplet. The script only fails early if there is no vcpkg
anywhere *and* no `git` to bootstrap one.

Install it under `C:\vcpkg` and export `VCPKG_ROOT` if you would rather pin
vcpkg explicitly; the project honours that instead.

## Output

The executable is **not** placed under `build/native/`. Torque3D sets
`CMAKE_RUNTIME_OUTPUT_DIRECTORY` to the template's game directory, so the build
lands next to the game scripts:

```
third_party/Torque3D/My Projects/BaseGame/game/BaseGame_OPTIMIZEDDEBUG.exe
```

23,800,320 bytes. The `_OPTIMIZEDDEBUG` suffix is Torque3D's name for the
`RelWithDebInfo` configuration. The runtime DLLs the build needs (`SDL2.dll`,
`OpenAL32.dll`, `zlib.dll`, `sndfile.dll`, `D3DCompiler_47.dll`) are copied
alongside it.

Because the output directory is the source tree, the usual check

```bash
find build/native -name "*.exe" -newer build/native/CMakeCache.txt | head
```

returns nothing: `CMakeCache.txt` is rewritten on every configure, so no build
product is ever newer than it, and the game binary is not under `build/native/`
at all.

## Toolset verification

The configure log reports the compiler it selected:

```
Compiler found: C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC/14.44.35207/bin/Hostx64/x64/cl.exe
```

Toolset **14.44.35207**, generator `Visual Studio 17 2022`, platform `x64`. This
is how a future reader confirms the right compiler was used.

## Running it

`-DTORQUE_TESTING=ON` links `Engine/source/testing/unitTesting.cpp`, which
supplies `main()` and builds the target with `/SUBSYSTEM:CONSOLE`. The resulting
executable is therefore a **GoogleTest runner, not the game**:

```
$ cd "third_party/Torque3D/My Projects/BaseGame/game" && ./BaseGame_OPTIMIZEDDEBUG.exe
Running main() from I:\BeamNGWeb\third_party\Torque3D\Engine\source\testing\unitTesting.cpp
[==========] Running 153 tests from 34 test suites.
...
[  PASSED  ] 153 tests.
```

All 153 tests pass, and it exits 0 without opening a window. To get the runnable
game window that this baseline is meant to be, configure with
`-DTORQUE_TESTING=OFF`.

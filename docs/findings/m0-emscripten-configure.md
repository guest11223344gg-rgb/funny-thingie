# M0 findings — configuring upstream Torque3D under Emscripten

**Task:** M0a Task 7 (probe). **Verdict: configure does not complete.**
This is a probe, so a failure with a precise attribution is the successful
outcome. Nothing under `third_party/` was modified; every override lives in the
tracked file `cmake/torque3d-emscripten.cmake`.

- **Upstream:** `third_party/Torque3D` at pin `4c44642aab32cf79be4f66966d49fd74ab18e221`
- **Toolchain:** emsdk 4.0.9 (`emcc 4.0.9`), CMake 4.4.3 (`C:\Program Files\CMake\bin\cmake.exe`)
- **Toolchain file:** `cmake/toolchains/emscripten.cmake` (Task 5), consumed via `-DCMAKE_TOOLCHAIN_FILE`
- **Generator:** `MinGW Makefiles` — chosen by the `emcmake` wrapper, not by us
- **Cross-compiling emulator:** `C:/emsdk/node/22.16.0_64bit/bin/node.exe` — also injected by `emcmake`

---

## 1. The three configure runs

| Run | Overrides | First real failure | Exact location |
|-----|-----------|--------------------|----------------|
| 1 | none | `pkg_check_modules(GTK3 REQUIRED gtk+-3.0)` in the GTK3 branch of nativeFileDialogs | `Engine/lib/nativeFileDialogs/CMakeLists.txt:16` |
| 2 | + `TORQUE_USE_ZENITY=ON`, `TORQUE_D3D11=OFF`, `TORQUE_OPENGL=ON`, `TORQUE_SDL=ON` | `advanced_option` invoked with 2 args because `${WIN32}` expanded to nothing | `Engine/lib/CMakeLists.txt:226` |
| 3 | + `WIN32=OFF` (cache) | `find_package(Ogg CONFIG REQUIRED)` | `Engine/source/CMakeLists.txt:11` |

Each run's failure is **the first one**, not the last one seen; every subsequent
line in each log is cascade noise or unrelated `-- Looking for ...` chatter. In
runs 1 and 2 CMake aborted at the reported error and never reached the next
stage, which is why the failure moves forward as each override lands.

### Exact commands

Run 1 — verbatim from the task brief, nothing added:

```bash
source /c/emsdk/emsdk_env.sh
emcmake cmake -S third_party/Torque3D -B build/web-t3d \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/emscripten.cmake" \
  -DTORQUE_APP_NAME=BaseGame \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo 2>&1 | tee build/t3d-configure-1.log
```

Runs 2 and 3 — identical plus the tracked override file:

```bash
emcmake cmake -S third_party/Torque3D -B build/web-t3d \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/emscripten.cmake" \
  -DCMAKE_PROJECT_INCLUDE="$PWD/cmake/torque3d-emscripten.cmake" \
  -DTORQUE_APP_NAME=BaseGame \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
```

`emcmake` rewrites the command before invoking CMake; the log's first line
records what actually ran, including `-G 'MinGW Makefiles'` and
`-DCMAKE_CROSSCOMPILING_EMULATOR=<node>` which we did not pass.

`build/web-t3d` is a **separate** directory from `build/web`. The latter doubles
as the dev-server serve root (Task 4), so Torque3D's build tree — and the ~183 MB
vcpkg checkout it drags in — is deliberately kept out of it.

---

## 2. Category: `nativeFileDialogs` — GTK3 via host pkg-config

**Run 1's first real failure. Verbatim:**

```
-- Checking for module 'gtk+-3.0'
--   Package 'gtk+-3.0' not found
CMake Error at C:/Program Files/CMake/share/cmake-4.4/Modules/FindPkgConfig.cmake:1093 (message):
  The following required packages were not found:

   - gtk+-3.0

Call Stack (most recent call first):
  C:/Program Files/CMake/share/cmake-4.4/Modules/FindPkgConfig.cmake:1166 (_pkg_check_modules_internal)
  Engine/lib/nativeFileDialogs/CMakeLists.txt:16 (pkg_check_modules)
```

**File and line that raised it:** `Engine/lib/nativeFileDialogs/CMakeLists.txt:16`
(`pkg_check_modules(GTK3 REQUIRED gtk+-3.0)`).

**Path taken, and why.** The file branches on the platform:

- `:7  if (APPLE)` — false
- `:11 elseif (UNIX)` — **true**, because Emscripten sets `UNIX 1`
  (`$EMSDK/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake:53`)
- `:12   if (TORQUE_USE_ZENITY)` — **false**, so control falls to `:14 else()`
- `:15     find_package(PkgConfig REQUIRED)` — succeeds
- `:16     pkg_check_modules(GTK3 REQUIRED gtk+-3.0)` — **fails**

`TORQUE_USE_ZENITY` is false because `Tools/CMake/torque_configs.cmake:130`
creates it with `advanced_option(TORQUE_USE_ZENITY "use the Zenity backend for
NFD" OFF)`, and that cache entry already exists by the time
`Engine/lib/nativeFileDialogs/CMakeLists.txt:1` runs its own
`option(TORQUE_USE_ZENITY "Use Zenity" ON)`. The `option()` call therefore does
nothing and the `OFF` default from `torque_configs.cmake` wins. Cache
confirms: `TORQUE_USE_ZENITY:BOOL=OFF`.

**The pkg-config in play is the host's.** The log records:

```
-- Found PkgConfig: C:/msys64/ucrt64/bin/pkg-config.exe (found version "2.5.1")
```

An isolated probe under the same toolchain reproduced this: `PKG_CONFIG_EXECUTABLE`
resolves to `C:/msys64/ucrt64/bin/pkg-config.exe`. So this is not "Emscripten has no
pkg-config" — it is "a Windows-host pkg-config is being asked for a Linux desktop
GUI toolkit, to satisfy a target that has no window system at all".

**Assessment / fix used.** `set(TORQUE_USE_ZENITY ON CACHE BOOL "" FORCE)` in the
override file skips the GTK3 `find_package` entirely. This is honest but weak, and
the weakness is worth recording: it **swaps the backend, it does not exclude the
library**. `nfd_zenity.c` must still compile in Task 8, and Zenity is a host
subprocess with no browser equivalent. The library is still wrong for this target;
it simply no longer breaks *configure*.

---

## 3. Category: `${WIN32}` expands to nothing — CMake argument collapse

**Run 2's first real failure. Verbatim:**

```
CMake Error at Engine/lib/CMakeLists.txt:226 (advanced_option):
  advanced_option Macro invoked with incorrect arguments for macro named:
  advanced_option
```

**File and line that raised it:** `Engine/lib/CMakeLists.txt:226`:

```cmake
advanced_option(ALSOFT_EAX "Enable legacy EAX extensions" ${WIN32})
```

`advanced_option` is `macro (advanced_option flag description state)` —
exactly three arguments (`Tools/CMake/torque_macros.cmake:77-80`). Under
Emscripten `WIN32` is *set but empty* (`Emscripten.cmake:43` is `set(WIN32)`),
so `${WIN32}` expands to nothing and the macro is called with two arguments.
This is a plain CMake argument-collapse bug, not an Emscripten incompatibility
as such.

**Why it does not happen on a normal Linux build.** `Tools/CMake/torque_configs.cmake:106-108`:

```cmake
if(NOT WIN32)
   set(WIN32 OFF CACHE BOOL "" FORCE)
endif()
```

On a non-Windows **host** this runs and leaves `WIN32` defined as the *string*
`"OFF"`, so `${WIN32}` expands to a token. On this Windows host `WIN32` is `1`
at that moment (see section 5), the block is skipped, `WIN32` is never written to
the cache (verified — no `WIN32` entry in run 1's `CMakeCache.txt`), and after
`project()` it becomes empty.

**Assessment / fix used.** `set(WIN32 OFF CACHE BOOL "" FORCE)` in the override
file reproduces exactly the state upstream creates for itself on non-Windows
hosts. `if(WIN32)` still evaluates false because CMake reads `"OFF"` as false;
the only effect is that `${WIN32}` stops vanishing. Verified: run 3's cache shows
`WIN32:BOOL=OFF` and the error is gone.

*Inference, flagged:* I did not run a Linux-host configure to confirm the
`if(NOT WIN32)` story directly; it is inferred from the macro definition, the
block at `:106-108`, the absent cache entry, and the empirical before/after
`project()` values in section 5. The mechanism fits every observation, but the
Linux half is reasoning, not observation.

---

## 4. Category: vcpkg audio dependencies — `find_package(Ogg CONFIG REQUIRED)`

**Run 3's first (and only) failure. Verbatim:**

```
CMake Error at Engine/source/CMakeLists.txt:11 (find_package):
  Could not find a package configuration file provided by "Ogg" with any of
  the following names:

    Ogg.cps
    ogg.cps
    OggConfig.cmake
    ogg-config.cmake

  Add the installation prefix of "Ogg" to CMAKE_PREFIX_PATH or set "Ogg_DIR"
  to a directory containing one of the above files.  If "Ogg" provides a
  separate development package or SDK, be sure it has been installed.
```

**File and line that raised it:** `Engine/source/CMakeLists.txt:11`. The five
siblings are at `:12-16` (`Vorbis`, `FLAC`, `Opus`, `unofficial-theora`,
`SndFile`), all `CONFIG REQUIRED`. Note this is the *first* failure of the run,
so nothing after it in the log is meaningful.

**Assessment.** No override in `cmake/torque3d-emscripten.cmake` can honestly fix
this, and none was attempted:

- The brief's suggested fix — Emscripten's own ports (`-sUSE_OGG=1`, …) — provides
  the *libraries*, but **Emscripten ports do not install CMake config packages**.
  `find_package(Ogg CONFIG REQUIRED)` looks for `OggConfig.cmake` and friends; no
  port produces those. Ports alone cannot satisfy this call. Confirmed in
  isolation: `find_package(Ogg CONFIG)` returns `Ogg_FOUND=FALSE` under the
  Emscripten toolchain.
- Making the vcpkg toolchain do the work would mean letting Torque3D's bootstrap
  win and building host binaries for a wasm target — not viable.
- Hand-writing stub `OggConfig.cmake` files would make configure *appear* to pass
  and then fail at link, which is exactly the papering-over this task forbids.

This is the terminal finding of Task 7 and needs a real decision in M0b: either
replace these six `find_package(... CONFIG REQUIRED)` calls with an Emscripten
port-based path (an engine-tree change, which Task 7's rules forbid), or convert
the audio stack to Emscripten ports at the `TORQUE_LINK_THIRDPARTY` level.

---

## 5. Category: platform detection — a host-Windows / target-Linux hybrid

The task brief predicted "Emscripten defines neither `WIN32` nor `UNIX`, so it
falls through to `platformX11` or nothing". **That is not what happens.**
Emscripten sets `UNIX 1` explicitly (`Emscripten.cmake:53`), and CMake's
platform variables are initialised from the **host** until `project()` is called.

Measured directly with the project's own toolchain file (minimal
`CMakeLists.txt`, `message()` either side of `project()`):

```
BEFORE project: WIN32=[1] UNIX=[]   APPLE=[]
AFTER  project: WIN32=[]  UNIX=[1]  APPLE=[]
```

`Tools/CMake/torque_configs.cmake` is included at `CMakeLists.txt:19`, i.e.
**before** `project()` at `CMakeLists.txt:22`, so it runs entirely inside the
window where `WIN32=1`. Consequences, mostly verified in the cache:

| Symptom | Cause | Evidence |
|---|---|---|
| `VCPKG_TARGET_TRIPLET:STRING=x64-windows-mixed` | `torque_configs.cmake:45 if(WIN32)` true at that moment (triplet set at `:49`) | run-3 cache |
| `TORQUE_D3D11:BOOL=ON` by default | `torque_configs.cmake:144` inside `if(WIN32)`; also `addDef(TORQUE_D3D11)` at `:145` | run-1 cache |
| vcpkg bootstrap ran `bootstrap-vcpkg.bat` semantics (downloaded `vcpkg.exe`) | `torque_configs.cmake:35 if(WIN32)`, command at `:36` | run-1 log lines 5-8 |
| `WIN32` never forced into the cache | `torque_configs.cmake:106 if(NOT WIN32)` false | no `WIN32` cache entry in run 1 |

Then after `project()`, `WIN32` is empty and `UNIX=1`, so `Engine/` takes every
Linux branch: `platformPOSIX` (`Engine/source/CMakeLists.txt:233`),
`platformX86UNIX` (`:237`), `platformX11` (`:257`), and `find_package(Freetype
REQUIRED)` (`:60`). Meanwhile `TORQUE_D3D11` was already defaulted ON and stays
ON in the cache (it is inert for source selection because the D3D code is
guarded by `if (WIN32 AND TORQUE_D3D11)`, but it is semantically wrong and will
matter in Task 8).

**So an Emscripten configure is a Windows-host/Linux-target hybrid**: vcpkg is
asked for a Windows triplet, while the engine is assembled for X11 Linux. Neither
half describes a browser. This one mechanism explains the majority of the
failures below it and is the most important thing this probe found.

`TORQUE_D3D11=OFF` is forced in the override file for clarity; it changes nothing
about source selection under Emscripten today.

---

## 6. Category: Freetype — no honest bypass exists

`Engine/source/CMakeLists.txt:58-62`:

```cmake
if (UNIX AND NOT APPLE)
	set(TORQUE_SOURCE_FILES ${TORQUE_SOURCE_FILES} ${TORQUE_PLATFORM_X11_SOURCES})
	find_package(Freetype REQUIRED)
```

`UNIX=1` under Emscripten, so this branch is live. Probed in isolation under the
same toolchain:

```
PROBE Freetype_FOUND=FALSE FREETYPE_INCLUDE_DIRS=
```

`FindFreetype` finds nothing. The Emscripten sysroot contains no freetype headers
or libraries (`cache/sysroot/include/freetype2/...` does not exist) — the port is
materialised lazily at link time and never as a CMake package. There is therefore
nothing to point `FREETYPE_INCLUDE_DIRS` / `FREETYPE_LIBRARY` at.

**No bypass is provided, on purpose.** The real fix is to stop Emscripten being
classified as UNIX/Linux for platform purposes — the X11 branch, `platformPOSIX`
and `platformX86UNIX` are all wrong for a browser — and that requires a change
inside the engine tree, which this task's rules forbid. Recorded here instead of
worked around.

**Not reached in any run:** configure dies at `Engine/source/CMakeLists.txt:11`
before line 60 is evaluated. The `Freetype_FOUND=FALSE` result is from an
isolated probe, not from the Torque3D configure.

---

## 7. The vcpkg self-bootstrap: it fired, and it did *not* capture the toolchain

The brief asked specifically whether `Tools/CMake/torque_configs.cmake:2-44`
fires under Emscripten and whether it fights the toolchain file.

**It fired.** Run 1's log lines 2-20:

```
-- Bootstrapping vcpkg...
Cloning into 'I:/BeamNGWeb/build/web-t3d/vcpkg'...
Updating files: 100% (14311/14311), done.
Downloading https://github.com/microsoft/vcpkg-tool/releases/download/2026-09-26/vcpkg.exe -> I:\BeamNGWeb\build\web-t3d\vcpkg\vcpkg.exe... done.
Validating signature... done.
```

14,311 files, ~183 MB, plus a `vcpkg.exe` download. `if(NOT DEFINED ENV{VCPKG_ROOT})`
is true (no such env var), `if(NOT EXISTS "${CMAKE_BINARY_DIR}/vcpkg")` is true on
a clean build directory, so it clones. **This is why a first-time configure is
slow and network-dependent** — it must be expected, and `VCPKG_ROOT` can be set in
the environment to skip it.

**It did not fight the toolchain file.** `torque_configs.cmake:44` does
`set(CMAKE_TOOLCHAIN_FILE "${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake" CACHE
STRING ...)` **without `FORCE`**, so it cannot overwrite the user-supplied
`-DCMAKE_TOOLCHAIN_FILE`. Run 3's cache:

```
CMAKE_TOOLCHAIN_FILE:STRING=I:/BeamNGWeb/cmake/toolchains/emscripten.cmake
```

The vcpkg toolchain never loaded (no vcpkg `find_package` machinery in any log;
`find_package(Ogg CONFIG REQUIRED)` failing is consistent with that).

**But it left a residue:** `VCPKG_TARGET_TRIPLET:STRING=x64-windows-mixed` *is* in
the cache, set by the host-`WIN32` window in section 5. It is currently inert
because the vcpkg toolchain is not active; it would become a live hazard if
anyone later allowed the vcpkg toolchain in.

**`TORQUE_APP_NAME` is required** (`CMakeLists.txt:15`, `FATAL_ERROR` if empty)
and was passed as `BaseGame`.

---

## 8. What was ruled out, and how

- **vcpkg toolchain capturing our toolchain file** — *ruled out.* Cache shows
  `CMAKE_TOOLCHAIN_FILE` is ours; no vcpkg package machinery appears in any log.
  The `CACHE` set without `FORCE` at `torque_configs.cmake:44` cannot overwrite a
  `-D` value.
- **Emscripten ports satisfying `find_package(Ogg CONFIG REQUIRED)`** — *ruled
  out.* Ports provide libraries, not CMake config packages; isolated probe
  returns `Ogg_FOUND=FALSE`.
- **Including the override file via `-DCMAKE_PROJECT_INCLUDE` before
  `torque_configs.cmake`** — *not possible.* `CMAKE_PROJECT_INCLUDE` is processed
  immediately after the top-level `project()` (`CMakeLists.txt:22`), which is
  *after* `torque_configs.cmake` at `:19`. The override file cannot reach the
  vcpkg bootstrap or the `VCPKG_TARGET_TRIPLET` decision. This ordering is why
  the file must set cache variables `FORCE`: the code that reads them lives in
  files processed after it.
- **Clearing `UNIX` to skip the Linux branches** — *considered and rejected.*
  `set(UNIX "")` in the override file would indeed disable `platformX11`,
  `platformPOSIX`, `platformX86UNIX` and the Freetype call, but it also makes
  `Engine/lib/nativeFileDialogs/CMakeLists.txt` fall through every branch and
  reach `add_library(nativeFileDialogs STATIC )` with no sources — a different
  error — and it silently drops the entire POSIX platform layer. That is a port
  decision, not a configure probe, and it would have been recorded as an
  unexplained flag. Not done.
- **Whether configure can be made to complete** — *not attempted.* It requires an
  architectural decision about the audio dependencies that belongs to M0b.

---

## 9. What configure did produce before failing

Configure never completed, so **no targets were generated** and there is no
`Makefile` worth building. What did get configured along the way:

- **vcpkg**: cloned and bootstrapped (above).
- **zlib**: configured from `Engine/lib/zlib`; note the downgrade warning
  `ADD_LIBRARY called with SHARED option but the target platform does not support
  dynamic linking. Building a STATIC library instead.`
- **SDL2**: configured successfully, and detects Emscripten correctly —
  `Platform: Emscripten-1`, `Compiler: C:/emsdk/upstream/emscripten/emcc.bat`,
  `SDL_OPENGL: OFF`, `SDL_OPENGLES: ON`, all X11/Wayland backends OFF.
- **nativeFileDialogs**: reached only after the run-2/3 overrides.
- The engine's own source collection (`Engine/source`) was **never reached in
  run 1**, and in run 3 died at its eleventh line.

### Hazards visible in the log for Task 8

- **`SDL_PTHREADS: OFF`** in SDL2's summary. SDL is not using pthreads even though
  Task 6 established pthread support. Relevant to the job-system plan.
- **`SDL_ATOMIC: OFF`**, `SDL_GCC_ATOMICS: ON`.
- **Nothing in this configure exercised the `-pthread` work from Task 6.**
  Neither `cmake/toolchains/emscripten.cmake` nor the Torque3D configure adds
  pthread flags, so the compile-side/link-side split (`-matomics -mbulk-memory
  -mthread-model posix` on *compile*, `--shared-memory` on *link*) is untested
  here. Task 8 must put `-pthread` on compile options as well as link options or
  `wasm-ld` will refuse the link.
- `CMake Warning (deprecated) at Engine/lib/sdl/CMakeLists.txt:3300
  (cmake_minimum_required): Compatibility with CMake < 3.10 will be removed from
  a future version of CMake.` Bundled SDL declares a pre-3.10 minimum; harmless on
  CMake 4.4.3 but a future hazard.
- `CMake Warning` about `Tools/CMake/finders/FindZlib.cmake` module-name case
  mismatch, and a `FindZLIB`-module deprecation warning. Benign.
- `-- Performing Test CHECK_CPU_ARCHITECTURE_X86 - Failed` and friends: the CPU
  detection tests all fail under wasm. The `cmake_minimum_required`-era
  `CMAKE_CXX_SIZEOF_DATA_PTR` check is what actually decides: it is 4
  (`build/web-t3d/CMakeFiles/4.4.3/CMakeCXXCompiler.cmake:69`), so the top-level
  `CMakeLists.txt` sets `TORQUE_CPU_X32` ON, which is what pulls in
  `platformX86UNIX` at `Engine/source/CMakeLists.txt:237`.

---

## 10. The override file

`cmake/torque3d-emscripten.cmake`, consumed via
`-DCMAKE_PROJECT_INCLUDE="$PWD/cmake/torque3d-emscripten.cmake"`. It contains,
with reasons inline: `WIN32=OFF`, `TORQUE_D3D11=OFF`, `TORQUE_OPENGL=ON`,
`TORQUE_SDL=ON`, `TORQUE_USE_ZENITY=ON`. It deliberately does **not** touch the
Freetype call or the audio `find_package`s, for the reasons in sections 4 and 6.

Verified landing (run-3 cache): `WIN32:BOOL=OFF`, `TORQUE_D3D11:BOOL=OFF`,
`TORQUE_OPENGL:BOOL=ON`, `TORQUE_SDL:BOOL=ON`, `TORQUE_USE_ZENITY:BOOL=ON`,
`CMAKE_PROJECT_INCLUDE:UNINITIALIZED=.../cmake/torque3d-emscripten.cmake`.

---

## 11. Corrections to the task brief's expectations

Recorded because Task 9 builds on this document:

1. **"Emscripten defines neither `WIN32` nor `UNIX`"** — wrong. Emscripten sets
   `UNIX 1` (`Emscripten.cmake:53`). The real trap is that platform variables are
   *host-derived before `project()`* and *target-derived after*, so Torque3D sees
   Windows first and Linux second in the same configure.
2. **`Engine/source/CMakeLists.txt:8`** for the audio `find_package`s and **`:60`**
   for Freetype: `:60` is right, `:8` is not — the six `find_package(... CONFIG
   REQUIRED)` calls are at **`:11-16`**, and `:11` (`Ogg`) is the one that fires.
3. **The first failure is not the audio block.** It is `nativeFileDialogs`/GTK3.
   The audio block is only reached once nativeFileDialogs is neutralised.
4. **`nativeFileDialogs` is Windows/Cocoa *plus* a GTK3 path**, and it is the GTK3
   path (the `TORQUE_USE_ZENITY OFF` default) that breaks, not the Win32/Cocoa
   branches the brief anticipated.

---

## Appendix A — raw log, run 1 (no patches, verbatim)

Also committed as `docs/findings/m0-emscripten-configure-run1.txt`.
Runs 2 and 3 are committed verbatim as `-run2.txt` and `-run3.txt`; their
error blocks are quoted in full in sections 3 and 4 above. (The extension is
`.txt` rather than `.log` because the repository ignores `*.log`.)

```
configure: cmake -S third_party/Torque3D -B build/web-t3d -DCMAKE_TOOLCHAIN_FILE=I:/BeamNGWeb/cmake/toolchains/emscripten.cmake -DTORQUE_APP_NAME=BaseGame -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_CROSSCOMPILING_EMULATOR=C:/emsdk/node/22.16.0_64bit/bin/node.exe -G 'MinGW Makefiles'
-- Bootstrapping vcpkg...
Cloning into 'I:/BeamNGWeb/build/web-t3d/vcpkg'...
Updating files:  20% (2983/14311)Updating files:  21% (3006/14311)Updating files:  22% (3149/14311)Updating files:  23% (3292/14311)Updating files:  24% (3435/14311)Updating files:  25% (3578/14311)Updating files:  26% (3721/14311)Updating files:  27% (3864/14311)Updating files:  28% (4008/14311)Updating files:  29% (4151/14311)Updating files:  30% (4294/14311)Updating files:  31% (4437/14311)Updating files:  32% (4580/14311)Updating files:  33% (4723/14311)Updating files:  34% (4866/14311)Updating files:  35% (5009/14311)Updating files:  36% (5152/14311)Updating files:  37% (5296/14311)Updating files:  38% (5439/14311)Updating files:  39% (5582/14311)Updating files:  39% (5612/14311)Updating files:  40% (5725/14311)Updating files:  41% (5868/14311)Updating files:  42% (6011/14311)Updating files:  43% (6154/14311)Updating files:  44% (6297/14311)Updating files:  45% (6440/14311)Updating files:  46% (6584/14311)Updating files:  47% (6727/14311)Updating files:  48% (6870/14311)Updating files:  49% (7013/14311)Updating files:  50% (7156/14311)Updating files:  51% (7299/14311)Updating files:  52% (7442/14311)Updating files:  53% (7585/14311)Updating files:  54% (7728/14311)Updating files:  55% (7872/14311)Updating files:  56% (8015/14311)Updating files:  57% (8158/14311)Updating files:  58% (8301/14311)Updating files:  59% (8444/14311)Updating files:  60% (8587/14311)Updating files:  60% (8657/14311)Updating files:  61% (8730/14311)Updating files:  62% (8873/14311)Updating files:  63% (9016/14311)Updating files:  64% (9160/14311)Updating files:  65% (9303/14311)Updating files:  66% (9446/14311)Updating files:  67% (9589/14311)Updating files:  68% (9732/14311)Updating files:  69% (9875/14311)Updating files:  70% (10018/14311)Updating files:  71% (10161/14311)Updating files:  72% (10304/14311)Updating files:  73% (10448/14311)Updating files:  74% (10591/14311)Updating files:  75% (10734/14311)Updating files:  76% (10877/14311)Updating files:  77% (11020/14311)Updating files:  78% (11163/14311)Updating files:  78% (11290/14311)Updating files:  79% (11306/14311)Updating files:  80% (11449/14311)Updating files:  81% (11592/14311)Updating files:  82% (11736/14311)Updating files:  83% (11879/14311)Updating files:  84% (12022/14311)Updating files:  85% (12165/14311)Updating files:  86% (12308/14311)Updating files:  87% (12451/14311)Updating files:  88% (12594/14311)Updating files:  89% (12737/14311)Updating files:  90% (12880/14311)Updating files:  91% (13024/14311)Updating files:  92% (13167/14311)Updating files:  93% (13310/14311)Updating files:  94% (13453/14311)Updating files:  95% (13596/14311)Updating files:  96% (13739/14311)Updating files:  97% (13882/14311)Updating files:  98% (14025/14311)Updating files:  99% (14168/14311)Updating files: 100% (14311/14311)Updating files: 100% (14311/14311), done.
Downloading https://github.com/microsoft/vcpkg-tool/releases/download/2026-09-26/vcpkg.exe -> I:\BeamNGWeb\build\web-t3d\vcpkg\vcpkg.exe... done.
Validating signature... done.

vcpkg package management program version 2026-09-26-51bf87ca6e9bf3e622d84ff323bd202ab1ca0c0b

See LICENSE.txt for license information.
Telemetry
---------
vcpkg collects usage data in order to help us improve your experience.
The data collected by Microsoft is anonymous.
You can opt-out of telemetry by re-running the bootstrap-vcpkg script with -disableMetrics,
passing --disable-metrics to vcpkg on the command line,
or by setting the VCPKG_DISABLE_METRICS environment variable.

Read more about vcpkg telemetry at https://learn.microsoft.com/vcpkg/about/privacy
Read the Microsoft Privacy Statement at https://go.microsoft.com/fwlink/?LinkId=521839
Prepare Template(BaseGame) install...
-- Looking for sys/types.h
-- Looking for sys/types.h - found
-- Looking for stdint.h
-- Looking for stdint.h - found
-- Looking for stddef.h
-- Looking for stddef.h - found
-- Check size of off64_t
-- Check size of off64_t - done
-- Looking for fseeko
-- Looking for fseeko - found
-- Looking for unistd.h
-- Looking for unistd.h - found
CMake Warning (author) at Engine/lib/zlib/CMakeLists.txt:152 (add_library):
  ADD_LIBRARY called with SHARED option but the target platform does not
  support dynamic linking.  Building a STATIC library instead.  This may lead
  to problems.
This warning is for project developers.  Use -Wno-author to suppress it.

-- Found PkgConfig: C:/msys64/ucrt64/bin/pkg-config.exe (found version "2.5.1")
-- Looking for __GLIBC__
-- Looking for __GLIBC__ - not found
-- Performing Test CHECK_CPU_ARCHITECTURE_X86
-- Performing Test CHECK_CPU_ARCHITECTURE_X86 - Failed
-- Performing Test CHECK_CPU_ARCHITECTURE_X64
-- Performing Test CHECK_CPU_ARCHITECTURE_X64 - Failed
-- Performing Test CHECK_CPU_ARCHITECTURE_ARM32
-- Performing Test CHECK_CPU_ARCHITECTURE_ARM32 - Failed
-- Performing Test CHECK_CPU_ARCHITECTURE_ARM64
-- Performing Test CHECK_CPU_ARCHITECTURE_ARM64 - Failed
-- Performing Test CHECK_CPU_ARCHITECTURE_ARM64EC
-- Performing Test CHECK_CPU_ARCHITECTURE_ARM64EC - Failed
-- Performing Test CHECK_CPU_ARCHITECTURE_LOONGARCH64
-- Performing Test CHECK_CPU_ARCHITECTURE_LOONGARCH64 - Failed
-- Performing Test HAVE_GCC_WALL
-- Performing Test HAVE_GCC_WALL - Success
-- Performing Test HAVE_GCC_WUNDEF
-- Performing Test HAVE_GCC_WUNDEF - Success
-- Performing Test HAVE_GCC_NO_STRICT_ALIASING
-- Performing Test HAVE_GCC_NO_STRICT_ALIASING - Success
-- Performing Test HAVE_GCC_WDOCUMENTATION
-- Performing Test HAVE_GCC_WDOCUMENTATION - Success
-- Performing Test HAVE_GCC_WDOCUMENTATION_UNKNOWN_COMMAND
-- Performing Test HAVE_GCC_WDOCUMENTATION_UNKNOWN_COMMAND - Success
-- Performing Test HAVE_GCC_COMMENT_BLOCK_COMMANDS
-- Performing Test HAVE_GCC_COMMENT_BLOCK_COMMANDS - Success
-- Performing Test HAVE_GCC_WDECLARATION_AFTER_STATEMENT
-- Performing Test HAVE_GCC_WDECLARATION_AFTER_STATEMENT - Success
-- Performing Test HAVE_GCC_ATOMICS
-- Performing Test HAVE_GCC_ATOMICS - Success
-- Performing Test HAVE_GCC_FVISIBILITY
-- Performing Test HAVE_GCC_FVISIBILITY - Success
-- Performing Test HAVE_GCC_WSHADOW
-- Performing Test HAVE_GCC_WSHADOW - Success
-- Performing Test HAVE_GCC_WUNUSED_LOCAL_TYPEDEFS
-- Performing Test HAVE_GCC_WUNUSED_LOCAL_TYPEDEFS - Success
-- Performing Test HAVE_NO_UNDEFINED
-- Performing Test HAVE_NO_UNDEFINED - Failed
-- Looking for ctype.h
-- Looking for ctype.h - found
-- Looking for float.h
-- Looking for float.h - found
-- Looking for iconv.h
-- Looking for iconv.h - found
-- Looking for inttypes.h
-- Looking for inttypes.h - found
-- Looking for limits.h
-- Looking for limits.h - found
-- Looking for malloc.h
-- Looking for malloc.h - found
-- Looking for math.h
-- Looking for math.h - found
-- Looking for memory.h
-- Looking for memory.h - found
-- Looking for signal.h
-- Looking for signal.h - found
-- Looking for stdarg.h
-- Looking for stdarg.h - found
-- Looking for stdio.h
-- Looking for stdio.h - found
-- Looking for stdlib.h
-- Looking for stdlib.h - found
-- Looking for string.h
-- Looking for string.h - found
-- Looking for strings.h
-- Looking for strings.h - found
-- Looking for wchar.h
-- Looking for wchar.h - found
-- Looking for 7 include files stddef.h, ..., float.h
-- Looking for 7 include files stddef.h, ..., float.h - found
-- Looking for M_PI
-- Looking for M_PI - found
-- Performing Test HAVE_MPROTECT
-- Performing Test HAVE_MPROTECT - Success
-- Looking for strtod
-- Looking for strtod - found
-- Looking for malloc
-- Looking for malloc - found
-- Looking for calloc
-- Looking for calloc - found
-- Looking for realloc
-- Looking for realloc - found
-- Looking for free
-- Looking for free - found
-- Looking for getenv
-- Looking for getenv - found
-- Looking for setenv
-- Looking for setenv - found
-- Looking for putenv
-- Looking for putenv - found
-- Looking for unsetenv
-- Looking for unsetenv - found
-- Looking for bsearch
-- Looking for bsearch - found
-- Looking for qsort
-- Looking for qsort - found
-- Looking for abs
-- Looking for abs - found
-- Looking for bcopy
-- Looking for bcopy - found
-- Looking for memset
-- Looking for memset - found
-- Looking for memcpy
-- Looking for memcpy - found
-- Looking for memmove
-- Looking for memmove - found
-- Looking for memcmp
-- Looking for memcmp - found
-- Looking for strlen
-- Looking for strlen - found
-- Looking for strlcpy
-- Looking for strlcpy - found
-- Looking for strlcat
-- Looking for strlcat - found
-- Looking for _strrev
-- Looking for _strrev - not found
-- Looking for _strupr
-- Looking for _strupr - not found
-- Looking for _strlwr
-- Looking for _strlwr - not found
-- Looking for index
-- Looking for index - found
-- Looking for rindex
-- Looking for rindex - found
-- Looking for strchr
-- Looking for strchr - found
-- Looking for strrchr
-- Looking for strrchr - found
-- Looking for strstr
-- Looking for strstr - found
-- Looking for strtok_r
-- Looking for strtok_r - found
-- Looking for itoa
-- Looking for itoa - not found
-- Looking for _ltoa
-- Looking for _ltoa - not found
-- Looking for _uitoa
-- Looking for _uitoa - not found
-- Looking for _ultoa
-- Looking for _ultoa - not found
-- Looking for strtol
-- Looking for strtol - found
-- Looking for strtoul
-- Looking for strtoul - found
-- Looking for _i64toa
-- Looking for _i64toa - not found
-- Looking for _ui64toa
-- Looking for _ui64toa - not found
-- Looking for strtoll
-- Looking for strtoll - found
-- Looking for strtoull
-- Looking for strtoull - found
-- Looking for atoi
-- Looking for atoi - found
-- Looking for atof
-- Looking for atof - found
-- Looking for strcmp
-- Looking for strcmp - found
-- Looking for strncmp
-- Looking for strncmp - found
-- Looking for _stricmp
-- Looking for _stricmp - not found
-- Looking for strcasecmp
-- Looking for strcasecmp - found
-- Looking for _strnicmp
-- Looking for _strnicmp - not found
-- Looking for strncasecmp
-- Looking for strncasecmp - found
-- Looking for strcasestr
-- Looking for strcasestr - found
-- Looking for wcscmp
-- Looking for wcscmp - found
-- Looking for _wcsdup
-- Looking for _wcsdup - not found
-- Looking for wcsdup
-- Looking for wcsdup - found
-- Looking for wcslcat
-- Looking for wcslcat - not found
-- Looking for wcslcpy
-- Looking for wcslcpy - not found
-- Looking for wcslen
-- Looking for wcslen - found
-- Looking for wcsncmp
-- Looking for wcsncmp - found
-- Looking for wcsstr
-- Looking for wcsstr - found
-- Looking for wcscasecmp
-- Looking for wcscasecmp - found
-- Looking for _wcsicmp
-- Looking for _wcsicmp - not found
-- Looking for wcsncasecmp
-- Looking for wcsncasecmp - found
-- Looking for _wcsnicmp
-- Looking for _wcsnicmp - not found
-- Looking for sscanf
-- Looking for sscanf - found
-- Looking for vsscanf
-- Looking for vsscanf - found
-- Looking for vsnprintf
-- Looking for vsnprintf - found
-- Looking for fopen64
-- Looking for fopen64 - found
-- Looking for fseeko64
-- Looking for fseeko64 - found
-- Looking for _Exit
-- Looking for _Exit - found
-- Looking for sigaction
-- Looking for sigaction - found
-- Looking for sigtimedwait
-- Looking for sigtimedwait - found
-- Looking for setjmp
-- Looking for setjmp - found
-- Looking for nanosleep
-- Looking for nanosleep - found
-- Looking for sysconf
-- Looking for sysconf - found
-- Looking for sysctlbyname
-- Looking for sysctlbyname - not found
-- Looking for getauxval
-- Looking for getauxval - not found
-- Looking for elf_aux_info
-- Looking for elf_aux_info - not found
-- Looking for poll
-- Looking for poll - found
-- Looking for memfd_create
-- Looking for memfd_create - not found
-- Looking for posix_fallocate
-- Looking for posix_fallocate - found
-- Looking for pow in m
-- Looking for pow in m - found
-- Looking for atan
-- Looking for atan - found
-- Looking for atan2
-- Looking for atan2 - found
-- Looking for atanf
-- Looking for atanf - found
-- Looking for atan2f
-- Looking for atan2f - found
-- Looking for ceil
-- Looking for ceil - found
-- Looking for ceilf
-- Looking for ceilf - found
-- Looking for copysign
-- Looking for copysign - found
-- Looking for copysignf
-- Looking for copysignf - found
-- Looking for cos
-- Looking for cos - found
-- Looking for cosf
-- Looking for cosf - found
-- Looking for exp
-- Looking for exp - found
-- Looking for expf
-- Looking for expf - found
-- Looking for fabs
-- Looking for fabs - found
-- Looking for fabsf
-- Looking for fabsf - found
-- Looking for floor
-- Looking for floor - found
-- Looking for floorf
-- Looking for floorf - found
-- Looking for fmod
-- Looking for fmod - found
-- Looking for fmodf
-- Looking for fmodf - found
-- Looking for log
-- Looking for log - found
-- Looking for logf
-- Looking for logf - found
-- Looking for log10
-- Looking for log10 - found
-- Looking for log10f
-- Looking for log10f - found
-- Looking for lround
-- Looking for lround - found
-- Looking for lroundf
-- Looking for lroundf - found
-- Looking for pow
-- Looking for pow - found
-- Looking for powf
-- Looking for powf - found
-- Looking for round
-- Looking for round - found
-- Looking for roundf
-- Looking for roundf - found
-- Looking for scalbn
-- Looking for scalbn - found
-- Looking for scalbnf
-- Looking for scalbnf - found
-- Looking for sin
-- Looking for sin - found
-- Looking for sinf
-- Looking for sinf - found
-- Looking for sqrt
-- Looking for sqrt - found
-- Looking for sqrtf
-- Looking for sqrtf - found
-- Looking for tan
-- Looking for tan - found
-- Looking for tanf
-- Looking for tanf - found
-- Looking for acos
-- Looking for acos - found
-- Looking for acosf
-- Looking for acosf - found
-- Looking for asin
-- Looking for asin - found
-- Looking for asinf
-- Looking for asinf - found
-- Looking for trunc
-- Looking for trunc - found
-- Looking for truncf
-- Looking for truncf - found
-- Performing Test ICONV_IN_LIBC
-- Performing Test ICONV_IN_LIBC - Success
-- Performing Test ICONV_IN_LIBICONV
-- Performing Test ICONV_IN_LIBICONV - Failed
-- Looking for alloca.h
-- Looking for alloca.h - found
-- Looking for alloca
-- Looking for alloca - found
-- Looking for alloca
-- Looking for alloca - found
-- Looking for alloca
-- Looking for alloca - not found
-- Performing Test HAVE_SA_SIGACTION
-- Performing Test HAVE_SA_SIGACTION - Success
-- Looking for dlopen
-- Looking for dlopen - found
-- Performing Test HAVE_O_CLOEXEC
-- Performing Test HAVE_O_CLOEXEC - Success
-- Performing Test LIBC_HAS_WORKING_LIBUNWIND
-- Performing Test LIBC_HAS_WORKING_LIBUNWIND - Failed
-- Performing Test LIBUNWIND_HAS_WORKINGLIBUNWIND
-- Performing Test LIBUNWIND_HAS_WORKINGLIBUNWIND - Failed
-- Checking for modules 'libunwind;libunwind-generic'
--   Package 'libunwind' not found
--   Package 'libunwind-generic' not found
-- Looking for samplerate.h
-- Looking for samplerate.h - not found
-- Found Git: C:/Program Files/Git/mingw64/bin/git.exe (found version "2.50.1.windows.1")
CMake Warning (deprecated) at Engine/lib/sdl/CMakeLists.txt:3300 (cmake_minimum_required):
  Compatibility with CMake < 3.10 will be removed from a future version of
  CMake.

  Update the VERSION argument <min> value.  Or, use the <min>...<max> syntax
  to tell CMake that the project requires at least <min> but has been updated
  to work with policies introduced by <max> or earlier.
This warning is for project developers.  Use -Wno-author or -Wno-deprecated
to suppress it.

-- 
-- SDL2 was configured with the following options:
-- 
-- Platform: Emscripten-1
-- 64-bit:   FALSE
-- Compiler: C:/emsdk/upstream/emscripten/emcc.bat
-- Revision: SDL-2.32.10-g4c44642a
-- 
-- Subsystems:
--   Atomic:	OFF
--   Audio:	ON
--   Video:	ON
--   Render:	ON
--   Events:	ON
--   Joystick:	ON
--   Haptic:	ON
--   Hidapi:	ON
--   Power:	ON
--   Threads:	ON
--   Timers:	ON
--   File:	ON
--   Loadso:	OFF
--   CPUinfo:	OFF
--   Filesystem:	ON
--   Sensor:	ON
--   Locale:	ON
--   Misc:	ON
-- 
-- Options:
--   SDL2_DISABLE_INSTALL        (Wanted: ON): OFF
--   SDL2_DISABLE_SDL2MAIN       (Wanted: OFF): OFF
--   SDL2_DISABLE_UNINSTALL      (Wanted: OFF): OFF
--   SDL_3DNOW                   (Wanted: OFF): OFF
--   SDL_ALSA                    (Wanted: ON): OFF
--   SDL_ALSA_SHARED             (Wanted: ON): OFF
--   SDL_ALTIVEC                 (Wanted: OFF): OFF
--   SDL_ARMNEON                 (Wanted: OFF): OFF
--   SDL_ARMSIMD                 (Wanted: OFF): OFF
--   SDL_ARTS                    (Wanted: ON): OFF
--   SDL_ARTS_SHARED             (Wanted: ON): OFF
--   SDL_ASAN                    (Wanted: OFF): OFF
--   SDL_ASSEMBLY                (Wanted: OFF): OFF
--   SDL_ASSERTIONS              (Wanted: auto): auto
--   SDL_BACKGROUNDING_SIGNAL    (Wanted: OFF): OFF
--   SDL_CCACHE                  (Wanted: ON): OFF
--   SDL_CLOCK_GETTIME           (Wanted: ON): ON
--   SDL_COCOA                   (Wanted: OFF): OFF
--   SDL_DBUS                    (Wanted: ON): OFF
--   SDL_DIRECTFB                (Wanted: OFF): OFF
--   SDL_DIRECTFB_SHARED         (Wanted: OFF): OFF
--   SDL_DIRECTX                 (Wanted: OFF): OFF
--   SDL_DISKAUDIO               (Wanted: ON): ON
--   SDL_DUMMYAUDIO              (Wanted: ON): ON
--   SDL_DUMMYVIDEO              (Wanted: ON): ON
--   SDL_ESD                     (Wanted: ON): OFF
--   SDL_ESD_SHARED              (Wanted: ON): OFF
--   SDL_FOREGROUNDING_SIGNAL    (Wanted: OFF): OFF
--   SDL_FUSIONSOUND             (Wanted: OFF): OFF
--   SDL_FUSIONSOUND_SHARED      (Wanted: OFF): OFF
--   SDL_GCC_ATOMICS             (Wanted: ON): ON
--   SDL_HIDAPI                  (Wanted: ON): OFF
--   SDL_HIDAPI_JOYSTICK         (Wanted: ON): OFF
--   SDL_HIDAPI_LIBUSB           (Wanted: OFF): OFF
--   SDL_IBUS                    (Wanted: ON): OFF
--   SDL_INSTALL_TESTS           (Wanted: OFF): OFF
--   SDL_JACK                    (Wanted: ON): OFF
--   SDL_JACK_SHARED             (Wanted: ON): OFF
--   SDL_KMSDRM                  (Wanted: ON): OFF
--   SDL_KMSDRM_SHARED           (Wanted: ON): OFF
--   SDL_LASX                    (Wanted: OFF): OFF
--   SDL_LIBC                    (Wanted: ON): ON
--   SDL_LIBICONV                (Wanted: OFF): OFF
--   SDL_LIBSAMPLERATE           (Wanted: ON): OFF
--   SDL_LIBSAMPLERATE_SHARED    (Wanted: ON): OFF
--   SDL_LIBUDEV                 (Wanted: ON): OFF
--   SDL_LSX                     (Wanted: OFF): OFF
--   SDL_METAL                   (Wanted: OFF): OFF
--   SDL_MMX                     (Wanted: OFF): OFF
--   SDL_NAS                     (Wanted: ON): OFF
--   SDL_NAS_SHARED              (Wanted: ON): OFF
--   SDL_OFFSCREEN               (Wanted: ON): ON
--   SDL_OPENGL                  (Wanted: ON): OFF
--   SDL_OPENGLES                (Wanted: ON): ON
--   SDL_OSS                     (Wanted: ON): OFF
--   SDL_PIPEWIRE                (Wanted: ON): OFF
--   SDL_PIPEWIRE_SHARED         (Wanted: ON): OFF
--   SDL_PTHREADS                (Wanted: OFF): OFF
--   SDL_PTHREADS_SEM            (Wanted: OFF): OFF
--   SDL_PULSEAUDIO              (Wanted: ON): OFF
--   SDL_PULSEAUDIO_SHARED       (Wanted: ON): OFF
--   SDL_RENDER_D3D              (Wanted: OFF): OFF
--   SDL_RENDER_METAL            (Wanted: OFF): OFF
--   SDL_RPATH                   (Wanted: ON): OFF
--   SDL_RPI                     (Wanted: ON): OFF
--   SDL_SNDIO                   (Wanted: ON): OFF
--   SDL_SNDIO_SHARED            (Wanted: ON): OFF
--   SDL_SSE                     (Wanted: OFF): OFF
--   SDL_SSE2                    (Wanted: OFF): OFF
--   SDL_SSE3                    (Wanted: OFF): OFF
--   SDL_SSEMATH                 (Wanted: OFF): OFF
--   SDL_STATIC_PIC              (Wanted: OFF): OFF
--   SDL_SYSTEM_ICONV            (Wanted: ON): ON
--   SDL_TESTS                   (Wanted: OFF): OFF
--   SDL_VENDOR_INFO             (Wanted: ): OFF
--   SDL_VIRTUAL_JOYSTICK        (Wanted: ON): ON
--   SDL_VIVANTE                 (Wanted: ON): OFF
--   SDL_VULKAN                  (Wanted: OFF): OFF
--   SDL_WASAPI                  (Wanted: OFF): OFF
--   SDL_WAYLAND                 (Wanted: ON): OFF
--   SDL_WAYLAND_LIBDECOR        (Wanted: ON): OFF
--   SDL_WAYLAND_LIBDECOR_SHARED (Wanted: ON): OFF
--   SDL_WAYLAND_QT_TOUCH        (Wanted: ON): OFF
--   SDL_WAYLAND_SHARED          (Wanted: ON): OFF
--   SDL_X11                     (Wanted: ON): OFF
--   SDL_X11_SHARED              (Wanted: ON): OFF
--   SDL_X11_XCURSOR             (Wanted: ON): OFF
--   SDL_X11_XDBE                (Wanted: ON): OFF
--   SDL_X11_XFIXES              (Wanted: ON): OFF
--   SDL_X11_XINPUT              (Wanted: ON): OFF
--   SDL_X11_XRANDR              (Wanted: ON): OFF
--   SDL_X11_XSCRNSAVER          (Wanted: ON): OFF
--   SDL_X11_XSHAPE              (Wanted: ON): OFF
--   SDL_XINPUT                  (Wanted: OFF): OFF
-- 
--  CFLAGS:         -idirafter "I:/BeamNGWeb/third_party/Torque3D/Engine/lib/sdl/src/video/khronos"
--  EXTRA_CFLAGS:   -Wall -Wundef -fno-strict-aliasing -Wdocumentation -Wdocumentation-unknown-command -fcomment-block-commands=threadsafety -fcomment-block-commands=deprecated -Wdeclaration-after-statement -fvisibility=hidden -Wshadow -Wno-unused-local-typedefs
--  EXTRA_LDFLAGS:  
--  EXTRA_LIBS:    m
-- 
--  Build Shared Library: ON
--  Build Static Library: OFF
-- 
-- If something was not detected, although the libraries
-- were installed, then make sure you have set the
-- CFLAGS and LDFLAGS environment variables correctly.
-- 
CMake Warning (author) at Engine/lib/sdl/CMakeLists.txt:3448 (add_library):
  ADD_LIBRARY called with SHARED option but the target platform does not
  support dynamic linking.  Building a STATIC library instead.  This may lead
  to problems.
This warning is for project developers.  Use -Wno-author to suppress it.

-- Checking for module 'gtk+-3.0'
--   Package 'gtk+-3.0' not found
CMake Error at C:/Program Files/CMake/share/cmake-4.4/Modules/FindPkgConfig.cmake:1093 (message):
  The following required packages were not found:

   - gtk+-3.0

Call Stack (most recent call first):
  C:/Program Files/CMake/share/cmake-4.4/Modules/FindPkgConfig.cmake:1166 (_pkg_check_modules_internal)
  Engine/lib/nativeFileDialogs/CMakeLists.txt:16 (pkg_check_modules)


-- Configuring incomplete, errors occurred!
emcmake: error: 'cmake -S third_party/Torque3D -B build/web-t3d -DCMAKE_TOOLCHAIN_FILE=I:/BeamNGWeb/cmake/toolchains/emscripten.cmake -DTORQUE_APP_NAME=BaseGame -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_CROSSCOMPILING_EMULATOR=C:/emsdk/node/22.16.0_64bit/bin/node.exe -G 'MinGW Makefiles'' failed (returned 1)
```

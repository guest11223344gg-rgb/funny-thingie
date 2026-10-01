# cmake/torque3d-emscripten.cmake
#
# Tracked overrides for configuring upstream Torque3D under Emscripten.
#
# Consumed as:
#     -DCMAKE_PROJECT_INCLUDE="$PWD/cmake/torque3d-emscripten.cmake"
# so that third_party/Torque3D stays a pristine, disposable checkout (plan
# constraint: every change to Torque3D's build lives in a tracked file).
#
# ---------------------------------------------------------------------------
# WHEN THIS FILE RUNS, AND WHY THAT MATTERS
# ---------------------------------------------------------------------------
# CMAKE_PROJECT_INCLUDE is processed immediately AFTER the top-level
# project() call in third_party/Torque3D/CMakeLists.txt:22. The order is:
#
#   1. CMakeLists.txt:19  include(Tools/CMake/torque_configs.cmake)
#   2. CMakeLists.txt:22  project(${TORQUE_APP_NAME})   <- toolchain file loads,
#                                                          then THIS file runs
#   3. CMakeLists.txt:85  add_subdirectory(Engine)
#
# CMake initialises WIN32/UNIX/APPLE from the *host* until project() replaces
# them with target values. Verified on this machine:
#
#   BEFORE project(): WIN32=[1] UNIX=[]   APPLE=[]   (host is Windows)
#   AFTER  project(): WIN32=[]  UNIX=[1]  APPLE=[]   (Emscripten target)
#
# torque_configs.cmake runs at step 1, i.e. in the window where WIN32=1. That
# is why an Emscripten configure still picks the Windows-host vcpkg triplet
# (x64-windows-mixed) and still defaults TORQUE_D3D11 ON. By step 3, WIN32 is
# empty and UNIX=1, so every `if(UNIX AND NOT APPLE)` branch in Engine/ is
# taken instead. The configure is therefore a Windows-host/Linux-target hybrid.
#
# Everything below is a CACHE variable set FORCE, because the code that reads
# it lives in files processed at step 3, after this file has run.

# --- WIN32 as an expandable token -------------------------------------------
# torque_configs.cmake:106-108 does:
#     if(NOT WIN32)
#        set(WIN32 OFF CACHE BOOL "" FORCE)
#     endif()
# On a *non-Windows host* that block runs, so WIN32 becomes the defined string
# "OFF", and any `advanced_option(... ${WIN32})` downstream expands to a valid
# third argument. On this Windows host WIN32=1 at that moment (the host-value
# window described above), so the block is skipped and WIN32 is never put in
# the cache. After project() the Emscripten toolchain sets WIN32 to empty, and
# `${WIN32}` then expands to *nothing* -- collapsing macro calls to two
# arguments. Observed first failure of run 2:
#     CMake Error at Engine/lib/CMakeLists.txt:226 (advanced_option):
#       advanced_option Macro invoked with incorrect arguments for macro named:
#       advanced_option
# on the line `advanced_option(ALSOFT_EAX "..." ${WIN32})`.
#
# Setting WIN32=OFF in the cache reproduces exactly the state upstream creates
# for itself on non-Windows hosts. `if(WIN32)` still evaluates false (CMake
# reads "OFF" as false); the only effect is that `${WIN32}` expands to a token
# instead of vanishing.
set(WIN32 OFF CACHE BOOL "" FORCE)

# --- Renderer selection -----------------------------------------------------
# TORQUE_D3D11 defaults ON in torque_configs.cmake:143-146, guarded by
# `if(WIN32)` -- which is true at that point because the host is Windows. D3D11
# can never be valid for a wasm target and must be forced off.
set(TORQUE_D3D11 OFF CACHE BOOL "Allow Direct3D 11 render" FORCE)

# GLES3/WebGL2 is the only renderer a browser can present. This is already the
# upstream default (torque_configs.cmake:142); pinned here so the intent is
# explicit and survives any future default change.
set(TORQUE_OPENGL ON CACHE BOOL "Allow OpenGL render" FORCE)

# SDL is the platform interop layer. Engine/source/CMakeLists.txt:30 forces
# this ON unconditionally; declared here so the override set is self-describing.
set(TORQUE_SDL ON CACHE BOOL "Use SDL for platform interop" FORCE)

# --- nativeFileDialogs ------------------------------------------------------
# torque_configs.cmake:130 defaults TORQUE_USE_ZENITY OFF, so
# Engine/lib/nativeFileDialogs/CMakeLists.txt:11-16 takes the `elseif(UNIX)` /
# `else()` path and runs:
#     find_package(PkgConfig REQUIRED)
#     pkg_check_modules(GTK3 REQUIRED gtk+-3.0)
# Under Emscripten that resolves PKG_CONFIG_EXECUTABLE to the *host* MSYS2
# pkg-config (observed: C:/msys64/ucrt64/bin/pkg-config.exe), which cannot
# supply GTK3, and configure dies there. This was the first real failure of the
# unpatched configure.
#
# Selecting the Zenity backend skips the GTK3 find_package entirely.
# CAVEAT, recorded honestly: this swaps the NFD backend, it does NOT exclude the
# library. nfd_zenity.c still has to compile in Task 8, and Zenity itself is a
# host subprocess with no browser equivalent -- the library is still wrong for
# this target, it just no longer breaks *configure*.
set(TORQUE_USE_ZENITY ON CACHE BOOL "Use the Zenity backend for NFD" FORCE)

# --- Freetype: NO BYPASS PROVIDED, ON PURPOSE --------------------------------
# Engine/source/CMakeLists.txt:60, inside `if (UNIX AND NOT APPLE)`, runs
# find_package(Freetype REQUIRED). Emscripten sets UNIX=1, so this branch is
# taken. Probed in isolation: FindFreetype returns Freetype_FOUND=FALSE under
# the Emscripten toolchain, and the Emscripten sysroot contains no freetype
# headers or libraries until the port is materialised, so there is nothing to
# point FREETYPE_INCLUDE_DIRS / FREETYPE_LIBRARY at.
#
# There is therefore no honest bypass reachable from this file. The real fix is
# to stop Emscripten being classified as UNIX/Linux for platform purposes (the
# X11 branch, platformPOSIX and platformX86UNIX are all wrong for a browser),
# which requires a change inside the engine tree that this task's rules forbid.
# Deliberately NOT worked around; recorded in
# docs/findings/m0-emscripten-configure.md instead.

@echo off
REM scripts/build-native.cmd -- configure and build Torque3D BaseGame for Windows.
REM Run from the repository root: cmd //c scripts\build-native.cmd
setlocal

set T3D=third_party\Torque3D
set BUILD=build\native

REM cmake is not on PATH on this machine, so resolve it explicitly: prefer a
REM PATH copy, fall back to the winget install, and fail with a named error.
set CMAKE_BIN=
where cmake >nul 2>nul && set "CMAKE_BIN=cmake"
if not defined CMAKE_BIN if exist "C:\Program Files\CMake\bin\cmake.exe" set "CMAKE_BIN=C:\Program Files\CMake\bin\cmake.exe"
if not defined CMAKE_BIN (
  echo ERROR: cmake not found on PATH or at C:\Program Files\CMake\bin\cmake.exe.
  echo        Install it with: winget install Kitware.CMake
  exit /b 1
)

if not exist "%T3D%\CMakeLists.txt" (
  echo ERROR: %T3D% not found. Run scripts/fetch-torque3d.sh first.
  exit /b 1
)

REM vcpkg supplies the six audio codec libraries declared in vcpkg.json.
REM Torque3D's Tools/CMake/torque_configs.cmake picks up %VCPKG_ROOT% when it is
REM set and otherwise clones and bootstraps its own checkout under %BUILD%\vcpkg,
REM so a separate install at C:\vcpkg is not required. Fail early only when
REM neither route is available.
set VCPKG_PRESENT=
if defined VCPKG_ROOT set "VCPKG_PRESENT=%VCPKG_ROOT%"
if exist "C:\vcpkg\scripts\buildsystems\vcpkg.cmake" set "VCPKG_PRESENT=C:\vcpkg"
if exist "%BUILD%\vcpkg\scripts\buildsystems\vcpkg.cmake" set "VCPKG_PRESENT=%BUILD%\vcpkg"
if not defined VCPKG_PRESENT (
  where git >nul 2>nul
  if errorlevel 1 (
    echo ERROR: no vcpkg found and git is not on PATH, so Torque3D cannot bootstrap one.
    echo        Install vcpkg or git; see docs/build-native.md.
    exit /b 1
  )
  echo vcpkg not found; Torque3D will bootstrap one under %BUILD%\vcpkg.
)

"%CMAKE_BIN%" -S "%T3D%" -B "%BUILD%" -G "Visual Studio 17 2022" -A x64 ^
  -DTORQUE_APP_NAME=BaseGame ^
  -DTORQUE_TESTING=ON ^
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
if errorlevel 1 exit /b 1

"%CMAKE_BIN%" --build "%BUILD%" --config RelWithDebInfo --parallel
if errorlevel 1 exit /b 1

echo Built to %BUILD%

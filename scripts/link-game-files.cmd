@echo off
REM scripts/link-game-files.cmd -- junction game-files\assets into the game tree.
REM
REM WHY THIS EXISTS
REM
REM BeamNG-derived content cannot be committed (see
REM docs/findings/beamng-redistribution-policy.md), but it also should not live
REM inside third_party\Torque3D\, which scripts/fetch-torque3d.sh may re-clone
REM and which is git-ignored and treated as disposable. So the converted module
REM tree lives at the repository root, in game-files\assets\.
REM
REM The engine cannot simply be pointed there. winVolume.cpp:742 shows that
REM Platform::FS::getAssetDir() returns the directory holding the executable,
REM and platformVolume.cpp:47 mounts that as "game:". Every relative path in
REM main.tscript -- core, data, tools -- resolves against it. The module also has
REM to be reachable as data\<module> for main.tscript's
REM ModuleDatabase.scanModules("data", false) to discover it at all.
REM
REM So: one directory junction, from the engine's expected location to the real
REM one. A junction needs no administrator rights and is transparent to the
REM Win32 file APIs the engine uses, so no engine patch and no rebuild.
REM
REM Idempotent. Safe to re-run, and worth re-running after any re-fetch of
REM third_party\Torque3D, which would otherwise leave the link missing.
setlocal

set ROOT=%~dp0..
set LINK=%ROOT%\third_party\Torque3D\My Projects\BaseGame\game\data\BeamNGMaps
set TARGET=%ROOT%\game-files\assets\BeamNGMaps

if not exist "%ROOT%\third_party\Torque3D\My Projects\BaseGame\game\data" (
  echo ERROR: the BaseGame game\data directory does not exist yet.
  echo        Build the game first: scripts\build.sh native
  exit /b 1
)

if not exist "%TARGET%" (
  echo ERROR: %TARGET% does not exist.
  echo        Convert a level first, e.g.:
  echo          python tools\steam-level.py gridmap_v2
  exit /b 1
)

REM Is something already sitting at the link path?
if exist "%LINK%" (
  REM fsutil reparsepoint query succeeds only for a junction or symlink. If it
  REM fails, this is a real directory holding real files and must not be
  REM touched -- that would be exactly the kind of silent data loss this script
  REM exists to avoid.
  fsutil reparsepoint query "%LINK%" >nul 2>nul
  if errorlevel 1 (
    echo ERROR: %LINK% exists and is a real directory, not a junction.
    echo        Refusing to touch it. Inspect it, move it aside, and re-run.
    exit /b 1
  )
  REM NO TRAILING BACKSLASH. rmdir on a junction removes the link itself; with a
  REM trailing slash it would recurse through the link and delete the TARGET's
  REM contents. This single character is the difference between relinking and
  REM destroying 282 MB of converted terrain.
  rmdir "%LINK%"
  if errorlevel 1 (
    echo ERROR: could not remove the existing junction at %LINK%
    exit /b 1
  )
)

REM /J makes a directory junction: no admin rights, no elevation prompt.
mklink /J "%LINK%" "%TARGET%"
if errorlevel 1 (
  echo ERROR: mklink /J failed.
  exit /b 1
)

echo Linked:
echo   %LINK%
echo     -^> %TARGET%
endlocal

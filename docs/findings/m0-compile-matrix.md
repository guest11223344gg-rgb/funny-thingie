# Torque3D incremental wasm compile matrix (M0a, Task 8)

**Probe, not a build.** This document records what happens when Torque3D's
translation units are compiled to wasm one at a time. It is the input to the M0b
porting plan: it says which subsystems resist the Emscripten toolchain and
roughly why, so the plan can attack them in a sensible order.

Pinned revision: `4c44642aab32cf79be4f66966d49fd74ab18e221`.
Toolchain: Emscripten 4.0.9, `-std=c++23`, `-pthread`.

> **Read the limits section before quoting any row.** "Compiled" here means one
> translation unit produced an object file. It does **not** mean the subsystem
> builds, links, or runs. Nothing in this probe was linked.

---

## 0. Provenance — weaker scrutiny than its neighbours

Task 8's implementer was terminated partway through by an API quota error, not by
anything in the task:

```
HTTP 403 pre-consume quota failed, user quota: $0.190398, need quota: $0.238570
```

It left a working harness, 28 completed logs and a clean tree. The controller
finished the remaining sweep and wrote this document.

**Consequence, stated plainly:** this document is the only artifact in M0a with no
implementer-side review, and the whole-branch review that would normally catch
that is itself blocked by the same quota. Treat it as less verified than
`m0-emscripten-configure.md`, which was independently reviewed against its raw
logs. The method and the exact flags are recorded in section 6 so the result can
be rechecked rather than trusted.

---

## 1. Method

Torque3D's own CMake cannot drive this: its configure fails outright under
Emscripten (see `m0-emscripten-configure.md`), and repairing it is M0b work. So
each translation unit was compiled directly, bypassing CMake entirely:

```bash
unset CC CXX                      # an inherited CC shadows emcc and silently wins
EMCC=/c/emsdk/upstream/emscripten/emcc
"$EMCC" -c <file.cpp> -o out.o \
  -std=c++23 -pthread \
  -I<include paths> -D<defines>
```

Defines, fixed for every row:

```
-Dlinux -D__x86_64__ -D__linux__ -DTORQUE_OPENGL -DTORQUE_SDL
-DTORQUE_ADVANCED_LIGHTING -DTORQUE_BASIC_LIGHTING -DTORQUE_OGGVORBIS
-DTORQUE_OGGTHEORA -DTORQUE_RELEASE -DTORQUE_ENABLE_ASSERTS
-DTORQUE_DEBUG_GFX_MODE
```

`-Dlinux -D__linux__` is a **deliberate controller choice**, not something
Torque3D's build sets. It selects the Linux code paths, which is the half of the
configure's Windows-host/Linux-target hybrid that Emscripten would actually take
once the configure gets far enough to choose. It is a hypothesis about the target,
and the rows below are conditional on it.

`-pthread` and the atomics/bulk-memory flags it implies are present, matching
`m0-threading-smoke`'s finding that the engine's job system needs threads.

Representative files were chosen to spread across each directory rather than to
exhaust it — 84 translation units across 19 directories, 1 to 7 per directory.

### Include resolution rule

An unresolved `#include` is a missing `-I` on this command line, **not** a
portability finding. The first sweep surfaced 23 rows failing on
`fatal error: 'dom/domTypes.h' file not found`; that header is at
`Engine/lib/collada/include/1.4/dom/domTypes.h`, so the fix was one more `-I` on
the command line, not a source change. The full sweep was re-run with it added so
that all 84 rows share one configuration. **The results below are the corrected
run.** The superseded run is not quoted anywhere in this document.

That rule matters: row `ts/tsMesh.cpp` failed on the missing include in the first
run and only revealed its real error once the include was fixed (section 4.3).

---

## 2. The matrix

84 rows. **80 compiled, 3 failed, 1 could not be compiled as posed.**

| Directory | Rows | Result | Representative translation units |
|---|---|---|---|
| `core` | 6 | **6 pass** | `tokenizer.cpp`, `stringTable.cpp`, `frameAllocator.cpp`, `util/refBase.cpp`, `stream/fileStream.cpp`, `util/zip/zipArchive.cpp` |
| `math` | 5 | 4 pass, **1 fail** | `mMatrix.cpp`, `mMath_C.cpp`, `mRandom.cpp`, `mQuat.cpp`, `mMathSSE.cpp` — see 4.1 |
| `util` | 4 | **4 pass** | `settings.cpp`, `noise2d.cpp`, `sampler.cpp`, `quadTreeTracer.cpp` |
| `console` | 6 | **6 pass** | `console.cpp`, `consoleInternal.cpp`, `consoleObject.cpp`, `consoleTypes.cpp`, `engineExports.cpp`, `torquescript/parser.cpp` |
| `platform` | 7 | 6 pass, **1 blocked** | `platform.cpp`, `platformCPU.cpp`, `platformFileIO.cpp`, `platformFont.cpp`, `platformNet.cpp`, `platformTimer.cpp`, `platformMemory.cpp` — see 4.4 |
| `platformSDL` | 5 | **5 pass** | `sdlPlatform.cpp`, `sdlPlatformGL.cpp`, `sdlInput.cpp`, `sdlCPUInfo.cpp`, `sdlMsgBox.cpp` |
| `platformPOSIX` | 6 | 5 pass, **1 fail** | `POSIXFileio.cpp`, `POSIXConsole.cpp`, `POSIXTime.cpp`, `POSIXUtils.cpp`, `POSIXGL.client.cpp`, `POSIXMath.cpp` — see 4.2 |
| `windowManager` | 4 | **4 pass** | `platformWindow.cpp`, `platformInterface.cpp`, `sdl/sdlWindow.cpp`, `platformCursorController.cpp` |
| `gfx/gl` | 6 | **6 pass** | `gfxGLDevice.cpp`, `gfxGLShader.cpp`, `gfxGLTextureObject.cpp`, `gfxGLStateBlock.cpp`, `sdl/gfxGLDevice.sdl.cpp`, `tGL/tGL.cpp` |
| `shaderGen` | 4 | **4 pass** | `shaderGen.cpp`, `shaderOp.cpp`, `GLSL/shaderGenGLSL.cpp`, `featureMgr.cpp` |
| `materials` | 4 | **4 pass** | `materialDefinition.cpp`, `matInstance.cpp`, `materialManager.cpp`, `processedShaderMaterial.cpp` |
| `scene` | 4 | **4 pass** | `sceneObject.cpp`, `sceneManager.cpp`, `sceneRenderState.cpp`, `sgUtil.cpp` |
| `ts` | 4 | 3 pass, **1 fail** | `tsShape.cpp`, `tsShapeInstance.cpp`, `tsMaterialList.cpp`, `tsMesh.cpp` — see 4.3 |
| `terrain` | 3 | **3 pass** | `terrData.cpp`, `terrRender.cpp`, `terrCell.cpp` |
| `sfx` | 4 | **4 pass** | `sfxSystem.cpp`, `sfxBuffer.cpp`, `sfxDevice.cpp`, `sfxSound.cpp` |
| `app` | 3 | **3 pass** | `game.cpp`, `mainLoop.cpp`, `version.cpp` |
| `main` | 1 | **1 pass** | `main.cpp` |
| `gui` | 4 | **4 pass** | `guiCanvas.cpp`, `guiControl.cpp`, `guiTextCtrl.cpp`, `guiListBoxCtrl.cpp` |
| `T3D` | 4 | **4 pass** | `Scene.cpp`, `gameFunctions.cpp`, `camera.cpp`, `gameBase/gameConnection.cpp` |

15 of 19 directories compiled every file tried. The four that did not are
`math`, `platform`, `platformPOSIX` and `ts` — and in three of those four the
failure is a single file with a single cause.

---

## 3. The finding that is not a failure, and matters most

**`S64` and `U64` are 32 bits wide in this build.** It produces warnings, not
errors, so nothing above fails because of it — which is exactly why it is
dangerous.

`Engine/source/platform/types.h:126` includes `platform/types.gcc.h`, which does:

```c
// Engine/source/platform/types.gcc.h:33-39
#if defined(TORQUE_X86)
typedef signed long long    S64;
typedef unsigned long long  U64;
#else
typedef signed long    S64;
typedef unsigned long  U64;
#endif
```

`TORQUE_X86` appears **exactly once in the entire `Engine/` tree** — at that
`#if`. Nothing defines it; not the CMake files, not any source header. The
branch is dead code and the `#else` is always taken.

On the targets Torque3D was written for this is accidentally correct: under LP64
(Linux x86-64, macOS) `long` is 64 bits, so the `#else` branch gives a genuine
64-bit type. Emscripten is ILP32 — `long` is 32 bits — so the same branch
silently yields a 32-bit "64-bit" integer.

The compiler says so, if you look:

```
Engine/source/core/util/timeClass.h:65:39: warning: implicit conversion from
  'long long' to 'const S64' (aka 'const long') changes value from 8640000000
  to 50065408 [-Wconstant-conversion]
```

`8640000000` (100 days in milliseconds) truncates to `50065408`. This warning
appears in **44 of the 84 logs**. A companion symptom,
`timeClass.h:275:25: warning: shift count >= width of type`, is the same root
cause.

**Why this matters more than any of the four hard failures:** a compiler error
stops you and tells you where. This does not. Every `S64` in the engine —
timestamps, file offsets, GUIDs, and the tick arithmetic the simulation is built
on — becomes a silently wrapping 32-bit value in the browser build. It would
present as inexplicable timing drift and corrupt asset reads, far from the cause.

**Status: observed, not inferred.** The warning text and the truncation value are
in the raw logs. The attribution to `types.gcc.h` is by direct reading of the
header and a whole-tree search for the guard. What is *not* established is how
much of the engine breaks because of it — that requires the link-and-run step
this probe cannot do.

**Candidate fix (untested):** define `TORQUE_X86`, or correct the guard to test
pointer width rather than CPU family. Note that defining `TORQUE_X86` on a
non-x86 target is a lie that happens to work, so the guard is the honest fix.

---

## 4. The four rows that did not compile

### 4.1 `math/mMathSSE.cpp` — hand-written x86 assembly

```
Engine/source/math/mMathSSE.cpp:286:9: error: invalid input constraint 'd' in asm
Engine/source/math/mMathSSE.cpp:369:6: error: invalid input constraint 'd' in asm
```

The `'d'` constraint is the x86 `edx` register. wasm has no register-named
constraints. **Bounded:** the file is x86-specific by name and by construction,
and `mMath_C.cpp` — the portable C fallback — compiles clean. The porting
question is whether the build can be steered to the C path rather than whether
this file can be repaired.

### 4.2 `platformPOSIX/POSIXMath.cpp` — x87 floating-point control

```
Engine/source/platformPOSIX/POSIXMath.cpp:120:8: error: invalid operand in inline asm: 'fstcw $0'
Engine/source/platformPOSIX/POSIXMath.cpp:120:8: error: invalid instruction
Engine/source/platformPOSIX/POSIXMath.cpp:127:8: error: invalid operand in inline asm: 'fldcw $0'
Engine/source/platformPOSIX/POSIXMath.cpp:133:8: error: invalid operand in inline asm: 'fldcw $0'
```

`fstcw`/`fldcw` save and restore the x87 FPU control word, used here to set
rounding and precision modes. wasm has no x87 unit and no FPU control word; its
floating-point semantics are fixed. **Not a mechanical port** — the operations
have no wasm equivalent, so this is a behavioural question (what should rounding
mode mean in wasm?) rather than a syntax fix. Small file, real design decision.

### 4.3 `ts/tsMesh.cpp` — `__declspec` in the bundled Opcode library

```
Engine/lib/opcode/./Ice/IceFPU.h:342:11: error: '__declspec' attributes are not
  enabled; use '-fdeclspec' or '-fms-extensions' to enable support for
  __declspec attributes
... (20 errors, same cause, lines 342-347 and the ICECORE_API macro)
fatal error: too many errors emitted, stopping now [-ferror-limit=]
5 warnings and 20 errors generated.
```

Note this row only revealed this error **after** the COLLADA include path was
fixed — in the first sweep it died earlier, on the missing header. A probe that
had recorded the first error and stopped would have reported the wrong cause.

The cause is in a *bundled third-party library*, not in Torque3D's own code:
`ICE_CORE_API` expands to `__declspec(dllexport)`, MSVC syntax. **Bounded and
likely cheap:** `-fdeclspec` makes clang parse it as a no-op, and on a static
wasm build the import/export semantics it requests are meaningless anyway. The
hazard is that this repeats wherever Opcode's headers are included.

### 4.4 `platform/platformMemory.cpp` — `execinfo.h` does not exist on Emscripten

```
Engine/source/platform/platformMemory.cpp:38:10: fatal error: 'execinfo.h' file not found
```

`execinfo.h` is glibc's `backtrace()` API. Emscripten has no such header and no
equivalent. Unlike the 23 COLLADA rows, **this is not a missing `-I`** — the
header genuinely does not exist for this target.

**Bounded:** the include is guarded by platform macros that select the POSIX path
here; the fix is to add an Emscripten branch that omits the backtrace support and
stubs whatever consumes it. This is the ordinary shape of a platform port, and it
is the only such row in 84.

---

## 5. What this probe does not establish

Stated so the matrix is not read as a stronger result than it is:

- **Nothing was linked.** Every row is one translation unit producing one object
  file. Unresolved symbols, duplicate definitions, link ordering, and static
  initialisation order are all **untested**. A directory with 6/6 passing rows is
  not a subsystem that builds.
- **Nothing was run.** No wasm binary was produced, loaded, or executed.
- **The file selection is representative, not exhaustive.** 84 files of a much
  larger tree. A directory marked "all pass" means every file *tried* passed.
- **Rows are conditional on the define set in section 1**, and in particular on
  `-Dlinux`. Different defines select different platform paths and would produce a
  different matrix.
- **The `-I` list was assembled by iteration**, adding paths as errors demanded.
  It is recorded in full so it can be reproduced, but it is not a claim about
  what the correct include set ought to be.
- **Warnings were not triaged.** 46 of 84 logs contain warnings. Only the `S64`
  family (section 3) was investigated; the rest are unexamined, and the
  `S64` finding is a warning that an error-only sweep would have missed entirely.

---

## 6. Reproducing

Harness: `docs/findings/m0-compile-matrix-harness.sh` (the sweep driver — it
compiles each listed file with the flags above and writes one log per file).
Raw logs for the four rows that did not pass are committed as
`m0-compile-matrix-failures.txt`. The 80 passing rows are not committed
individually; the driver regenerates them.

```bash
source /c/emsdk/emsdk_env.sh
unset CC CXX
bash docs/findings/m0-compile-matrix-harness.sh
```

---

## 7. Corrections to the task brief's expectations

The brief listed four areas it expected to be difficult, based on reading the
source. Verified against the matrix:

1. **"`platformSDL/sdlPlatformGL.cpp` and `gfx/gl/sdl/gfxGLDevice.sdl.cpp` — SDL
   GL context attributes are desktop-GL shaped; ES needs a different profile
   request."** — **Both compiled clean.** No translation-unit-level problem. The
   concern may still be real at runtime (an ES profile request is a *behavioural*
   difference, invisible to the compiler), so this is not a refutation — but it
   is not a compile-time cost, and the brief implied one.
2. **"`gfx/gl/tGL/tWGL.h` and `tXGL.h` — loaders for Windows and X11 GL.
   Emscripten needs a third path; this is likely the single largest item."** —
   `tGL/tGL.cpp` **compiled clean** under `-Dlinux`. The loaders may still need
   an Emscripten path for correctness, but they are not a compile blocker, and
   the brief's "likely the single largest item" is not supported at this level.
3. **"`shaderGen/GLSL/shaderGenGLSL.cpp` — emits desktop GLSL; `#version 300 es`,
   precision qualifiers, `in`/`out` in place of `varying`/`attribute`."** —
   **Compiled clean.** This is a runtime output question: the file generates GLSL
   as *text*, so its correctness is invisible to the C++ compiler. The brief's
   item is real work but it is not a compile failure, and this matrix cannot
   measure it either way.
4. **"`app/game.cpp`, `main/main.cpp` — a `while` main loop must become
   `emscripten_set_main_loop`."** — **Both compiled clean.** Same reasoning: a
   blocking loop compiles fine and hangs the browser. Real work, invisible here.

**The pattern:** the brief's four predicted hard areas are all *runtime
semantics*, and all four compile clean. The three genuine compile failures are in
places the brief did not name — x86 inline assembly in `math` and `platformPOSIX`,
an MSVC-ism in the bundled Opcode library, and one glibc header. And the most
consequential finding of all is a warning the brief did not anticipate.

The lesson for M0b, and the reason this probe was worth running: source-reading
predicted the wrong failures. The predicted ones are real but they are the ones
that will not stop a build; the ones that stop a build are different, and the one
that will silently corrupt behaviour at runtime is different again.

---

## 8. Input to M0b

Not a plan — the plan is M0b's to write against these findings. Recorded because
the matrix exists to determine order:

- **Bounded and mechanical:** the Opcode `__declspec` row (4.3), the `execinfo.h`
  row (4.4).
- **Bounded but needs a decision:** the `S64` width (section 3) — the fix is
  small, the affected surface is large and must be found.
- **Genuinely hard:** `POSIXMath.cpp`'s x87 control word (4.2) has no wasm
  equivalent and needs a behavioural answer, not a port.
- **Unknown, and deliberately so:** everything the compiler could not see. All
  four of the brief's predicted items are runtime questions, and this probe
  answers none of them. A link-and-run milestone is the only thing that will.

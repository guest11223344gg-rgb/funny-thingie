# M0b: Torque3D on wasm — link, boot, render — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a wasm build of upstream Torque3D that **links, boots in a browser
tab, renders a frame, and accepts keyboard input** — the stock T3D template scene.
That single result validates or refutes whether porting the engine is cheaper than
writing a GLES3 renderer from scratch, which is the gate every later milestone sits
behind.

**Scope note:** This is M0b, the second half of the spec's M0. M0a ended with the
engine neither configuring nor linking — it produced evidence, not a binary. M0b's
deliverable is a running engine. It is **not** M1: no BeamNG content, no `core/`,
no `ZipVFS`, no JBeam, no solver, no UI. The acceptance test is the engine's own
`BaseGame` template scene in a tab.

**Architecture:** Torque3D already uses SDL2 as its universal platform layer
(`Engine/source/CMakeLists.txt:31`, `set(TORQUE_SDL ON)`), and the vendored SDL2 in
`Engine/lib/sdl/` already contains a complete Emscripten backend — M0a verified it
configures as `Platform: Emscripten-1`, `SDL_OPENGLES: ON`. M0b's strategy is to
make **wasm a first-class platform** in Torque3D's build, let SDL's Emscripten
backend carry windowing/input/audio, and add the two things the engine lacks for
this target: an Emscripten GL loader path and a GLSL ES 3.00 shader path. Every
change to upstream lives in a tracked file — a CMake override or a numbered patch —
so `third_party/Torque3D` stays pristine and disposable.

**Tech Stack:** C++17, CMake ≥ 3.21.0, MSVC 14.44 (native), Emscripten 4.0.9, SDL2
(vendored), OpenGL ES 3.0 / WebGL2, Python 3 (dev server), Node + Playwright
(browser harness).

**Spec:** `docs/superpowers/specs/2026-10-01-beamng-browser-port-design.md`

**Findings this plan is built on** (read these first — the plan cites them, and two
of its first tasks exist to correct them):
- `docs/findings/m0-emscripten-configure.md` — why the configure fails, in detail
- `docs/findings/m0-compile-matrix.md` — the 84-row wasm compile sweep
- `docs/findings/m0-summary.md` — the synthesis and the recommendation

---

## Global Constraints

Inherited from M0a and still binding:

- C++ standard is **C++17** — upstream `CMakeLists.txt:2` (`set (CMAKE_CXX_STANDARD 17)`). Do not raise it. Bumping to C++23 to dodge a compile error is forbidden (see Review Focus 5).
- CMake minimum is **3.21.0**.
- `TORQUE_APP_NAME=BaseGame` must be on the configure line.
- Torque3D is pinned at **`4c44642aab32cf79be4f66966d49fd74ab18e221`**. Never build against a floating `development`.
- `third_party/` is **git-ignored**. Torque3D is a fetched dependency.
- `assets/` is **git-ignored**. M0b does not use it.
- **The native PC build must keep working after every task.** A change that breaks it is a task failure, not a follow-up item.
- Web output is served over **localhost with COOP/COEP headers**. `SharedArrayBuffer` and pthreads depend on them.
- `core/` does not exist yet. M0b adds no `core/` code.

New in M0b:

- **Every change to Torque3D lives in a tracked file.** Build-level changes go in `cmake/torque3d-emscripten.cmake` (consumed via `-DCMAKE_PROJECT_INCLUDE=`). Source-level changes go in a numbered patch under `patches/torque3d/`, applied by a tracked script. Editing `third_party/Torque3D` by hand is forbidden — it is disposable and the change vanishes on the next fetch (Review Focus 1).
- **The wasm target must not be steered by host-shaped defines.** M0a's sweep used `-Dlinux -D__x86_64__` on purpose, to test the "configure classifies the target as Linux" hypothesis. Those are probe scaffolding. A real Emscripten build defines neither; it defines `__wasm32__` / `__EMSCRIPTEN__`. Task 2 re-baselines the matrix against the defines emcc actually sets before any failure is sized as work.
- **Do not stub a `find_package` to make configure pass.** A stub `OggConfig.cmake` makes configure *appear* to succeed and then fails at link. M0a refused to do this; M0b refuses too (Review Focus 4).

## Review Focus

M0b's failure modes are different from M0a's. M0a was evidence-gathering; M0b changes
code and links a binary, so its failures are structural and can be silent.

1. **A change made in `third_party/` instead of a tracked file.** The checkout is git-ignored and disposable. A hand-edit there works today and disappears on the next `fetch`, with no error to explain it. Expect the patch script to be the only way upstream source changes.
2. **The define set drifting from reality.** M0a's matrix was swept with `-Dlinux -D__x86_64__`. Two of its four "failures" (`mMathSSE.cpp`, `POSIXMath.cpp`) are x86-only code that a real wasm build would not select. Sizing them as porting work would be sizing a phantom. Expect every claim about "the engine fails to compile" to name the defines it was measured under.
3. **`-pthread` on link but not on compile.** Emscripten splits the flag: `-matomics -mbulk-memory -mthread-model posix` must be on *compile*, `--shared-memory` on *link*. M0a's configure added neither. Omitting the compile half makes `wasm-ld` refuse the link with an error that does not name the missing flag.
4. **Papering over a dependency to reach a green configure.** See Global Constraints. The configure must complete *honestly*, by replacing the six audio `find_package(CONFIG REQUIRED)` calls with a real Emscripten-port path, not by faking config packages.
5. **Dodging `refBase.h:114` by changing the language standard.** The construct is ill-formed before C++23 and MSVC accepts it as an extension. Compiling the wasm target at `-std=c++23` would make the symptom disappear and introduce a language-level divergence between the two targets. Fix the header (Task 1).
6. **The native build breaking silently.** Every task ends by confirming the native build still configures. A change that only builds for wasm is a regression.

---

## Task 1: A tracked patch mechanism, and the `refBase.h:114` fix

The highest-leverage item in M0b, and the first real source change to upstream. It
proves the patch mechanism and takes the pinned-standard sweep from 7 compiling rows
to roughly 80 in one commit.

**Why the mechanism comes first:** every later task patches Torque3D source. If the
mechanism is ad-hoc, changes leak into `third_party/` and vanish on the next fetch
(Review Focus 1). Build the mechanism, use it for one patch, and it is proven.

**The fix.** `Engine/source/core/util/refBase.h:112-118` marks `getPointer()` `constexpr`
and then locks a `weak_ptr` inside it:

```cpp
   [[nodiscard]] constexpr T* getPointer() const
   {
      auto ctrl = mWeak.lock();          // line 114 — not a constant expression pre-C++23
      if (!ctrl || !ctrl->object)
         return NULL;
      return (T*)(ctrl->object);
   }
```

`std::weak_ptr::lock()` cannot be a constant expression, and the local variable it
returns is of non-literal type, which is ill-formed in a `constexpr` function before
C++23. Upstream declares C++17 and MSVC accepts the construct as an extension, so the
native build never saw it. `clang`/`emcc` refuses it, in 77 of the 84 swept rows.

The honest fix is to stop claiming `getPointer()` is `constexpr` — it never was. Its
three callers (`operator->`, `operator*`, `operator T*`, lines 107-109) are also
`constexpr` and also cannot be, so they lose the specifier too.

**Files:**
- Create: `patches/torque3d/0001-refbase-getpointer-not-constexpr.patch`
- Create: `scripts/apply-patches.sh`
- Modify: `scripts/fetch-torque3d.sh` (apply patches after checkout)
- Modify: `scripts/build-web.sh` (assert patches are applied before configuring)
- Modify: `scripts/build.sh` (add a `patch` stage)
- Modify: `docs/build-environment.md` (record the patch mechanism)

**Interfaces:**
- Consumes: `third_party/Torque3D` at the pin (M0a Task 2).
- Produces: `scripts/apply-patches.sh` — idempotent, exits 0 when `third_party/Torque3D` carries every patch in `patches/torque3d/`, applied in filename order. Every later task adds a patch and re-runs it.

- [ ] **Step 1: Write the patch**

`patches/torque3d/0001-refbase-getpointer-not-constexpr.patch` — a `git diff` against
the pinned tree. Generate it by editing a scratch copy, never the live checkout:

```diff
--- a/Engine/source/core/util/refBase.h
+++ b/Engine/source/core/util/refBase.h
@@ -104,16 +104,16 @@
    bool isValid() const { return getPointer() != NULL; }
    bool isNull() const { return getPointer() == NULL; }
    
-   [[nodiscard]] constexpr T* operator->()      const { return getPointer(); }
-   [[nodiscard]] constexpr T& operator*()       const { return *getPointer(); }
-   [[nodiscard]] constexpr operator T*()        const { return getPointer(); }
+   [[nodiscard]] T* operator->()      const { return getPointer(); }
+   [[nodiscard]] T& operator*()       const { return *getPointer(); }
+   [[nodiscard]] operator T*()        const { return getPointer(); }
    
    /// Returns the pointer.
-   [[nodiscard]] constexpr T* getPointer() const
+   [[nodiscard]] T* getPointer() const
    {
       auto ctrl = mWeak.lock();
```

- [ ] **Step 2: Write the apply script**

`scripts/apply-patches.sh`:

```bash
#!/usr/bin/env bash
# scripts/apply-patches.sh — apply every tracked Torque3D patch, idempotently.
#
# third_party/Torque3D is git-ignored and disposable, so patches (not hand edits)
# are the only way upstream source changes. Safe to run repeatedly: a patch that
# is already applied is skipped.
set -euo pipefail

T3D="${T3D:-third_party/Torque3D}"
PATCH_DIR="${PATCH_DIR:-patches/torque3d}"

[ -d "$T3D/.git" ] || { echo "ERROR: $T3D is not a checkout. Run scripts/fetch-torque3d.sh" >&2; exit 1; }
[ -d "$PATCH_DIR" ] || { echo "no patches in $PATCH_DIR"; exit 0; }

for p in "$PATCH_DIR"/*.patch; do
  [ -e "$p" ] || continue
  if git -C "$T3D" apply --check --reverse "$p" >/dev/null 2>&1; then
    echo "already applied: $(basename "$p")"
  elif git -C "$T3D" apply --check "$p" >/dev/null 2>&1; then
    git -C "$T3D" apply "$p"
    echo "applied: $(basename "$p")"
  else
    echo "ERROR: $(basename "$p") neither applies nor is applied — the pin or the patch is wrong" >&2
    exit 1
  fi
done
```

- [ ] **Step 3: Wire it into fetch and build**

In `scripts/fetch-torque3d.sh`, after the pin is checked out, call
`bash scripts/apply-patches.sh`. In `scripts/build-web.sh`, after sourcing the SDK
and before `emcmake cmake`, call `bash scripts/apply-patches.sh` so a build can never
run against an unpatched tree. Add a `patch` stage to `scripts/build.sh` that runs
the script directly.

- [ ] **Step 4: Verify idempotence**

Run: `bash scripts/apply-patches.sh && bash scripts/apply-patches.sh`
Expected: first run reports `applied:`; second reports `already applied:`; both exit 0.

- [ ] **Step 5: Re-run the pinned-standard sweep and confirm the jump**

Run:
```bash
source /c/emsdk/emsdk_env.sh
unset CC CXX
sed 's/-std=c++23/-std=c++17/' docs/findings/m0-compile-matrix-harness.sh > /tmp/h17.sh
T8_WORKDIR=build/probe-cxx17-postfix bash /tmp/h17.sh
```
Expected: the compiling count rises from **7** to **roughly 80** of 84. Record the
exact number. Any row still failing on `refBase.h:114` means the patch did not land.

- [ ] **Step 6: Confirm the native build still configures**

Run: `cmd //c scripts\build-native.cmd`
Expected: configure succeeds. Removing `constexpr` cannot break the native build —
if it does, the patch is wrong.

- [ ] **Step 7: Commit**

```bash
git add patches/torque3d/0001-refbase-getpointer-not-constexpr.patch \
        scripts/apply-patches.sh scripts/fetch-torque3d.sh scripts/build-web.sh \
        scripts/build.sh docs/build-environment.md
git commit -m "build: add tracked Torque3D patch mechanism; fix refBase.h constexpr"
```

---

## Task 2: Re-baseline the sweep with a wasm-accurate define set

**This task exists to correct M0a's matrix, and it must run before any failure is
sized as work.** M0a swept the 84 rows with `-Dlinux -D__x86_64__` — a deliberate
choice to test the hypothesis that the configure classifies the target as Linux-x86.
That hypothesis is right about *the configure*, but the define set is not what a real
Emscripten build uses. `emcc` defines `__wasm32__` and `__EMSCRIPTEN__` and does
**not** define `__x86_64__`.

Two of the matrix's four "hard failures" are x86-only code that a correct wasm build
never selects:

- `math/mMathSSE.cpp:286,369` — x86 `'d'` register constraint. Guarded code; the
  portable `mMath_C.cpp` is the fallback.
- `platformPOSIX/POSIXMath.cpp:115` — the x87 block is inside
  `#if defined(TORQUE_CPU_X86) || defined(__x86_64__)`. Drop `-D__x86_64__` and the
  `#else` branch (which returns 0) is taken instead.

If they vanish, they are probe artifacts, not porting work — and the "genuinely hard,
needs a behavioural decision" item in the M0a summary shrinks or disappears.

**Files:**
- Modify: `docs/findings/m0-compile-matrix-harness.sh` (parameterise the define set)
- Create: `docs/findings/m0b-define-baseline.md`

**Interfaces:**
- Consumes: Task 1's patched tree, so the `refBase.h` blocker is out of the way and the rows fail on their own merits.
- Produces: a corrected list of which rows fail under the defines emcc actually sets — the input to Tasks 3 and 4.

- [ ] **Step 1: Parameterise the harness define set**

Change the harness so the define set is a variable rather than hard-coded, and
default it to what `emcc` actually defines plus `-Dlinux` (the configure currently
classifies the target as Linux, so the Linux source paths are what will be selected
until Task 5 fixes platform selection). Drop `-D__x86_64__`.

- [ ] **Step 2: Sweep under both define sets and diff**

Run the sweep twice — once with M0a's probe defines, once with the wasm-accurate set —
and produce a row-by-row diff. Record in `m0b-define-baseline.md`: which rows change
state, and for each, the guard that explains it.

- [ ] **Step 3: Verify the two hypotheses directly**

For `mMathSSE.cpp` and `POSIXMath.cpp`, confirm the guard rather than infer it:
compile each with and without `-D__x86_64__` and record both results. Expected:
`POSIXMath.cpp` compiles without it (the `#else` at `:136` is taken); `mMathSSE.cpp`'s
inclusion is decided by CMake source selection, which Task 5 addresses, not by the
compiler.

- [ ] **Step 4: Commit**

```bash
git add docs/findings/m0-compile-matrix-harness.sh docs/findings/m0b-define-baseline.md
git commit -m "docs: re-baseline the wasm compile sweep against emcc's real defines"
```

---

## Task 3: The `S64` / `U64` width — fix and measure

M0a's most consequential finding, and the one it could least bound. `S64` and `U64`
are **32 bits wide** under wasm32 because of a dead guard.

`Engine/source/platform/types.gcc.h:33-39`:

```c
#if defined(TORQUE_X86)
typedef signed long long    S64;
typedef unsigned long long  U64;
#else
typedef signed long    S64;   // 64-bit on LP64, 32-bit on wasm32's ILP32
typedef unsigned long  U64;
#endif
```

`TORQUE_X86` appears exactly once in the entire `Engine/` tree — at that `#if`.
Nothing defines it, so the `#else` always wins. On the targets Torque3D was written
for that is accidentally correct; on wasm32 it silently yields a 32-bit "64-bit"
integer, and every timestamp, file offset, GUID and tick computation wraps. It is a
**warning**, not an error: `timeClass.h:65` truncates `8640000000` to `50065408`, in
44 of the 84 logs. A build succeeds and misbehaves.

**The fix, and why not "test pointer width".** The M0a summary suggested testing
pointer width. That would be wrong: pointer width is 4 on wasm32, so such a guard
would still select the 32-bit `long`. The correct test is whether `long` itself is 64
bits. Keep `long` where it is 64-bit (preserving the native type exactly) and use
`long long` everywhere else:

```c
#if defined(TORQUE_X86) || !defined(__LP64__)
typedef signed long long    S64;
typedef unsigned long long  U64;
#else
typedef signed long    S64;
typedef unsigned long  U64;
#endif
```

`__LP64__` is defined on Linux/macOS x86-64 and not on wasm32, so this is a no-op
for the native build and a correctness fix for wasm.

**Files:**
- Create: `patches/torque3d/0002-types-s64-width.patch`
- Modify: `docs/findings/m0b-define-baseline.md` (record the measurement)

**Interfaces:**
- Consumes: Task 1's patch mechanism, Task 2's baseline.
- Produces: a 64-bit `S64` on wasm, and a measurement of how many sites depended on it.

- [ ] **Step 1: Write the patch** (content as above, against `types.gcc.h:33-39`).

- [ ] **Step 2: Apply and re-sweep**

Run `bash scripts/apply-patches.sh`, then the sweep. Expected: the
`timeClass.h:65` truncation warning **disappears from all 84 logs** (it was in 44).
Record the before/after count.

- [ ] **Step 3: Measure the affected surface**

This is the part M0a could not do. Grep the engine for `S64` / `U64` use, and for the
`8640000000`-style literals that truncated. Classify each site: does it depend on the
type being exactly 64 bits? Record the count. The fix is small; the point of this step
is to bound the *surface*, so M0b is not surprised at link or run time.

- [ ] **Step 4: Confirm the native build is unaffected**

Run: `cmd //c scripts\build-native.cmd`
Expected: configure and build unchanged. On LP64 the patch is a no-op by construction.

- [ ] **Step 5: Commit**

```bash
git add patches/torque3d/0002-types-s64-width.patch docs/findings/m0b-define-baseline.md
git commit -m "fix: make S64/U64 64-bit under wasm32"
```

---

## Task 4: The surviving compile failures

After Tasks 1-3, whatever still fails is the real porting surface. This task closes
it. Two causes are known from M0a and are expected to survive Task 2; Task 2 may add
others.

**Known and expected to survive:**

- **`ts/tsMesh.cpp` — `__declspec` in the bundled Opcode library.**
  `Engine/lib/opcode/./Ice/IceFPU.h:342-347` uses `__declspec`, MSVC syntax, in a
  *third-party* library bundled under `Engine/lib/`. `-fdeclspec` makes clang parse it
  as a no-op, and on a static wasm build the import/export semantics it requests are
  meaningless anyway. Prefer the flag over patching the library.

- **`platform/platformMemory.cpp:38` — `execinfo.h` does not exist on Emscripten.**
  The `#else` branch (non-Windows) includes glibc's `execinfo.h` for `backtrace()`.
  Unlike the COLLADA rows, this is not a missing `-I` — the header genuinely does not
  exist for this target. Add an Emscripten branch that omits the backtrace support and
  stubs whatever consumes it.

**Files:**
- Create: `patches/torque3d/000N-*.patch` (one per surviving failure)
- Modify: `cmake/toolchain/emscripten.cmake` (add `-fdeclspec` if used)
- Modify: `docs/findings/m0b-define-baseline.md`

**Interfaces:**
- Consumes: Task 2's corrected failure set.
- Produces: a sweep where every row in the sample compiles, or an explicit, named list of what does not and why.

- [ ] **Step 1: Take the corrected failure set from Task 2 and work it in order.**

For each failing row: name the exact error, the file and line, and classify it
mechanical (a flag, an include branch, a build-selection change) or a design decision
(no wasm equivalent). Mechanical items are patched. Design items are recorded, not
guessed at.

- [ ] **Step 2: Add `-fdeclspec` for the Opcode `__declspec` rows.**

Put it on the Emscripten compile options only — never on the native build. Confirm it
clears `tsMesh.cpp` and does not mask a real error elsewhere by checking the warning
count for that row.

- [ ] **Step 3: Patch `platformMemory.cpp` for Emscripten.**

Guard the `execinfo.h` include and its consumer behind `#if !defined(__EMSCRIPTEN__)`
(or an equivalent platform macro), so the Emscripten path simply has no backtrace
support. Record what the consumer does without it.

- [ ] **Step 4: Re-sweep and record the final matrix.**

Append a "M0b post-fix" column to `m0b-define-baseline.md`: row, pre-M0b result,
post-M0b result, cause. This is the number M0b's summary will cite.

- [ ] **Step 5: Confirm the native build still works, then commit.**

```bash
git add patches/torque3d cmake/toolchain/emscripten.cmake docs/findings/m0b-define-baseline.md
git commit -m "fix: clear the remaining wasm compile failures"
```

---

## Task 5: Configure repair — make wasm a platform

**The gating item.** M0a established that Torque3D's CMake has no Emscripten platform
at all: it selects Windows-host values before `project()` and Linux-target values
after, so the configure is a Windows-host / Linux-target hybrid and dies at
`Engine/source/CMakeLists.txt:11`. Nothing links until this is fixed.

The mechanism, from `docs/findings/m0-emscripten-configure.md` §5:

```
CMakeLists.txt:20  include(Tools/CMake/torque_configs.cmake)   <- runs with WIN32=1 (host)
CMakeLists.txt:25  project(${TORQUE_APP_NAME})                 <- WIN32="" UNIX=1 (target)
CMakeLists.txt:87  add_subdirectory(Engine)                    <- sees UNIX=1, picks Linux paths
```

So `torque_configs.cmake` chooses a Windows vcpkg triplet and defaults D3D11 on, while
`Engine/` assembles for X11 Linux. `cmake/torque3d-emscripten.cmake` can only set cache
variables (it runs after `project()`), so it can neutralise symptoms but cannot select
a coherent platform. **The repair is a patch to the engine's CMake** that adds an
Emscripten branch at every platform-decision point.

**Files:**
- Modify: `cmake/torque3d-emscripten.cmake` (cache overrides that still help)
- Create: `patches/torque3d/000N-emscripten-platform.patch`
- Modify: `scripts/build-web.sh` (add the Torque3D target)
- Create: `docs/findings/m0b-configure.md`

**Interfaces:**
- Consumes: `cmake/toolchains/emscripten.cmake` (M0a Task 5), the pin, and every override in `cmake/torque3d-emscripten.cmake`.
- Produces: a configure that completes under Emscripten and generates a wasm build system — the thing Task 9 links.

- [ ] **Step 1: Make the platform variables coherent at the moment they are read.**

Add an `EMSCRIPTEN` branch so the target is classified as neither Windows nor X11
Linux. This is the root fix; every other step below depends on it. Keep `UNIX` set
only where a POSIX behaviour is genuinely wanted (file IO, time) and clear it where
the X11/desktop behaviour is not.

- [ ] **Step 2: Replace the six audio `find_package(... CONFIG REQUIRED)` calls.**

`Engine/source/CMakeLists.txt:11-16` calls `find_package(Ogg|Vorbis|FLAC|Opus|unofficial-theora|SndFile CONFIG REQUIRED)`. Emscripten ports supply the *libraries* but no CMake config packages, so ports alone cannot satisfy these calls (M0a verified `Ogg_FOUND=FALSE`). Under `EMSCRIPTEN`, guard these out and link the ports instead (`-sUSE_OGG=1 -sUSE_VORBIS=1 -sUSE_FLAC=1`, plus the ones the target actually needs). **Do not** write stub config packages.

- [ ] **Step 3: Bypass `find_package(Freetype REQUIRED)`.**

`Engine/source/CMakeLists.txt:60`, inside `if(UNIX AND NOT APPLE)`. The Emscripten
sysroot has no freetype package. Guard it out for `EMSCRIPTEN`; if the engine needs a
font at runtime for the template scene, take it as an Emscripten port rather than a
host library.

- [ ] **Step 4: Exclude `nativeFileDialogs`.**

Added unconditionally at `Engine/lib/CMakeLists.txt:115`
(`add_subdirectory(nativeFileDialogs ... EXCLUDE_FROM_ALL)`). It has Win32/Cocoa/GTK3
backends and no browser equivalent. Guard the `add_subdirectory` behind
`if(NOT EMSCRIPTEN)`. This is the true exclusion M0a could not reach; the
`TORQUE_USE_ZENITY=ON` override in `cmake/torque3d-emscripten.cmake` becomes
unnecessary and should be removed with a note.

- [ ] **Step 5: Skip the vcpkg bootstrap under Emscripten.**

`Tools/CMake/torque_configs.cmake:35-36` clones a ~183 MB vcpkg on a clean build
directory. It is pointless for a wasm target. Guard it behind `if(NOT EMSCRIPTEN)`.
Keep the `WIN32=OFF` cache override — the `${WIN32}` argument-collapse at
`Engine/lib/CMakeLists.txt:226` is real regardless of platform.

- [ ] **Step 6: Add the pthread flags on both sides.**

`-pthread` must appear on **compile** options and **link** options. Emscripten splits
it (`-matomics -mbulk-memory -mthread-model posix` on compile, `--shared-memory` on
link). M0a's configure added neither, and `SDL_PTHREADS` came out `OFF`. This is
Review Focus 3.

- [ ] **Step 7: Configure and confirm it completes.**

Run:
```bash
source /c/emsdk/emsdk_env.sh
emcmake cmake -S third_party/Torque3D -B build/web-t3d \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/emscripten.cmake" \
  -DCMAKE_PROJECT_INCLUDE="$PWD/cmake/torque3d-emscripten.cmake" \
  -DTORQUE_APP_NAME=BaseGame -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  2>&1 | tee build/m0b-configure.log
```
Expected: `-- Configuring done` / `-- Generating done`, and a `Makefile` under
`build/web-t3d/`. Record the full override set and the platform branch that was
selected in `docs/findings/m0b-configure.md`.

- [ ] **Step 8: Confirm the native build still configures, then commit.**

```bash
git add cmake/torque3d-emscripten.cmake patches/torque3d scripts/build-web.sh docs/findings/m0b-configure.md
git commit -m "build: make Emscripten a first-class platform in Torque3D's CMake"
```

---

## Task 6: The GL loader — an Emscripten backend

Torque3D loads its GL entry points through `Engine/source/gfx/gl/tGL/`, which has a
Windows backend (`tWGL.h`) and an X11 backend (`tXGL.h`) and nothing for Emscripten.
`tGL.cpp` itself compiled clean under `-Dlinux` (M0a matrix §7), so this is a
*selection* problem, not a code-portability one: the build must choose a third path.

**Files:**
- Create: `patches/torque3d/000N-tgl-emscripten.patch` (or a new tracked header under `platform/`)
- Modify: `docs/findings/m0b-configure.md`

**Interfaces:**
- Consumes: Task 5's configure.
- Produces: a wasm build where every `gl*` entry point the engine calls resolves, so Task 9 can link.

- [ ] **Step 1: Find the loader selection point.**

Locate where `tGL.h` chooses `tWGL.h` vs `tXGL.h` and add an Emscripten branch. The
browser path should include `<GLES3/gl3.h>` and route the handful of calls Emscripten
does not expose directly through `emscripten_webgl_*` or SDL.

- [ ] **Step 2: Prefer SDL over a hand-written loader where it fits.**

SDL is already the platform layer and its Emscripten backend is present. If SDL
already loads the GL entry points the engine needs, use that rather than adding a
parallel loader — fewer moving parts, and one loader instead of two.

- [ ] **Step 3: Compile the GL device and check the entry points resolve.**

Build `gfx/gl` and confirm no undefined `gl*` symbols remain at the object level.
Record which calls needed the Emscripten route.

- [ ] **Step 4: Confirm the native build still uses its own loader, then commit.**

```bash
git add patches/torque3d docs/findings/m0b-configure.md
git commit -m "feat: add an Emscripten GL loader path"
```

---

## Task 7: GL context profile, and the minimum shader path

Two runtime concerns M0a's compile sweep was blind to by construction — a compiler
cannot see a wrong GL profile or a shader that fails to compile on the GPU.

**7a — the context profile.** `platformSDL/sdlPlatformGL.cpp` and
`gfx/gl/sdl/gfxGLDevice.sdl.cpp` compiled clean, but their SDL GL attributes are
desktop-GL shaped. A browser needs an ES 3.0 profile request (`SDL_GL_CONTEXT_PROFILE_ES`,
major 3, minor 0) or the context comes up as something the shaders cannot run on.
M0a's own smoke target already proves the pattern works
(`platform/web/smoke/main.cpp` requests WebGL2 explicitly).

**7b — the minimum shader path.** `shaderGen/GLSL/shaderGenGLSL.cpp` emits desktop
GLSL (`varying`/`attribute`, no precision qualifiers, `#version 330`). WebGL2 consumes
GLSL ES 3.00. Per `docs/findings/m0-summary.md` Q4, this is work on a component the
spec schedules for replacement behind `RenderQueue` — so do the **minimum** needed to
get a frame on screen, not a complete port. Enough to render the template scene's
shaders, and stop.

**Files:**
- Create: `patches/torque3d/000N-sdl-gl-es-profile.patch`
- Create: `patches/torque3d/000N-shadergen-gles-minimum.patch`
- Modify: `docs/findings/m0b-configure.md`

**Interfaces:**
- Consumes: Task 6's loader, Task 5's configure.
- Produces: a WebGL2 context the engine accepts, and shaders that compile on it.

- [ ] **Step 1: Request an ES 3.0 profile in the SDL GL attributes** (7a).

- [ ] **Step 2: Make the generator emit GLSL ES 3.00** — `#version 300 es`, precision qualifiers, `in`/`out` in place of `attribute`/`varying` (7b). Scope it to what the template scene's materials need; record what was left unported.

- [ ] **Step 3: Verify shaders compile on a real GL backend.** Extend the M0a smoke harness pattern (`tests/web/smoke.spec.js`) with a test that loads the engine's generated shaders and asserts `COMPILE_STATUS`. A shader that fails to compile is silent in the C++ build and fatal at runtime.

- [ ] **Step 4: Confirm the native build still renders, then commit.**

```bash
git add patches/torque3d tests/web docs/findings/m0b-configure.md
git commit -m "feat: ES3 profile request and minimum GLSL ES 3.00 shader path"
```

---

## Task 8: The main loop — `emscripten_set_main_loop`

Torque3D's game loop is a blocking `while` in `app/game.cpp` / `main/main.cpp`. A
blocking loop compiles fine and hangs the tab: the browser never gets control back.
This is the fourth of M0a's predicted-hard areas that compiled clean because the
compiler cannot see it (matrix §7).

**Files:**
- Create: `patches/torque3d/000N-emscripten-main-loop.patch`
- Modify: `docs/findings/m0b-configure.md`

**Interfaces:**
- Consumes: Task 7's rendering path.
- Produces: an engine that runs frames in a tab without blocking, so Task 9's acceptance test can observe a frame.

- [ ] **Step 1: Identify the loop entry point** in `app/game.cpp` / `main/main.cpp` and the per-frame function it calls.

- [ ] **Step 2: Under `__EMSCRIPTEN__`, drive frames with `emscripten_set_main_loop`** instead of the `while`. Keep the native path unchanged — the loop must still be a real loop on the PC build.

- [ ] **Step 3: Confirm the tab does not hang.** Load the build in the browser and confirm the page stays responsive and frames advance. A hang here looks like a blank tab and no console error, so assert on frame progress, not on load.

- [ ] **Step 4: Confirm the native build still loops, then commit.**

```bash
git add patches/torque3d docs/findings/m0b-configure.md
git commit -m "feat: drive the engine loop through emscripten_set_main_loop"
```

---

## Task 9: Link, boot, render — the acceptance test

**The milestone's terminal deliverable.** Everything above is preparation for this:
a wasm build of Torque3D that links, boots in a browser tab, renders the `BaseGame`
template scene, and accepts keyboard input. M0a linked nothing and ran nothing, so
unresolved symbols, duplicate definitions, and static-initialisation order are all
untested until here.

**Files:**
- Modify: `scripts/build-web.sh` (add the `torque3d` target)
- Create: `tests/web/engine-boot.spec.js`
- Modify: `README.md` (status table)
- Create: `docs/findings/m0b-summary.md`

**Interfaces:**
- Consumes: Tasks 1-8.
- Produces: `build/web-t3d/` output loadable by `tools/serve.py`, and a browser test that asserts a rendered frame and input handling.

- [ ] **Step 1: Link.** Build the wasm target to completion. Expect unresolved symbols and duplicate definitions; each is a named, bounded item. Record every one — the list is itself a finding about how far the platform layer reaches.

- [ ] **Step 2: Boot it in the dev server.** Serve the output through `tools/serve.py` (COOP/COEP) and load it. A `SharedArrayBuffer is not defined` error means the isolation headers are not reaching the page, not that the build is wrong — re-run `tests/web/server.spec.js` to isolate.

- [ ] **Step 3: Write the acceptance test.** `tests/web/engine-boot.spec.js` asserts: the module loads, the engine reaches its main loop, a frame is drawn (reuse the non-uniform-frame technique from `tests/web/smoke.spec.js` — a blank frame is uniform), and a key event reaches the engine. Assert on observed behaviour, not on page load.

- [ ] **Step 4: Run it.** `bash scripts/build.sh test` with the engine target served. Expected: PASS. **This is the result that validates or refutes Q4 of the M0a summary** — if the port links and boots, M1 proceeds; if it cannot link, Q4 reopens with real numbers.

- [ ] **Step 5: Update the README status table** to reflect the true state — which capabilities now work and which do not. Do not overstate: a rendered template scene is not BeamNG content.

- [ ] **Step 6: Commit.**

```bash
git add scripts/build-web.sh tests/web/engine-boot.spec.js README.md docs/findings/m0b-summary.md
git commit -m "feat: Torque3D links, boots and renders in a browser tab"
```

---

## Task 10: Findings handoff and M1 readiness

M0b's terminal deliverable, like M0a's, is the knowledge: what the port actually cost
now that it has been done, and whether M1's scope survives contact with it.

**Files:**
- Create: `docs/findings/m0b-summary.md` (if not already written in Task 9)

**Interfaces:**
- Consumes: every finding from Tasks 1-9.
- Produces: a decision on M1, and an updated risk picture for the spec.

- [ ] **Step 1: Answer these explicitly, citing the tasks:**

1. Does the engine link, boot, render and take input at the pin? If not, what is the exact blocker and is it bounded?
2. Was the port's cost — measured, not inferred — cheaper than writing a GLES3 renderer from scratch? The M0a summary left this to M0b's link-and-run; answer it now with real numbers.
3. How much of the GLSL ES 3.00 work did the minimum path need, and how much remains? The spec schedules `render/webgl2` behind `RenderQueue`; the less `shaderGen` porting is needed, the more that substitution is the right call.
4. Did the `S64` width fix surface hidden breakage at link or run time, or was the surface bounded as Task 3 measured?
5. Does M1's scope (`ZipVFS`, one level mesh, the renderer seam) survive? What did M0b reveal that changes its entry cost?

- [ ] **Step 2: Report and stop.** Present the findings. Do not begin M1 — it gets its own plan, written against these findings, and approved before implementation starts.

- [ ] **Step 3: Commit.**

```bash
git add docs/findings/m0b-summary.md
git commit -m "docs: summarise M0b findings and confirm M1 scope"
```

---

## What M0b Deliberately Does Not Do

Stated so the boundary is not mistaken for an omission:

- **No BeamNG content.** No `assets/`, no `ZipVFS`, no DAE, no DDS, no `.pc`. That is M1 onward.
- **No `core/` library**, no frozen interfaces, no JBeam, no solver, no UI.
- **No complete GLSL ES 3.00 port.** Task 7 does the minimum to render the template scene, because the spec replaces this component behind `RenderQueue`.
- **No performance work.** WASM SIMD, physics on a pthread, streaming, and batching are M6. M0b proves the target runs, not that it runs fast.
- **No attempt to make the browser build pretty.** A frame on screen with the right pixels is the bar. The template scene rendering at a low frame rate is a pass.

The reason for the shape of this plan: M0a showed that source-reading predicts the
wrong failures — the four "hard" areas it predicted all compiled clean, and the thing
that mattered most was a warning nobody expected. M0b's tasks are ordered to correct
the evidence first (Tasks 2-3), fix the bounded blockers it names (Tasks 1, 4), then
do the work the compiler could not see (Tasks 5-8), and finally run the only test that
settles the question (Task 9). Anything that measures the port off M0a's uncorrected
numbers would be sizing a phantom.

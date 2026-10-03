# M0 findings — summary and recommendation

Terminal deliverable of M0a. Turns the two probe documents into a decision.

Inputs:
- `m0-emscripten-configure.md` — what Torque3D's CMake does under Emscripten
- `m0-compile-matrix.md` — what its translation units do under `emcc`

Pinned revision `4c44642aab32cf79be4f66966d49fd74ab18e221`, Emscripten 4.0.9.

> **Provenance.** The Task 8 implementer was terminated by an API quota error and
> the controller finished that probe and wrote this summary. Neither this document
> nor the matrix it summarises has had independent review. The configure findings
> were independently reviewed against their raw logs and corrected; the matrix was
> not. Everything below is only as good as the two documents it cites.

---

## Question 1 — Does Torque3D configure and compile to wasm at the pinned revision, and what fraction of subsystems?

**Configure: no. It fails outright.** Three sequential first-failures were
isolated: unpatched it dies at `Engine/lib/nativeFileDialogs/CMakeLists.txt:16`
on `pkg_check_modules(GTK3 REQUIRED gtk+-3.0)` resolved against the host's MSYS2
pkg-config; with the tracked overrides it advances one step to
`Engine/source/CMakeLists.txt:11` on `find_package(Ogg CONFIG REQUIRED)` and
stops. The root cause is that CMake initialises `WIN32=1` from the host *before*
`project()` and `UNIX=1` *after*, so `torque_configs.cmake` — included before
`project()` — selects a Windows vcpkg triplet and defaults D3D11 on, while
`Engine/` then assembles for X11 Linux. The configure is a Windows-host /
Linux-target hybrid. Neither half describes a browser.

**Compile: yes, at translation-unit level, and more cleanly than expected.**
84 representative translation units across all 19 engine directories were
compiled directly with `emcc`, bypassing CMake: **80 compiled, 3 failed, 1
blocked.** 15 of the 19 directories compiled every file tried.

The three failures are all in hand-written platform code, not in the engine's
portable bulk:

| Row | Cause | Class |
|---|---|---|
| `math/mMathSSE.cpp` | x86 `'d'` register constraint in inline asm | mechanical — the portable C fallback `mMath_C.cpp` compiles |
| `platformPOSIX/POSIXMath.cpp` | x87 `fstcw`/`fldcw` FPU control word | **needs a design answer** — wasm has no FPU control word |
| `ts/tsMesh.cpp` | `__declspec` in the bundled Opcode library (`Ice/IceFPU.h:342-347`) | mechanical — `-fdeclspec` parses it as a no-op |
| `platform/platformMemory.cpp` | includes glibc's `execinfo.h` | mechanical — needs an Emscripten branch |

**The headline finding is not one of these.** `S64` and `U64` are **32 bits wide**
in this build. `Engine/source/platform/types.gcc.h:33` guards on `TORQUE_X86`,
which appears exactly once in the entire `Engine/` tree — at that `#if`. Nothing
defines it, the branch is dead, and the `#else` (`typedef signed long S64`)
always wins. That is accidentally correct under LP64 and silently wrong under
wasm32's ILP32. The compiler says so: `timeClass.h:65` truncates `8640000000` to
`50065408`, in 44 of the 84 logs. Every `S64` in the engine — timestamps, file
offsets, GUIDs, tick arithmetic — becomes a wrapping 32-bit value. It produces
warnings, not errors, so a build succeeds and misbehaves.

**The fraction question, answered honestly:** 80/84 *translation units*. That is
not "17 of 19 subsystems work". Nothing was linked and nothing was run. Unresolved
symbols, link ordering, and static initialisation order are entirely untested. On
the evidence available, the correct statement is: *the engine's C++ is
overwhelmingly wasm-clean at the compilation unit level, and its build system is
not wasm-capable at all.*

---

## Question 2 — What is the largest single work item, and is it bounded?

**Two answers, because they are different items.**

**Largest by gating power — repairing the configure. Bounded.** This is not
"fix two `find_package` calls". Torque3D has no Emscripten platform: once the
configure runs far enough to select sources it will pick the Linux desktop paths
(`platformPOSIX`, `platformX86UNIX`, `platformX11`) for a browser target, and its
GL loader (`tGL`) has Windows and X11 backends only. Making wasm a first-class
platform touches platform selection, the GL loader choice, and the
audio/video `find_package` calls. It is **bounded**: the mechanism is now
understood precisely, every affected decision point is enumerated in
`m0-emscripten-configure.md`, and there is no unknown-unknown left in it. It is
the largest single chunk of the next milestone and it gates all others.

**Largest by risk — the `S64` width. Unbounded until measured.** The fix is
small; the *affected surface* is not known. Nothing in this probe enumerates how
many places depend on `S64` being 64 bits, because a failing build was never
produced to find out. This is the item most likely to cost more than it looks,
and it is the one the probes were least able to bound. Measuring it is a concrete,
cheap early task for M0b: fix the typedef and count the warnings that disappear.

**Genuinely hard, but small: `POSIXMath.cpp`.** The x87 FPU control word
(`fstcw`/`fldcw`) sets rounding and precision modes. wasm has neither. There is no
mechanical translation; someone has to decide what those calls should mean on a
target with fixed floating-point semantics. Small file, real design decision —
and a good example of why "how many files fail" is the wrong sizing metric.

**Nothing found is unbounded in the sense of "unknown blockers still surfacing"**
— the compile surface has been swept and its failures have named causes.

---

## Question 3 — Does the spec's M1 remain correctly scoped, or did the probes change what comes next?

**M1's content is unchanged. Its entry cost is now known to be a milestone, not a
tidy-up.**

The spec defines M1 as: `ZipVFS` mounts a vehicle zip and a level zip, renders one
level mesh; retires `IAssetSource`, `MeshData`, and the renderer seam; the DAE
parser and DDS upload path land here. Nothing in either probe touches that
description — BeamNG assets, the zip layout, and the mesh pipeline are untouched
by wasm portability questions. **M1 stays correctly scoped.**

What changed is the road to it. The spec's M0 is "Torque3D compiles under emcc,
boots in a browser tab, renders the default T3D template scene, accepts keyboard
input." M0a has shown that the first clause of that sentence is not a formality:
the engine does not configure, does not link, and would misbehave on timing if it
did. **M0b is therefore a real milestone with its own plan, not the tail of M0a.**

One consequence worth deciding before M0b is planned: M1 cannot be reached
without M0b, so any parallelism the spec's section 6 assumes between "get the
engine running" and "read BeamNG assets" **starts later than the spec implies**.
The asset-side work (`ZipVFS`, the DAE parser, DDS upload) is genuinely
independent of the engine port and could proceed in parallel *if* it is built
against the frozen `IAssetSource`/`MeshData` interfaces rather than against a
running engine. That is the spec's own design intent, and the probes make it more
attractive, not less.

---

## Question 4 — Was porting upstream Torque3D validated, or do the GL loader and shader generator together cost more than writing a GLES3 renderer from scratch?

**Validated — on the evidence available, the port is far cheaper. But the evidence
covers compilation only, and the decisive test has not been run.**

**First, correct the premise.** The spec does *not* commit to replacing the
renderer at M2. `docs/.../2026-10-01-beamng-browser-port-design.md:77-80` commits
to **two renderers behind a stable `RenderQueue` interface**, with `render/t3d`
swappable for `render/webgl2` as "a concrete substitution behind a stable
interface rather than a rewrite". The distinction matters for what follows.

**The argument for the port:**

1. **The engine's portable bulk is already wasm-clean.** 15 of 19 directories
   compiled every translation unit tried, including all of `scene`, `ts`,
   `terrain`, `sfx`, `gui`, `materials`, `T3D` and `console`. Those are the
   subsystems a from-scratch GLES3 renderer would still need written for it.
   Writing them is a far larger job than porting them.
2. **The renderer is not the compile blocker.** `gfx/gl` (6/6) and `shaderGen`
   (4/4) compiled clean, including `tGL/tGL.cpp`, `gfxGLDevice.sdl.cpp` and
   `shaderGenGLSL.cpp` — the exact files the task brief named as the likely
   hardest. At compilation level they are not hard at all.
3. The three real failures are in x86 assembly and third-party platform shims —
   work that has to be done *either way*, since a from-scratch renderer still has
   to run inside a host the browser can execute.

**The argument against, stated fairly:** the probe measured compilation, and the
things that are supposed to be hard about porting a renderer are not compile-time.
GL context attributes, the tGL loader's missing Emscripten backend, `#version 300
es` shader emission and desktop→ES `varying`/`attribute` conversion are all
*runtime* concerns, and this probe is blind to every one of them — the same way it
is blind to the blocking main loop that would hang a browser while compiling
cleanly. The brief predicted those four as the hard areas; all four compiled, and
that is not evidence they are easy, only that a compiler cannot see the problem.
The cost of the port's renderer work is therefore **unmeasured**, not **low**.

**Recommendation:** proceed with the port. Not because the renderer work is proven
cheap, but because the alternative has to rebuild everything Torque3D already
provides and compiles — and because the renderer is the one component the spec
already plans to substitute behind a seam.

**Make M0b's link-and-run the decision point.** If M0b produces a wasm build that
links and boots to a rendered frame, the port is validated and M1 proceeds. If
M0b cannot link, the calculus changes materially and this question should be
reopened with real numbers instead of inferences.

**One strategic note the probes make visible.** The spec's M0 risk list includes
"GLSL 3.3 to GLSL ES 3.00 shader translation" as one of the scariest unknowns.
But if `render/t3d` is going to be swapped for `render/webgl2` behind
`RenderQueue`, then perfecting ES 3.00 shader *generation* inside Torque3D is work
on a component scheduled for replacement. M0b should do the **minimum** needed to
get a frame on screen — enough to prove the platform layer, the GL context and the
threading — and should not invest in porting `shaderGenGLSL.cpp` to ES 3.00 beyond
what that minimum requires. The spec retires that risk at M0; the probes suggest
it is the wrong risk to spend effort retiring.

---

## What M0a did not do, restated so it is not mistaken for an omission

- No `core/` library, no frozen interfaces from spec section 4.2, no BeamNG
  content, no JBeam parsing, no soft-body solver, no UI.
- **Torque3D does not boot in a browser tab.** Compiling translation units in
  isolation is not the engine running. Getting it running is M0b.
- No attempt was made to fix any compile failure found. Fixing them is the next
  plan's job; doing it here would have meant writing that plan blind.
- Nothing was linked. Nothing was executed.

## Recommended next step

Write the M0b plan against these findings — **not** against the spec's assumptions
about how hard the port would be, which the probes have now replaced. M0b's
deliverable should be a wasm build of Torque3D that links, boots in a browser tab
and renders a frame. That single result validates or refutes Question 4, and it is
the gate every later milestone sits behind.

The user should approve this summary and M0b's scope before M0b is planned.

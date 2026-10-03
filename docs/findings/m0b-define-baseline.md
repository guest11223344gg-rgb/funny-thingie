# M0b — re-baselining the wasm compile sweep against emcc's real defines

Task 2 of `docs/superpowers/plans/2026-10-03-m0b-wasm-boot.md`. Corrects
`docs/findings/m0-compile-matrix.md`, which was swept with probe scaffolding that
a real Emscripten build does not use.

Pinned revision `4c44642aab32cf79be4f66966d49fd74ab18e221`, Emscripten 4.0.9,
`-std=c++17` (the standard the plan pins and upstream declares), on the tree
carrying `patches/torque3d/0001-refbase-getpointer-not-constexpr.patch`.

---

## Why this exists

M0a's matrix swept 84 translation units with
`-Dlinux -D__x86_64__ -D__linux__ …`. That define set was a deliberate probe
choice — it tests the hypothesis that Torque3D's configure classifies the target
as Linux-x86, which it does. But it is **not** what `emcc` sets: `emcc` defines
`__wasm32__` and `__EMSCRIPTEN__`, and does **not** define `__x86_64__`.

The harness is now parameterised (`T8_DEF`, `T8_STD`) so the define set and the
compiler standard can be overridden without editing it. Two sweeps were run at
C++17, identical in every other respect:

| Sweep | Define set | Compiles | Fails | Blocked |
|---|---|---|---|---|
| A — M0a probe defines | `-Dlinux -D__x86_64__ …` | **80** | **3** | **1** |
| B — wasm-accurate | `-Dlinux …` (no `-D__x86_64__`) | **3** | **80** | **1** |

Reproduce:

```bash
source /c/emsdk/emsdk_env.sh
unset CC CXX
# A — the set M0a used
T8_STD="-std=c++17" T8_WORKDIR=build/probe-wasmdefs-a \
  bash docs/findings/m0-compile-matrix-harness.sh
# B — the set emcc actually uses
T8_DEF="-Dlinux -D__linux__ -DTORQUE_OPENGL -DTORQUE_SDL -DTORQUE_ADVANCED_LIGHTING \
        -DTORQUE_BASIC_LIGHTING -DTORQUE_OGGVORBIS -DTORQUE_OGGTHEORA -DTORQUE_RELEASE \
        -DTORQUE_ENABLE_ASSERTS -DTORQUE_DEBUG_GFX_MODE" \
T8_STD="-std=c++17" T8_WORKDIR=build/probe-wasmdefs-b \
  bash docs/findings/m0-compile-matrix-harness.sh
```

---

## Result A — the probe defines, after the `refBase.h` fix

**80 compile, 3 fail, 1 blocked.** The three failures and the blocked row are
exactly the four M0a named:

```
FAIL  math/mMathSSE.cpp         invalid input constraint 'd' in asm
FAIL  platformPOSIX/POSIXMath.cpp   invalid operand in inline asm: 'fstcw $0'
FAIL  ts/tsMesh.cpp             '__declspec' attributes are not enabled
INCL  platform/platformMemory.cpp   'execinfo.h' file not found
```

This confirms Task 1: the `refBase.h:114` fix alone takes the pinned standard
from **7** compiling rows to **80**, i.e. identical to the C++23 control run.
The standard was never the problem; the header was.

## Result B — the defines `emcc` actually sets: everything breaks, on one line

Dropping `-D__x86_64__` and changing nothing else **inverts the result**:
3 compile, 80 fail, and all 80 fail on the same line of the same header.

```
error: "GCC: Unsupported Target CPU"
```

That is `Engine/source/platform/types.gcc.h:132-133`:

```c
#if defined(i386) || defined(__i386) || defined(__i386__)
#  define TORQUE_CPU_STRING "Intel x86"
#  define TORQUE_CPU_X86
#  define TORQUE_LITTLE_ENDIAN
#elif defined(__x86_64__)
#  define TORQUE_CPU_STRING "Intel x64"
#  define TORQUE_CPU_X64
#  define TORQUE_LITTLE_ENDIAN
#elif (defined( __arm64__ ) && defined( __APPLE__ )) || defined( __arch64__ )
#  define TORQUE_CPU_STRING "Arm 64"
#  define TORQUE_CPU_ARM64
#  define TORQUE_LITTLE_ENDIAN
#else
#  error "GCC: Unsupported Target CPU"
#endif
```

**There is no wasm32 branch.** A real Emscripten build defines none of `i386`,
`__x86_64__`, or the arm64 macros, so it hard-errors here before any other
question can be asked.

---

## The finding

**M0a's `-D__x86_64__` was load-bearing, and it was hiding a missing platform.**
Torque3D has no wasm CPU identification at all. The probe's define set supplied
one — a *false* one — which is why 80 rows compiled and why two of the four
recorded failures looked like x86-assembly porting work.

What that reclassifies:

1. **`mMathSSE.cpp` and `POSIXMath.cpp` are not porting work in the wasm sense.**
   Both are x86-guarded and would not be selected on a correctly-identified
   wasm32 target:
   - `mMathSSE.cpp:206` — the GCC inline-asm block is inside
     `#elif defined(TORQUE_COMPILER_GCC) && (defined(TORQUE_CPU_X86) || defined(TORQUE_CPU_X64))`.
   - `POSIXMath.cpp:115` — the `fstcw`/`fldcw` block is inside
     `#if defined(TORQUE_CPU_X86) || defined(__x86_64__)`, with an `#else` that
     returns 0.
   So the M0a summary's "genuinely hard, needs a behavioural decision" item is
   smaller than it looked: on a correct wasm32 identification the `#else` branch
   is taken and the x87 control word is never touched.
2. **The real first blocker is the missing CPU branch**, and it gates every
   other row. It is bounded and mechanical — one `#elif` — but it must exist
   before any other measurement means anything.
3. **Defining `TORQUE_CPU_X64` for wasm would be wrong.** wasm32 is 32-bit and
   little-endian; claiming x64 would be the same class of lie as M0a's
   `-D__x86_64__`, and it would re-enable the x86-only code paths above. The
   honest fix is a new branch that sets `TORQUE_LITTLE_ENDIAN` and a wasm-specific
   CPU macro, then an audit of `TORQUE_CPU_X86` / `TORQUE_CPU_X64` uses.

## Consequence for M0b's task order

The plan's Task 2 expected the two x86 rows to vanish and `tsMesh` /
`platformMemory` to survive. The measurement is more useful than that: nothing
survives, because the target cannot be identified as a CPU at all.

A new patch — `0002-types-wasm32-cpu.patch` — becomes the **first** source change
of the port, ahead of the `S64` fix and ahead of every compile-failure item, and
the matrix must be re-swept with it before any failure is sized as work. This is
the third instance of the same pattern M0a named twice: a latent mis-declaration
that a permissive host hides and a strict target exposes (`S64` width,
`refBase.h:114`, and now the absent wasm CPU branch).

**Status: observed.** Both sweeps ran; the counts and the error text are in the
logs under `build/probe-wasmdefs-{a,b}/logs/`. The reclassification of
`mMathSSE` / `POSIXMath` is read from the guards above and confirmed by the
`#else` branch in `POSIXMath.cpp:136`; it has not yet been re-run with a wasm32
CPU branch in place, which is the next task's job.

# BeamNGWeb: BeamNG.drive-style vehicle simulation in the browser

Date: 2026-10-01
Status: Design approved, awaiting spec review

## 1. Purpose

Build a soft-body vehicle simulation that runs both natively on Windows and in a
web browser, using Torque3D as the PC engine and BeamNG.drive's own content
(vehicles, levels, textures, physics skeletons) as the asset source, for the
author's personal use on their own machine.

The target experience is BeamNG.drive's free-roam mode: pick a vehicle, load a
BeamNG map, drive, crash, and watch the body deform. Plus a parts and vehicle
selector built on BeamNG's own `.pc` part configuration files.

## 2. What this is not

- Not a distribution of BeamNG.drive. BeamNG's engine is closed; there is no
  fork to obtain. `github.com/BeamNG/Torque3D` was verified to be a stock
  upstream T3D 3.5.1 mirror from 2014 with no BeamNG-specific commits, last
  pushed 2015-08-12.
- Not a reimplementation of BeamNG's physics solver, which is proprietary. The
  node/beam approach is reimplemented from the publicly documented JBeam format.
- Not a publicly deployable artifact. See section 3.

## 3. Constraints

**Asset handling.** BeamNG assets come from the author's purchased Steam copy,
currently at `D:\SteamLibrary\steamapps\common\BeamNG.drive`. Extracted assets
live in a git-ignored `assets/` directory. The web build is served from
localhost for personal use and is never deployed to a public URL with BeamNG
content bundled. This is a hard constraint on the spec, not a preference: the
engineering does not change, only where output is permitted to live.

**Dual target.** One codebase producing a native PC build and a WASM/browser
build. The PC build must keep working throughout; it is the debugging surface
for shared code.

**Performance is a requirement, not a polish pass.** The browser target has a
real frame budget and a hard 4 GB WASM32 memory ceiling. Both are treated as
constraints on the architecture from the first milestone, not addressed later.

**Localhost serving.** The dev server runs on localhost so COOP/COEP headers
can be set, which SharedArrayBuffer and pthreads require.

## 4. Architecture

### 4.1 Layout

```
core/                 portable C++17: no platform deps, no graphics API
  assets/             IAssetSource, ZipVFS, DAE parser, DDS header parser,
                      materials.json -> MaterialData
  sim/                JBeam parser, node/beam solver, Vehicle, SimWorld
  scene/              transforms, visibility, RenderQueue building
  game/               part configuration (.pc), gameplay glue
render/
  t3d/                adapter onto the existing Torque3D renderer. Used by the
                      PC target always, and by the browser target during M0-M1
                      as the walking skeleton, before webgl2 replaces it.
  webgl2/             purpose-built, GLSL ES 3.00, PBR + damage. Browser only,
                      lands at M2.
platform/
  pc/                 Torque3D integration, thin
  web/                Emscripten main loop, pthread pool, SAB,
                      VFS over HTTP range requests
ui/                   HUD, garage, vehicle selector
assets/               git-ignored; BeamNG content, extracted
```

`core/` is the only code linked by both targets. This is what makes PC and
browser share a single physics implementation and a single asset pipeline, and
it is what makes core bugs reproducible natively where a real debugger and
sanitizers are available.

Both renderers sit behind `RenderQueue`. Swapping `render/t3d` for
`render/webgl2` is therefore a concrete substitution behind a stable interface
rather than a rewrite — this is the mechanism by which the "port first, replace
the renderer later" strategy works.

### 4.2 Frozen interfaces

These five are frozen before parallel workstreams begin. They are the contract
between the three workstreams described in section 6; changing one after work
starts requires coordination across all three.

```cpp
// core/assets — the only way anything reads an asset
struct IAssetSource {
    virtual std::optional<Blob>     read(std::string_view path) = 0;
    virtual std::optional<Blob>     readRange(std::string_view path,
                                              size_t offset, size_t len) = 0;
    virtual std::vector<EntryInfo>  list(std::string_view prefix) = 0;
};

// core/assets — renderer-agnostic, structure-of-arrays
struct MeshData {
    std::vector<float>        positions;   // xyz
    std::vector<float>        normals;
    std::vector<float>        uvs;
    std::vector<uint32_t>     indices;
    std::vector<VertexWeight> skinWeights; // node influence, for flexbody
};
struct MaterialData { /* PBR scalars, texture handles, damage params */ };

// core/sim — physics publishes, interface and renderer consume
struct Vehicle {
    NodeArray   nodes;        // SoA
    BeamArray   beams;        // SoA
    WheelArray  wheels;
    FlexMap     flexbodyMap;  // vertex -> node weights
};

// core/sim — fixed-step entry point, no per-frame coupling
struct SimWorld {
    void step(float fixedDt);
    const TransformBuffer& lastCompleted() const;  // shared-memory readable
};

// core/scene — flat draw list; interface fills, renderer submits
struct RenderQueue { /* draws, material keys, instance groups */ };
```

`TransformBuffer` is double-buffered in shared memory. The sim writes the next
block while the renderer reads the last completed one. No lock, no per-frame
allocation.

## 5. Milestones

Ordered by risk retired per unit of work. Each milestone produces something
runnable.

**M0 — Walking skeleton.** Torque3D compiles under emcc, boots in a browser
tab, renders the default T3D template scene, accepts keyboard input. No BeamNG
content. Retires the scariest unknowns: the Emscripten platform layer, GLSL 3.3
to GLSL ES 3.00 shader translation, the virtual filesystem, and
pthreads + SharedArrayBuffer.

**M1 — BeamNG assets read.** `ZipVFS` mounts a vehicle zip and a level zip and
renders one level mesh. Retires `IAssetSource`, `MeshData`, and the renderer
seam. The DAE parser and DDS upload path land here.

**M2 — One vehicle, rigid.** JBeam parses, nodes and beams build, the vehicle
renders as a flexbody, wheels spin. Retires the JBeam parser and the `Vehicle`
seam.

**M3 — Soft body.** Node/beam spring-damper solver with deformation, flexbody
vertex mapping, visible crumple on impact. This is the long pole; see section 9.

**M4 — Drive.** Input to vehicle control, chase camera, HUD, free roam on a
BeamNG map. First genuinely playable milestone.

**M5 — Parts and configuration.** `.pc` part configs, vehicle switching, garage
map. This is the full scope of the "free roam plus parts" objective.

**M6 — Performance pass.** WASM SIMD, physics on a pthread, level streaming,
static batching, texture eviction. Section 8 describes what lands here.

## 6. Workstreams

Three parallel workstreams plus integration ownership.

**Agent A — physics.** Owns `core/sim/`. JBeam parsing, the node/beam solver,
`Vehicle`, flexbody vertex mapping, solver determinism.

**Agent B — engine.** Owns `platform/web/` and `render/`. Work is staged: for
M0-M1 the browser renders through `render/t3d`, so Agent B first gets
Torque3D's own renderer running under Emscripten (this is where the GLSL 3.3 to
GLSL ES 3.00 translation happens). Only once that renders does Agent B build
`render/webgl2` as the replacement. Emscripten platform layer and pthread pool
also fall here.

**Agent C — BeamNG interface and UI.** Owns `core/assets/` and `ui/`. ZipVFS,
DAE parsing, DDS handling, `materials.json` translation, `.pc` part configs,
HUD and garage UI.

**Integration.** Seam contracts, the build system for both targets, Torque3D PC
integration, and integration testing. Someone must own the boundaries where the
three workstreams meet; without that owner the interfaces drift.

Two things deliberately do not parallelize and are sequenced first: the build
system must exist before any agent can verify its work, and M0 must land before
Agent B has a rendering context to target. Agents A and C can start against
`core/` headers immediately, since their work is testable natively.

## 7. Data flow

**Startup.** The Emscripten module boots. A pthread pool is sized to
`hardwareConcurrency - 1`. `ZipVFS` mounts vehicle and level archives by
reading only each zip's central directory and indexing entries — archives are
never downloaded whole. This is why M1 targets the zip layout specifically:
level archives are hundreds of megabytes, and the entire streaming design
depends on never fetching one in full.

**Per frame.** Main thread: input becomes `SimInput`, visibility is computed,
`RenderQueue` is filled, GL commands are submitted. Worker thread:
`SimWorld::step(dt)` runs at a fixed rate, decoupled from vsync. The two meet
at the double-buffered `TransformBuffer`.

**Asset load path.** Zip entry becomes a `Blob` via `IAssetSource`, which feeds
a parser (DAE, DDS, jbeam, or materials.json), which produces `MeshData`,
`MaterialData`, or a `Vehicle` spec, which is then either uploaded to the GPU
or used to initialize simulation state.

**Flexbody deformation.** BeamNG performs this on the CPU, re-mapping every
vertex to its nodes each frame. In a browser that cost will consume the frame
budget. Instead, flexbody deformation is implemented as GPU skinning: each
vertex's node weights are precomputed once at load time, only node transforms
are uploaded per frame (hundreds of floats rather than tens of thousands of
vertices), and the vertex shader performs the blend. Visually equivalent to the
CPU approach, with an order of magnitude less main-thread work. This is why
`MeshData` carries `skinWeights` and why that interface is frozen early.

## 8. Performance budget

- **Structure-of-arrays** for nodes, beams, and vertex data. Vehicles carry
  thousands of nodes; an array-of-structs layout will not hold the budget.
- **WASM SIMD** for the solver inner loop.
- **Fixed-step physics on a worker thread**, decoupled from rendering. Solver
  rate is never tied to vsync. State exchanged through shared memory, not
  per-frame copies.
- **DDS uploaded directly** as compressed textures via
  `WEBGL_compressed_texture_s3tc`. The 7496 textures in `content/vehicles` are
  already DXT; this path costs zero decode time.
- **Streaming with eviction.** Level chunks load on demand with an LRU texture
  cache. The 4 GB WASM32 ceiling is the constraint that forces this to be
  designed in from M1 rather than retrofitted.
- **Instanced and merged static batching** with PVS for level geometry. BeamNG
  maps are draw-call heavy.

Frame time, node budget, and memory are asserted in the test harness as
pass/fail gates, not merely reported.

## 9. Risks

**Soft-body fidelity (M3) is the long pole.** A spring-damper node/beam solver
that is stable at high step rates and produces beam-like deformation is
genuinely hard. Staging M2 as rigid with deformable geometry means the project
is drivable before this completes. BeamNG's own default is a 2000 Hz fixed
physics step; this spec does not assume that rate is achievable in a browser
and treats the step rate as a tunable to be validated empirically.

**Shader translation (M0).** Torque3D ships GLSL 3.3; WebGL2 consumes GLSL ES
3.00. This is mechanical but broad, and it is the largest single unknown in the
port. M0 exists specifically to find out how bad it is before anything depends
on it.

**Renderer divergence.** Two renderers sharing a `RenderQueue` will drift
visually. Accepted deliberately: the alternative is running a 2010s forward
renderer on the platform with the tightest performance budget. Golden-image
tests are therefore per-target, not cross-target.

**Asset parse failures at scale.** 5062 jbeam files and 7496 textures will
contain content the parsers do not handle. Section 10 covers containment.

**Memory ceiling.** WASM32 caps at 4 GB with no recovery from exhaustion. This
is the one failure mode with no graceful degradation, which is why the
allocator is budgeted and eviction is explicit.

## 10. Error handling

BeamNG content is large and heterogeneous; parse failures are expected, not
exceptional. Every loader returns a result, records a diagnostic, and
substitutes a placeholder so simulation continues:

- Unparseable jbeam becomes a box on wheels.
- Missing or unreadable texture becomes a 1×1 fallback.
- Failed mesh parse becomes a visible placeholder.
- `.cdae` files are ignored by design; `.dae` is the supported mesh path.

The one exception is memory exhaustion, which has no recovery. A budgeted
allocator with explicit caps and an LRU texture cache refuses a load that would
exceed budget rather than trapping. WASM traps are caught at the JS boundary
and surfaced in a diagnostics overlay, so a failure produces a readable report
rather than a dead tab.

**Debugging strategy.** Because `core/` is identical on both targets, any core
bug reproduces natively where a real debugger and sanitizers are available. The
workflow is to fix in the native build and verify in the browser. Web-specific
bugs are then confined to `platform/web/` and `render/webgl2/`, which is a much
smaller surface to reason about.

## 11. Testing

`core/` is pure C++ and tests natively; Torque3D already vendors gtest. Three
layers:

1. **Parser golden tests.** JBeam, DAE, DDS, and materials.json parsers tested
   against real files from the local BeamNG install.
2. **Solver determinism.** The same input stepped N times must produce
   identical state. This is the test that keeps the solver honest and makes
   bug reports reproducible.
3. **Contract tests.** One per frozen interface in section 4.2, so the three
   workstreams cannot drift apart silently.

Browser-side verification reuses the existing CDP harness pattern from prior
work in this environment: headless Chrome, screenshot capture, console-error
assertions, and the performance gates from section 8 as failing assertions.

## 12. Open decisions

**Project location.** Defaulting to `C:\Projects\BeamNGWeb`, matching the
existing `C:\Projects\` convention. Trivial to change before the build system
lands.

**Asset mount strategy.** Defaulting to HTTP range requests against a localhost
dev server that serves the BeamNG install directory, rather than a bulk
extract-and-copy step. Avoids duplicating hundreds of megabytes and keeps the
`assets/` directory small. Revisit if the dev server proves too slow at M1.

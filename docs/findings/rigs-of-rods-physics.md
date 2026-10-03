# Rigs of Rods as a physics reference

**Question.** BeamNG's vehicles are soft-body: bodies are lattices of nodes and
beams, and they bend, crumple and tear. Torque3D's vehicles are rigid bodies
with raycast wheels. Reimplementing the former from scratch is a research
project — is there an open-source implementation to work from?

**Short answer.** Yes, and it is the right one: **Rigs of Rods** is the direct
ancestor of BeamNG.drive and implements the same node/beam model. But it is
**GPLv3-or-later**, and this project is built on MIT-licensed Torque3D, so
copying its code would relicense everything. The safe route is to work from its
*published documentation* and write our own solver — the model is small, and
the docs describe it completely.

This is a reading of public licences and documentation, not legal advice.

---

## 1. Why RoR is the right reference

Rigs of Rods has been in development since 2005 and went open source in 2009.
BeamNG.drive began as a fork of it, which is why the two share a data model:
RoR's `.truck` files and BeamNG's `.jbeam` files describe the same thing — a
lattice of nodes joined by spring-damper beams — with different names and
different syntax.

So the physics we would be porting is not a lookalike. It is the thing BeamNG
grew out of.

Repository: <https://github.com/RigsOfRods/rigs-of-rods> (~6,700 commits, active
— most recent commit Sep 2026).

## 2. The licence problem, stated plainly

| component | licence | consequence |
| --- | --- | --- |
| Torque3D (this project's engine) | MIT | permissive; no obligation beyond attribution |
| Rigs of Rods | **GPLv3 or later** | copyleft; derivative works must also be GPLv3 |
| BeamNG.drive | proprietary | no code rights at all |

The README is explicit:

> Rigs of Rods went open source under GPLv2 or later on the 8th of February,
> 2009. Rigs of Rods is now licensed under GPLv3 or later.

MIT code can be *combined* into a GPLv3 work — that direction is compatible —
but the result is GPLv3. There is no way to link RoR code into this engine and
keep distributing the result under MIT. Concretely, taking its solver would mean:

- the whole binary ships under GPLv3, with source available to anyone who gets it;
- GPLv3 §11 adds an express patent grant we would have to honour;
- GPLv3 §3 requires "installation information" for user products, which is
  awkward for a locked-down build;
- the MIT notice on Torque3D would have to be preserved alongside it.

That may be entirely acceptable — it is a real choice, not a mistake. But it is
a **one-way door** and it should be taken deliberately, not as a side effect of
copying a file.

Note also that RoR's *content* is not covered by the GPL even where the code is:
the README says community vehicles and terrains "are separate from the core
project and are not covered under the project's license". So RoR's vehicles are
not a shortcut around the BeamNG content problem either.

### Recommended route

**Read the documentation; write our own solver.** Copyright covers the
expression of a program, not the physics it computes. The node/beam model is
publicly and thoroughly documented by the RoR project itself, in prose, for the
express purpose of letting people build on it. Implementing a spring-damper
lattice from that description is ordinary engineering.

The discipline that keeps this clean:

- do not read `ActorForcesEuler.cpp` and transcribe it;
- do not copy constants, naming, or file structure;
- do write down the model from the docs first, then implement against our notes;
- keep our solver in our own files, with our own structure.

If that discipline is not wanted, then take the GPLv3 decision explicitly and
say so in the README. What is not safe is copying code while believing the
project is still MIT.

## 3. The model, in full

RoR's own documentation is unusually clear about this:

> RoR uses a very unique way to simulate a truck. In fact, **it does not
> simulates a truck at all**... It only simulates a set of points, called
> **Nodes** interconnected by **Beams**.

- **Nodes** are point masses. They are dimensionless, have mass, and collide.
  Nothing else exists as a rigid body.
- **Beams** are massless. Each is a spring and a damper in series, with a rest
  length. They have length and no thickness.
- The joint where beams meet a node is a **ball joint** — no force opposes a
  change of angle. So "anything that is not triangulated will fold", and rigid
  parts emerge only from triangulation. This is why a vehicle is a lattice and
  not a box.
- Beam behaviour is a three-stage damage model: **elastic** (returns to rest
  length), **plastic** (does not), then **snap** (the beam disappears).
- Rotation, centre of gravity and centripetal force are never computed. They
  *emerge* from the beam interactions. That is the whole trick, and it is why
  the solver is far smaller than a rigid-body engine.

This is the same model BeamNG uses, and the same reason a BeamNG car crumples
where you hit it.

## 4. Where the code lives (for reading, not copying)

```
source/main/physics/
  Actor.cpp / Actor.h            the simulated object: nodes + beams
  ActorForcesEuler.cpp           force accumulation and integration
  ActorSpawner.cpp               parses .truck into nodes and beams
  SimData.h / SimConstants.h     per-actor simulation attributes
  Differentials.cpp              axle coupling
  SlideNode.cpp                  sliding attachment points
  collision/  air/  water/       domain-specific force generators
  flex/
    FlexBody.cpp                 visual mesh driven by the node positions
    FlexMesh.cpp                 triangle -> node binding
    FlexFactory.cpp              builds flexbodies from the definition
    FlexMeshWheel.cpp            flexbody wheels
    FlexAirfoil.cpp              wing surfaces
    Flexable.h / Locator_t.h     interfaces
```

`flex/` is worth calling out separately. The flexbody is how a *visual* mesh is
bound to the simulation: each vertex is attached to nodes, so the rendered body
deforms as the lattice deforms. That is the part that makes it look like BeamNG
rather than like a physics debug view, and it is independent of the solver.

`ActorForcesEuler.cpp` names the integrator: explicit Euler. Cheap, and stable
enough at the small timesteps the model needs.

## 5. The data format, and why it maps onto jbeam

RoR's `.truck` is line-oriented, one section per keyword:

```
; node: id, x, y, z, options
3, 0.63, 0.36, 0.66, l

; beam: node1, node2, options
11, 24, s 12.5
```

Sections: `nodes`, `beams`, `wheels`, `shocks`, `hydros`, `commands`,
`rotators`, `engine`, `brakes`, `submesh`, `flexbody`, `set_beam_defaults`.

BeamNG's `.jbeam` is the same idea in JSON, with the same primitives under
BeamNG's names — `nodeWeight`, `beamSpring`, `beamDamp`, `beamDeform`,
`beamStrength`, and sections for `nodes`, `beams`, `hydros`, `wheels`. The
mapping is close to one-to-one:

| RoR `.truck` | BeamNG `.jbeam` | meaning |
| --- | --- | --- |
| `nodes` id, x, y, z | `nodes` | point mass position |
| node option `l` + kg | `nodeWeight` | mass |
| `beams` node1, node2 | `beams` | the spring-damper |
| `set_beam_defaults` spring | `beamSpring` | stiffness |
| `set_beam_defaults` damping | `beamDamp` | damping |
| `set_beam_defaults` deform | `beamDeform` | plastic threshold |
| `set_beam_defaults` break | `beamStrength` | snap threshold |
| `wheels` | `wheels` | ray or mesh wheel |
| `hydros` | `hydros` | actuator |

So a jbeam reader is a bounded piece of work: parse the JSON, map the field
names, and hand the lattice to the solver. It is the *solver* that is the real
task, and RoR's documentation hands us its shape.

Reminder: `.jbeam` files are BeamNG's copyrighted content. Read them from a
local install at runtime; never commit or ship them. See
`beamng-redistribution-policy.md`.

## 6. What this changes about the earlier plan

The earlier recommendation was to start with Torque3D's rigid-body
`WheeledVehicle` and treat soft-body as a distant milestone. RoR's documentation
changes the cost estimate, not the order:

1. **Textures and materials** — unchanged, still the biggest visual gap.
2. **A drivable car** — still worth doing first, and still fastest on Torque3D's
   existing `WheeledVehicle`. It gets a car on the road while the solver is built.
3. **Our own node/beam solver** — now a defined task rather than an open
   question: point masses, spring-damper beams, ball joints, three-stage damage,
   explicit Euler. Written from the documented model, in our own files.
4. **Flexbodies** — bind the visual mesh to the lattice so deformation is
   visible. Independent of step 3 and can land after it.

Step 3 is the one that makes it "work like BeamNG". It is no longer unbounded,
because the model is documented and small — but it is still the largest single
piece of work in the project, and it should be its own milestone.

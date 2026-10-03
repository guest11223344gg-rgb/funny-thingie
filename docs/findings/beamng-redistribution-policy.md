# Can BeamNG content be redistributed?

**Answer: no.** Not the terrain, not the level assets, not the extracted meshes or
textures. Not in this repository, not as a downloadable mod, not inside another
engine. The two documents that decide this are the End User License and Warranty
Agreement shipped with the game and the Modding Guidelines it defers to.

This note records the clauses so the question does not have to be re-litigated.
It is a reading of the published documents, not legal advice.

Sources, both from the local Steam install:

- `D:/SteamLibrary/steamapps/common/BeamNG.drive/EULA.pdf` (6 pages, 17.6 kB of text)
- `https://go.beamng.com/ModdingGuidelines`

---

## 1. The EULA makes the terrain BeamNG's copyrighted work

§ 1 *Ownership* enumerates what BeamNG owns, and the list is deliberately wide:

> All right, title, interest and ownership rights at / in the Software and any
> copyright, design right, database right, title right, patents and any rights to
> inventions, know-how, trade and business names, trade secrets and trade marks
> (whether registered or un registered), other intellectual property rights
> (together "Intellectual Property Rights"), and all copies thereof (including but
> not limited to any titles, computer code, themes, **objects**, characters,
> character names, stories, text, dialog, catch phrases, **locations**, concepts,
> **artwork**, animations, sounds, musical compositions, audio-visual effects,
> moral rights and any related documentation) are owned by, belong to and vest in
> BeamNG or its licensors.

"objects", "locations" and "artwork" cover a level: the `.ter` heightfield, the
`.dae` props, the `main.materials.json` terrain layers, the sky. § 3.1 adds that
the Software "is licensed, not sold" and that the licence "confers no title or
ownership in the Software" — so having paid for the game buys a licence to *use*
those files, not ownership of them.

## 2. Three separate clauses forbid distributing them

§ 4.1, first and second bullets:

> Unless this Agreement expressly entitles you to do so in § 2 and § 3 you are not
> entitled to:
> - sell, distribute or otherwise transfer copies or reproductions of the Software
>   to other parties in any way, nor to rent, lease or license the Software to
>   others without the prior written consent of BeamNG; or
> - use, copy, transfer or distribute **the Software or part of it** other than as
>   permitted by this Agreement;

"or part of it" is the operative phrase. A single converted `.ter` file is a part
of the Software, so uploading it is the second bullet regardless of whether it is
sold. § 3.5 closes the door on anything not explicitly granted: *"All rights no
expressly granted herein are reserved by BeamNG."*

§ 3.3 is the clause that speaks directly to this project's situation — taking
BeamNG's content and running it in a different engine:

> The License in this Agreement does not grant the right to modify the source code
> of the Software, not to integrate parts of the Software or the Software as a
> whole into another work except if permitted in our modding guidelines.

"integrate parts of the Software ... into another work" is exactly what porting a
BeamNG map into Torque3D is. It is permitted only to the extent the Modding
Guidelines permit it — and they do not permit it (see § 3 below).

## 3. The Modding Guidelines close the escape hatch § 3.3 leaves open

§ 3.3 defers to the guidelines, so the guidelines are not optional colour — they
are the terms. Under *To avoid*:

> - You are **not allowed to use copyrighted content and content that belongs to
>   other users** without permission in your mods.
> - You **must not overwrite any default game data**. This is also valid for parts
>   within jbeam files, mesh names within .dae files or objects within your
>   materials.json files.

and under *Recommendations*:

> - You have to be **the author of the mod** and/or **have permission** if you want
>   to use content from another user.

> - Please do not copy a whole map/car to simply add a single detail.

Two things follow. First, re-shipping the map is "copy a whole map" — named and
forbidden. Second, a BeamNG map that originated as a *community* mod is not
BeamNG's to license either: the guidelines require the original author's
permission, so redistributing it breaches the EULA *and* the modder's copyright.

## 4. What is actually permitted

The EULA is not silent on modding — it carves it out explicitly. § 4.2:

> - in whole or in part, reverse engineer, merge, translate, disassemble or
>   decompile the Software (**Modding of the Software's content files is not
>   reverse engineering**)

So the parenthetical confirms that editing and converting the content files is
permitted modding, not prohibited reverse engineering. The distinction that
matters is **local modification vs. redistribution**:

| Action | Verdict | Basis |
| --- | --- | --- |
| Converting a map for your own use on your own machine | Allowed | § 4.2 parenthetical |
| Committing BeamNG `.ter` / `.dae` / textures to a public repo | **Forbidden** | § 4.1 "or part of it" |
| Publishing the converted level as a downloadable mod | **Forbidden** | § 4.1; guidelines "copy a whole map" |
| Shipping BeamNG assets inside another engine's game | **Forbidden** | § 3.3 "integrate parts ... into another work" |
| Publishing *your own* converter tool, containing no BeamNG assets | Allowed | your own code |
| A tool that converts the user's own local copy, on their machine | Allowed | user exercises their own § 4.2 right |
| Mods containing only your original content | Allowed | guidelines: "you have to be the author" |
| Commercial, military or governmental use | Separate licence | § 3.6, `licensing@beamng.gmbh` |

The fourth and fifth rows are the pattern this repository already follows and
should keep following: `tools/steam-level.py` is *our* code, it reads from a
Steam install the user already owns, and it writes into a git-ignored directory.
That is the standard, defensible shape for a content converter. The moment the
same script also shipped a pre-converted `.ter` so users did not need the game,
it would become a redistribution of BeamNG's work.

## 5. Consequence of getting it wrong

§ 6.2: *"This License will terminate automatically if you fail to abide by any of
the terms and conditions."* Breach is not a warning-then-fix situation; it
terminates the licence. § 4.2's final bullet adds that *"A breach of the preceding
obligations entails BeamNG's right to terminate this Agreement for any cause."*

## 6. Standing position for this repository

Already implemented, and the reason it is safe:

- `.gitignore` excludes `assets/`, commented *"BeamNG content — licensed material,
  never committed, never deployed."*
- `third_party/*` is ignored and disposable, so the generated
  `data/BeamNGMaps/` tree is not tracked either.
- The only tracked artefacts are our own code, patches and documentation.

Rules to hold to:

1. Never commit BeamNG `.ter`, `.dae`, `.dds`, `materials.json` or level zips.
2. Never publish the generated `data/BeamNGMaps/` tree.
3. Keep the converter as a *tool that requires a local install*, never a bundle.
4. Attribute the source in docs (BeamNG.drive, version, path) without shipping it.
5. If redistribution is genuinely wanted, ask BeamNG first — in writing:
   `licensing@beamng.gmbh`. § 4.1 and § 3.6 both contemplate a separate agreement.

One further caveat worth stating: some BeamNG maps are built from real-world
elevation or third-party data. Even where such a source is separately licensed,
BeamNG's *conversion* of it is their derivative work, so the analysis above is
unchanged — and the original rights holder would be an additional permission to
seek, not a substitute for BeamNG's.

# nxopen-journal

[中文](README.md) | English

An agent skill for Siemens NX 12 (verified on NX 12.0.0.27 only). Install it and your agent
(ZCode, Codex CLI, Claude Code, ...) writes NXOpen Python journal scripts for you, replays them
headlessly through NX 12 in batch mode, and produces solid models, assemblies, Drafting drawings,
NX Nastran FEA results and NX Motion simulations. You do not need to know NXOpen or Python.

The skill itself is written in Chinese: `SKILL.md` and `references/*.md` are the working documents
your agent reads. This page is the English entry point.

## What it covers

| Domain | Covered |
| --- | --- |
| Modeling | sketches, extrude and revolve, boolean, shell and draft, patterns (linear, circular, along path, helix, polygon, general, reference), four hole-package types, layers and categories, STL export |
| Assembly | assembly structure, mating constraints, draggable mechanism, two routes to a revolute joint, two geometric routes for interference checking |
| Drafting | base and projected views, detail view, sections (stepped, half, revolved), dimensions and centrelines, radius dimensions |
| FEA | Nastran SOL101 static, 2D shell mesh, solve-level calibration, solution and boundary-condition descriptors |
| Motion | links and joints, drivers, solving, result extraction |

Five tools come with it: `scripts/check_journal.py` (static check of a journal against
a rule base of measured NX 12 pitfalls), `scripts/run_journal_batch.bat` (headless replay),
`scripts/gb_drawing.py` (GB-style drawing kit: A4 frame, pinned views, title block, tech
note and dimension lanes — any journal can `import gb_drawing`), the case standard layer
`scripts/nxlib/` (test framework plus recipes for five domains such as modeling, assembly
and drafting; regression cases import it instead of copying their own), and the offline figure
chain in `scripts/render/` (batch sessions cannot capture images, so solids are rendered
from STL outside NX and drawing PDFs are rasterised on the host).

## Figures from real runs

Every image below was produced by a batch replay on this machine, not a mock-up. Six cold-start
agents, each with no memory, ran the six modules independently: each received only the skill
documents and one task sentence, then designed its own part, wrote the journal, passed static
checks, replayed in batch and verified itself; the coordinator only accepted the final figure.
Solids and assemblies are rendered outside NX from STL exported by the same run (a batch session
cannot capture an image, see limitations), the drawings are PDFs the run wrote directly, and both
charts plot real solve data written to disk.

| Modeling: bearing pedestal, ribs, hole pattern (trimetric render) | Assembly: plate, pins, bushing and cap, mates colour-coded |
| --- | --- |
| <img src="images/modeling.png" width="400"> | <img src="images/assembly.png" width="400"> |

The assembly figure colour-codes the four red pins, the gold bushing and the dark cap on the grey
base plate. 13 persistent constraints hold the seven components and every pose was read back and
verified against its design value.

| Drafting: three views, section A-A, dimensions, centrelines | GB drawing: A4 sheet, frame, title block, notes |
| --- | --- |
| <img src="images/drafting-annotation.png" width="400"> | <img src="images/gb-drawing.png" width="400"> |

All nine dimensions in the drafting figure are UF-related objects attached to geometry, and the PDF
text layer was token-checked with pymupdf. The GB figure's sheet, frame, title block and general
notes come from the skill's gb_drawing module in one pass.

| FEA: SOL101 cantilever vs beam theory (two panels) | Motion: rocker angle and angular velocity vs analytic (720 steps) |
| --- | --- |
| <img src="images/fea.png" width="900"> | <img src="images/motion.png" width="900"> |

The FEA figure overlays the real 14998-node displacement field on beam theory (free-end ratio 0.982)
and samples bottom-fibre stress against the analytic distribution (ratio 1.000 mid-span; the
Saint-Venant corner region is shaded and not used as a criterion). The motion figure plots per-frame
data of a 720-step solve: the rocker swing span differs from the closed form by 0.0014 degrees and
the reversal count matches.

## Requirements

| # | Requirement | How to check | If missing |
| --- | --- | --- | --- |
| 1 | Windows + Siemens NX 12 (verified on 12.0.0.27; NX 11 and older, NX 13 and newer are unverified) with the NXOpen automation interface | `%NX_HOME%\NXBIN\run_journal.exe` exists | Batch replay cannot run; none of the 35 cases work, only the static check is left |
| 2 | `NX_HOME` pointing at the NX install root | defaults to `D:\UG-NX12`; set `NX_HOME` if yours is elsewhere | The batch wrapper prints an error and exits with code 2 instead of silently using the wrong path |
| 3 | An agent that loads skills | put the directory into your agent's skill directory and let the agent read `SKILL.md` | The skill never triggers. Routing comes from the frontmatter of `SKILL.md`; nothing to compile or register |
| 4 | Python 3 on the host | `python -V`. Only `check_journal.py` and the PDF value check need it (the latter also needs pymupdf) | Journals are unaffected: NX runs them with its embedded interpreter, which is Python 3.6.1 |
| 5 | NX Nastran solver licence | the solve log prints a `NASTRAN LICENSE:` line near the top | Cases 09 and 25 cannot run; everything else can. These two really call the solver, they are not optional |
| 6 | nxopen MCP | see below | Optional; read the dependency notes first |

### nxopen MCP

The MCP server is a separate project ([nxopen-mcp](https://github.com/mingfeng6684/nxopen-mcp)) and
is the main defence against hallucinated APIs: it looks answers up in NX's own API documentation.
Half of its tools need a local embedding service.

Upstream publishes no version number, no tags and no releases, so the only thing that can be stated
is how to install it: `pip install "nxopen-mcp[embed,reflect]"` (upstream requires Python 3.11+), or
`uvx nxopen-mcp` to run it without installing. The author's machine has an editable install of the
source, local version 0.2.0, and the `NXOPEN_MCP_*` environment variables below are written for that
version. What matters more than the version: build the index once against your own NX installation,
and use the same embedding model for the index and for the queries.

| Tool | Needs | When the embedding service is down |
| --- | --- | --- |
| `get_class` / `get_member` | local index | works |
| `search_api` / `find_builder` | local index + embedding service | fails; there is no keyword-search fallback |

Any OpenAI-compatible `/v1/embeddings` endpoint works (`llama-server --embedding`, Ollama,
LM Studio) as long as it serves `bge-m3` (1024 dimensions). Point the MCP at it:

```
NXOPEN_MCP_EMBEDDER=llama
NXOPEN_MCP_OLLAMA_URL=<your endpoint, e.g. http://127.0.0.1:11436>
NXOPEN_MCP_OLLAMA_MODEL=bge-m3
```

## Install

Hand the block below to your agent, replacing the first line with where you got the skill from.
The agent does the rest, including the local adaptation.

```text
Install the nxopen-journal skill: <paste the source here>

Requirements:
1. Put it into your skill directory, keeping the directory name nxopen-journal
   (Codex CLI: ~/.codex/skills/, ZCode: ~/.zcode/skills/, Claude Code: ~/.claude/skills/;
   follow your own agent's documentation);
2. Read SKILL.md before writing anything and follow its rules and verdict criteria;
3. Adapt to this machine and report each item, saying what is missing rather than guessing:
   - NX install root: confirm %NX_HOME%\NXBIN\run_journal.exe exists. NX_HOME defaults to
     D:\UG-NX12; if NX lives elsewhere, set it. An unresolvable path prints
     ERROR: run_journal.exe not found under NX_HOME=... and exits with code 2;
   - Replay check: run scripts\tests\RUN_TESTS.bat and report every case;
   - nxopen MCP: if present, confirm the semantic-search embedding service works; if not, say
     that API checks will fall back to dir() and the UGOPEN headers;
   - NX Nastran: cases 09 and 25 really call the solver; if they fail, report whether the
     module or the licence is missing;
4. Finally list everything that does not match this machine and needs my decision.
```

### Day-to-day use

Describe the job in plain language, for example:

> With nxopen-journal, model a 120x80x12 bracket with four corner M8 counterbore holes and
> export three views.

The agent reads `SKILL.md`, then the domain file for the task, writes the journal, runs the static
check, and replays it. The output is `.prt` files and drawings.

### Verify the install

Run the full regression suite once; a final summary line of all tests passed means this machine is
ready:

```
> scripts\tests\RUN_TESTS.bat
PASS 27_radius_dim.py
PASS 28_pattern_helix.py
PASS 29_interference.py
PASS 30_fea_descriptors.py
PASS 31_drafting_sections.py
PASS 32_pattern_enums.py
PASS 33_gb_sheet.py
PASS 09_fea_static.py
PASS pdf value check - test 19 annotation values
=== ALL TESTS PASSED ===
```

32 gated cases pass, plus three one-shot API probes that are kept as evidence and are not part of
the check. By default the run deletes the artifacts under `scripts/tests/parts/`, including the
Nastran intermediate files, because every run rebuilds them completely.

## Regression cases

The suite is grouped by domain; what each case covers and how its negative check is done is
recorded in `scripts/tests/README.md`.

| Domain | Cases |
| --- | --- |
| Modeling | 01 02 03 05 08 14 15 22 26 28 32 34 |
| Assembly | 04 10 16 17 29 35 |
| Drafting | 06 07 19 20 21 27 31 33 |
| FEA | 09 24 25 30 |
| Motion | 18 23 (16 and 17 cover assembly-level joints) |

Three further one-shot API probes are not part of the check and are kept as historical evidence.

## Why this skill

Writing NX scripts is not hard because of syntax: it is hard because you cannot tell from the
documentation which call actually works in NX 12 batch mode and which one takes the process down.
That is where an agent falls flat. This skill turns those judgements into instructions:

- Every conclusion comes from a real run. The six domain files and the suite notes carry 286
  measured annotations across 18 dates, the earliest 2026-08-05. The bar for adding one is explicit:
  first confirm the API exists through nxopen MCP, then pass a minimal real run in NX 12 batch mode.
- Every conclusion has a case guarding it. `scripts/tests/` holds 35 cases, 32 of them gated. If a
  conclusion stops holding, its case fails instead of quietly going stale, and the cases themselves
  were checked in reverse: change something and run `scripts\tests\RUN_TESTS.bat`.
- Dead ends are already mapped: 62 "when you hit this, do that" entries across the domain files and
  `SKILL.md` — for interference checking you get the boolean-intersect route and the
  `SimpleInterference` route, for threaded holes you get "pilot hole plus annotation".

## Known limitations

- Verified only on NX 12.0.0.27 and Windows; other NX versions are unverified.
- A batch session cannot capture an image: the image-capture builder commits without writing a file,
  and `Disp.CreateImage` raises a memory access violation. View orientation and rendering style do
  work. So images come from two routes instead: drawings as PDF out of Drafting, and solid geometry
  as STL rendered outside NX, which is where this README's model and assembly figures come from.
- Case 26 keeps one native crash as a boundary record, which is why exit codes cannot be used as the
  verdict. The crash happens in its own NX process, and the skill never writes into your NX
  installation.
- Of the nine pattern types, `Linear`, `Circular`, `AlongPath`, `Helix`, `Polygon`, `Spiral`,
  `General` and `Reference` all produce instances through `PatternFeatureBuilder` (cases 01, 02, 22,
  28, 32); `Mirror` is rejected at commit, so mirrored features go through
  `Features.MirrorFeatureBuilder` (case 03).
- The skill only generates scripts and evidence; it never modifies your NX installation, and both
  scripts and models land in your working directory.

## Repository layout

```
nxopen-journal/
├── SKILL.md                        entry layer: rules / environment / skeleton / common operations / logging / workflow / routing
├── references/                     six domain files: modeling / assembly-drafting / drafting-annotation / fea / motion / gb-drawing
├── images/                         figures from real runs
├── scripts/
│   ├── gb_drawing.py               GB-style drawing kit (frame / pinned views / title block / tech note / dimension lanes / PDF)
│   ├── nxlib/                      case standard layer (test framework + recipes for five domains, imported by the cases)
│   ├── check_journal.py            static check (AST + rule base of measured pitfalls)
│   ├── check_repo.py               repo self-check (Py3.6 syntax / case list / doc structure / file list / standard-layer exclusivity)
│   ├── run_journal_batch.bat       single-file batch replay (NX_HOME parameterised)
│   ├── render/                     offline figure chain (shaded STL rendering, PDF rasterising, trim and scale bar)
│   └── tests/                      regression suite (32 gated cases + 3 one-shot probes) plus its own README
└── agents/openai.yaml              Codex / OpenAI front-end config for cross-agent portability
```

The repository ships a cloud CI (`.github/workflows/ci.yml`) that runs the Python 3.6 syntax check,
`check_journal.py` and `scripts/check_repo.py` on every push; none of the three needs NX. The
regression suite itself needs a machine with NX 12 installed.

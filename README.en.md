# nxopen-journal

[中文](README.md) | English

Let an agent write NX 12 journals from natural language and replay them in batch to produce models and drawings.

`NX 12 (12.0.0.27)` · `NX Python 3.6.1` · `Host Python 3.11+` · `v1.7.1` · `MIT`

## Contents

- [Background](#background)
- [Features](#features)
- [Layout](#layout)
- [Installation](#installation)
- [Behavior and limitations](#behavior-and-limitations)
- [Tests](#tests)
- [License](#license)

## Background

The hard part of NXOpen journals is not syntax but whether a call survives NX 12 batch execution. This skill turns verified findings into recipes: every conclusion is first checked against the nxopen MCP for API existence, then run in NX 12 batch; conclusions that can be pinned down get a regression case. The agent reads `SKILL.md` to pick a domain, reads that domain's reference file, writes the journal, passes the static checker, and replays it in batch.

It covers 3D modeling, assemblies, Drafting, Nastran FEA, Motion simulation, and reverse reconstruction, plus a set of deliverable gates. Real outputs for all six domains are in the [nxopen-journal-toolkit](https://github.com/EVOL233awa/nxopen-journal-toolkit) README; this repository keeps only the skill sources, references, and regression suite.

## Features

| Domain | Covered |
| --- | --- |
| 3D modeling | Sketches, extrude/revolve, booleans, shell/draft, nine pattern types, three non-threaded hole types in the hole package, layers and categories, STL export |
| Assemblies | Assembly structure, mating constraints, draggable mechanisms, two routes for revolute joints, two geometry routes for interference checks; ball, cylindrical, hinge, and slider joints belong to Motion |
| Drafting and GB drawings | Three views, projected views, detail views, sections, assembly balloons/sections/title blocks, dimensions, centerlines; GB frames, line weights, fonts, and first-angle placement handled by `gb_drawing.py` |
| FEA | Nastran SOL101 static analysis, 2D shell meshes, solve-level calibration, boundary-condition descriptors; requires an NX Nastran solver license |
| Motion simulation | Links, revolute joints, slider joints, gear couplers, drivers, solving, result extraction; frame 0 is t=0 |
| Reverse reconstruction | Extracts a structure list and sections from a featureless solid, rebuilds an editable model by structural features; independently re-computes sections, holes, volume, bounding box, four views, and two-way deviation |
| Deliverable verification | STEP/STL/DXF/occupancy/PDF gates with three-state `PASS`/`FAIL`/`NO_SIGNAL`; host-side entry points `check_deliverables.py`, `run_journal_checked.py`, `api_index.py` |

Supporting scripts: `check_journal.py` static checks, `run_journal_batch.bat` batch replay, `nxlib/` test standard layer, `render/` offline rendering chain, and the `tests/` regression suite.

## Layout

```text
nxopen-journal/
├── SKILL.md                  entry layer: rules / environment / skeleton / logs / workflow / domain routing
├── README.md / README.en.md  Chinese and English documentation
├── CHANGELOG.md              version history
├── references/               nine domain files
├── scripts/
│   ├── check_journal.py      static checks
│   ├── check_repo.py         repository self-check
│   ├── run_journal_batch.bat batch replay
│   ├── gb_drawing.py         GB drawings
│   ├── nxlib/                test standard layer
│   ├── render/               offline rendering chain
│   └── tests/                54 case files + RUN_TESTS.bat
├── docs/wiki/                maintainer guide
├── .github/workflows/ci.yml  cloud CI
└── agents/openai.yaml        Codex/OpenAI config
```

## Installation

Quick start: copy the whole block below to an agent on any host. It clones this repository, confirms the NX environment, and runs the static check and regression suite. Changes are in [CHANGELOG.md](CHANGELOG.md).

```text
Task: install and verify nxopen-journal.
1. Clone it into the agent's skill directory, keeping the name nxopen-journal.
2. Confirm NX_HOME and %NX_HOME%\NXBIN\run_journal.exe; NX embedded Python is 3.6.1.
3. Run python scripts\check_repo.py and confirm the output CHECK_REPO_OK.
4. Run scripts\tests\RUN_TESTS.bat and confirm the last line === ALL TESTS PASSED ===, with no _FAIL, FATAL, or SKIP in the log.
5. Report the install path, NX version, NX_HOME, Python version, and both check results; on failure report the case number, failed item, and the last 50 log lines.
```

Or install manually with the steps below.

### Prerequisites

| Requirement | Detail | If missing |
| --- | --- | --- |
| OS | Windows 11 | Batch execution and regression tests cannot run |
| NX | Siemens NX 12 (verified 12.0.0.27) with the NXOpen automation interface | Only static checks remain |
| `NX_HOME` | NX install root; defaults to `D:\UG-NX12` | Batch fails with exit code 2 |
| Agent | An agent that can load skill directories | The skill will not trigger |
| Python | Host 3.11+ | Journals are unaffected; checks and MCP are unavailable |
| NX Nastran license | The solve log prints `NASTRAN LICENSE:` | Cases 09 and 25 cannot run; the rest still work |
| nxopen MCP (optional) | See below | Fall back to `dir()` and UGOPEN headers when writing API calls |

NX journals run on NX 12 embedded Python 3.6.1, independent of host Python; the two are not interchangeable.

### Configuration

| Setting | Description | Default |
|---|---|---|
| `NX_HOME` | NX install root | `D:\UG-NX12` |
| `KEEP_PARTS` | Keep `scripts/tests/parts/` when `RUN_TESTS.bat` runs | unset (clean) |

### Manual installation

1. Put the repository in your agent's skill directory, keeping the name `nxopen-journal`:

   ```bash
   git clone https://github.com/EVOL233awa/nxopen-journal
   ```

   Codex CLI uses `~/.codex/skills/`, Claude Code uses `~/.claude/skills/`; other agents follow their own skill directory convention.

2. Confirm `NX_HOME` and `%NX_HOME%\NXBIN\run_journal.exe`. Set `NX_HOME` first if NX is installed elsewhere.

3. Static check:

   ```bash
   python scripts/check_repo.py
   ```

   `CHECK_REPO_OK` means it passed.

4. Full regression:

   ```bat
   scripts\tests\RUN_TESTS.bat
   ```

   The last line is `=== ALL TESTS PASSED ===`, and the log contains no `_FAIL`, `FATAL`, or `SKIP`.

5. After installation, describe the task in natural language:

   > Use nxopen-journal to build a 120×80×12 bracket with four M8 counterbores and export three views.

### nxopen MCP (optional)

The most common journal error is a wrong API name or signature. The nxopen MCP indexes your local NX documentation so the agent can look up classes, members, and signatures that actually exist.

- Full install: use `nxopen-journal-toolkit`; `nxjt install` registers the MCP and `nxjt index` builds the index.
- MCP only: this fork [`nxopen-mcp-enhanced`](https://github.com/EVOL233awa/nxopen-mcp-enhanced) 1.0.0, or upstream [`nxopen-mcp`](https://github.com/mingfeng6684/nxopen-mcp) v0.2.0.
- Build the index: `nxopen-mcp-enhanced index --nx-path <NX install root>` or `nxopen-mcp index --nx-path <NX install root>`.

The skill works without it; queries that mix Chinese with English terms (for example `创建拉伸特征 extrusion`) hit better, while short Chinese-only terms are unreliable.

## Behavior and limitations

- When `NX_HOME` is unset: batch looks for NX under the default `D:\UG-NX12`; if not found, it exits with code 2.
- When a journal enters NX: the interpreter is fixed at 3.6.1, so `math.dist`, `math.prod`, `math.isqrt`, f-string `=`, dict merge operators, and `functools.cache` are unavailable; run `check_journal.py` before execution.
- When `RUN_TESTS.bat` runs: it clears `scripts/tests/parts/` by default; set `KEEP_PARTS=1` to keep artifacts; judgments read log tokens, not exit codes.
- When a deliverable gate cannot see its instrument: it returns `NO_SIGNAL`, not `FAIL`. ASCII DXF can be checked without `ezdxf`; binary DXF without the library can only return `NO_SIGNAL`.
- Only Windows 11 + NX 12.0.0.27 is verified; other platforms and versions are untested.
- Batch mode cannot take screenshots; images come from Drafting PDF or external STL rendering.
- Case 26 keeps one native crash record at the `ThreadedHole` boundary; judgments read log tokens.
- The drawing PDF gate proves only that a text layer exists, not that the content is complete; title blocks and Chinese technical notes are read back from the NX model side.
- Of the nine pattern types, `Mirror` is rejected at commit time; feature mirroring uses `Features.MirrorFeatureBuilder`.
- Reverse reconstruction does not guarantee a one-pass result on complex parts; this version provides a structure list, an editable feature tree, and an independent re-computation acceptance chain.
- The skill only generates scripts and artifacts; it does not modify the NX installation directory.

## Tests

The suite has 54 case files = 51 gated cases + 3 one-off API probes. What each case covers and how it is negatively verified are in `scripts/tests/README.md`.

| Domain | Cases |
| --- | --- |
| 3D modeling | 01 02 03 05 08 14 15 22 26 28 32 34 37 |
| Parametrics and audit | 41–48 |
| Assemblies | 04 10 16 17 29 35 |
| Drafting | 06 07 19 20 21 27 31 33 54 |
| FEA | 09 24 25 30 |
| Motion | 18 23 36 (16/17 cover assembly-level joints) |
| Measurement and reverse | 38 39 40 49 |
| Deliverable verification | 50 51 52 53 |

```bash
python scripts/check_repo.py
scripts\tests\RUN_TESTS.bat
```

## License

MIT. See [LICENSE](LICENSE).

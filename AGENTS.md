# AGENTS.md

This file provides guidance to coding agents working in this repository. `CLAUDE.md` is a one-line
pointer to this file — keep the guidance here, not there.

## What this repository is

`nicer-nisar` is a team project repo for the NASA Responsible GenAI Hackweek 2026. It is an exploratory
learning project, not a production codebase. As of now it is essentially the hackweek template plus a
pixi environment — `notebooks/`, `scripts/`, and the `contributors/` folders still hold empty or stub
placeholder files.

The subject matter is **NISAR** (NASA-ISRO Synthetic Aperture Radar) data, and the research question is
meta: *do agentic AI enhancements (Skills, MCP servers, `llms.txt`-style docs) actually improve outcomes
for real scientific workflows?* The two target workflows are glacier velocity from pixel tracking/offsets,
and snow melt timing / snow depth, each for a given area of interest and time range, working from the
[ASF NISAR User Guide](https://nisar-docs.asf.alaska.edu) and its linked references.

Two consequences for how you should work here:

1. **Agent-facing artifacts are deliverables, not scaffolding.** `SKILL.md` files, MCP server code, and
   prompt/context experiments are the point of the project — treat them as first-class source, and expect
   to be asked to write, evaluate, and compare them.
2. **Failures are results.** Goal 2 in the README is to document fail cases of status-quo agentic AI on
   NISAR data alongside the wins. When a workflow you attempt goes wrong or a tool returns something
   misleading, record what happened rather than quietly routing around it.

See `README.md` for the full problem statement, collaborator list, and goals.

## Environment

Managed by [pixi](https://pixi.sh) (`pixi.toml` + `pixi.lock`). A conda `environment.yml` previously
existed and was deliberately removed — do not reintroduce it.

```bash
pixi install                 # materialize the environment from pixi.lock
pixi run python ...          # run a command inside the environment
pixi shell                   # interactive shell in the environment
pixi add <package>           # add a conda-forge dependency (updates pixi.toml + pixi.lock)
pixi add --pypi <package>    # add a PyPI-only dependency
```

Always add dependencies with `pixi add` so the lock file stays in sync; never hand-edit `pixi.lock`
(`.gitattributes` marks it binary/generated, so it will not show a useful diff).

`platforms` is `["osx-arm64", "linux-64"]`, so Apple Silicon laptops and Linux CI / cloud JupyterHubs
both resolve. Intel Macs or Windows need `pixi workspace platform add osx-64` (or `win-64`) first.

Current dependencies (all conda-forge): `python >=3.14.7,<3.15`, `earthaccess`, `rioxarray`,
`virtualizarr`, `icechunk` — enough to search/authenticate against NASA Earthdata, read rasters, and try
the VirtualiZarr + Icechunk access pattern the README proposes. Anything else the workflows need
(`asf_search`, plotting, pixel-tracking libraries) still has to be added with `pixi add`.

There are no tests and no linter config, and `[tasks]` in `pixi.toml` is present but empty. If you add a
task, define it there so it runs as `pixi run <task>` rather than documenting a bare shell command.

## Repository layout conventions

These come from the hackweek template and exist to avoid merge conflicts between team members:

- `contributors/<github-username>/` — each person's personal scratch space for exploration. Put
  in-progress and per-person work here; do not edit another contributor's folder without being asked.
  `contributors/team_member_1/` and `team_member_2/` are leftover template stubs, not real people.
- `notebooks/` — notebooks that are **delivered results** for the team. Promote work here once it is
  presentable, not while it is still exploratory.
- `scripts/` — shared non-notebook code (`.py`, `.sh`) used by more than one person.
- `model-card.md` — still the unmodified template text; only fill it in if the project actually trains or
  applies an ML model.

## Data handling

NISAR is a very large-data mission (~80 TB/day globally); workflows here deliberately scope to a small AOI
and date range. `.gitignore` excludes `*.h5`, `*.hdf`, `*.hdf5`, `*.nc`, and `*.tif` — keep downloaded
granules and derived rasters out of git and reference them by access pattern (earthaccess / asf_search
query, S3 URL) in code instead of committing them.

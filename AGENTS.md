# AGENTS.md

Guidance for coding agents in this repository.

## What this repository is

`nicer-nisar` is a team project repo for the NASA Responsible GenAI Hackweek 2026. It is an exploratory
learning project, not a production codebase.

See `README.md` for the full problem statement, collaborator list, and goals.

## Environment

Managed by [pixi](https://pixi.sh) (`pixi.toml` + `pixi.lock`).

```bash
pixi install                 # materialize the environment from pixi.lock
pixi run python ...          # run a command inside the environment
pixi shell                   # interactive shell in the environment
pixi add <package>           # add a conda-forge dependency (updates pixi.toml + pixi.lock)
pixi add --pypi <package>    # add a PyPI-only dependency
```

Always manage any package changes with `pixi`.
(`.gitattributes` marks it binary/generated, so it will not show a useful diff).

There are no tests and no linter config.

## Repository layout conventions

- `contributors/<github-username>/` — each person's personal scratch space. DO NOT edit other people's folders.

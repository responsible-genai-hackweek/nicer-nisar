# Python environment and package management

Managed by [pixi](https://pixi.sh) (`pixi.toml` + `pixi.lock`).

```bash
pixi install                 # materialize the environment from pixi.lock
pixi run python ...          # run a command inside the environment
pixi shell                   # interactive shell in the environment
pixi add <package>           # add a conda-forge dependency (updates pixi.toml + pixi.lock)
pixi add --pypi <package>    # add a PyPI-only dependency
```

Always manage any package changes with `pixi`.
(`.gitattributes` marks pixi.lock binary/generated, so it will not show a useful diff).

For further information, use this https://pixi.prefix.dev/latest/llms.txt


# Development

Dev environments are managed with [uv](https://docs.astral.sh/uv/) for
reproducibility: `uv.lock` pins the exact version of every dependency, and
`.python-version` pins the interpreter used by default.

```bash
uv sync --extra dev   # creates .venv, installs locked deps
uv run pytest
```

`uv sync` reads `uv.lock`, so everyone (and CI) gets identical dependency
versions. Re-run `uv lock` and commit the updated `uv.lock` whenever
`pyproject.toml`'s dependencies change.

## Running CI checks locally

CI runs the test suite on Python 3.11-3.14 and PyPy 3.11, plus lint,
typing and docs jobs, via [tox](https://tox.wiki) (using the [tox-uv](https://github.com/tox-dev/tox-uv)
plugin, so tox itself uses uv to create envs and can fetch missing
interpreters). To run the exact same checks locally:

```bash
uv run tox            # test envs for every interpreter tox/uv can find or fetch, + lint, typing, docs
uv run tox -e py312   # test a single interpreter
uv run tox -e lint    # lint only
uv run tox -e typing  # mypy and pyright, on src/ and tests/typing/
```

`tests/typing/check_*.py` check how mypy and pyright see code using mmth:
never run, only type-checked (`--strict` for mypy, and strict mode via
`tests/typing/pyrightconfig.json` for pyright). Each line where an error is
expected carries an ignore comment for each checker, e.g.
`# type: ignore[arg-type]  # pyright: ignore[reportArgumentType]`, and both
report an ignore comment that's no longer needed, so a missing error fails
too.

To test against a specific interpreter that isn't already on your machine,
have uv fetch it first, e.g. `uv python install 3.14` or
`uv python install pypy3.11`.

## Building the docs

The documentation is a [MkDocs](https://www.mkdocs.org/) site using the
Material theme, with the API reference generated from docstrings by
[mkdocstrings](https://mkdocstrings.github.io/). It is hosted on Read the
Docs (see `.readthedocs.yaml`).

```bash
uv sync --extra docs
uv run mkdocs serve          # live-reloading preview
uv run mkdocs build --strict # what CI and Read the Docs run
uv run tox -e docs           # same, via tox
```

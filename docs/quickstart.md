---
title: Quickstart
description: Create a CANOE project and run the pipeline, in three commands
---

# Quickstart

From nothing to a solved TEMOA model in three commands. The [Get Started](get_started.md)
tutorial explains each step and how to change it.

## Before you start

- [uv](https://docs.astral.sh/uv/getting-started/installation/), the Python package
  manager CANOE uses. It installs the right Python for you.
- About 5 GB of free disk space, for the data cache.
- A solver: the project uses Gurobi, which needs a license (free for academics). See
  [Solvers](get_started.md#solvers) for the open-source alternative.

## Run it

```bash
# 1. Create a project: answer the questions, and let it install the data cache
uvx --from git+https://github.com/CANOE-main/CANOE canoe init project-hydrogen

# 2. Install canoe into the project
cd project-hydrogen
uv sync

# 3. Run the pipeline: compile, your edits, representative periods, TEMOA
uv run main.py
```

`project-hydrogen` is a placeholder: replace it (in every command) with a name that
says what your project studies, keeping the `project-` prefix.

`canoe init` asks:

| Question | Example |
|---|---|
| Folder of your CANOE data cache | empty, to keep one inside the project |
| Project name | `project-hydrogen` |
| Short description | `Hydrogen in Quebec's industry` |
| Scenario | `all-high` |
| Provinces to model | `QC` (space to toggle, enter to confirm) |
| Install the data cache now? | `Y` (about 2 GB) |

The compiled database is written to `canoe-pwd/all-high/canoe.sqlite`, and TEMOA writes
its results into the reduced copy next to it (`canoe-pwd/all-high/canoe_16d.sqlite`),
with its logs in `temoa-outputs/all-high/`.

## Next steps

- [Get Started](get_started.md): the tutorial, from the project files to editing the
  database and making your own scenario.
- [Configuration Reference](reference/index.md): every setting of the TOML files.
- [Using the published database](published_database.md): start from the published
  master database instead of compiling your own.

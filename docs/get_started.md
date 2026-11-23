---
title: Get Started
description: Create a CANOE project, run the pipeline step by step, and make it your own
---

# Get Started

This tutorial creates a CANOE project, runs the whole pipeline (compile the database,
edit it, reduce it to representative days, solve it with TEMOA), and then changes it:
editing the database from code, changing the configuration and making a scenario of
your own.

Along the way we build `project-hydrogen`, a project modelling Quebec. One province
keeps every step fast; nothing here is specific to it.

!!! note "`project-hydrogen` is an example"
    Use a name that says what your project studies (`project-<name>`), and replace
    `project-hydrogen` with it in the commands below.

!!! tip "In a hurry?"
    The [Quickstart](quickstart.md) has just the commands.

## Before you start

You need:

- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**, the Python package
  manager CANOE uses. It downloads the right Python (3.12) by itself, so you don't need
  to install Python first.
- **About 5 GB of free disk space** for the data cache (a 2 GB download, unpacked).
- **A solver** for TEMOA. The project is set up for Gurobi, which needs a license (free
  for academics); [Solvers](#solvers) shows how to use the open-source HiGHS instead.

## 1. Create a project

```bash
uvx --from git+https://github.com/CANOE-main/CANOE canoe init project-hydrogen
```

`uvx` runs the `canoe` command without installing it anywhere; `canoe init` creates the
folder `project-hydrogen` (it must be new or empty) and asks:

**Folder of your CANOE data cache.** Leave it empty to keep the cache inside the
project, or give the folder of a cache you already have (see [the data
cache](#2-the-data-cache)).

**Project name.** Pre-filled with the folder name (`project-hydrogen`): press Enter to
keep it or type another. Projects are named `project-<name>` so they're easy to
recognize.

**Short description.** One line, for the project's README.

**Scenario.** The set of configuration files to start from. `all-high` models every
sector at high resolution (more scenarios will come).

**Provinces to model.** All ten are selected; press space to toggle one and enter to
confirm. For this tutorial, keep only `QC`.

**Install the data cache now?** Asked if the cache folder doesn't have the data yet.
Answer `Y` to download it (about 2 GB), or `n` to do it later.

!!! info "No questions"
    `canoe init project-hydrogen --defaults` takes every default (all provinces, cache
    in the project, project named after the folder) and doesn't download anything.

### What you get

```
project-hydrogen/
├── main.py                    # the pipeline, step by step
├── README.md                  # your project's README
├── pyproject.toml             # the project's dependencies: canoe[solvers]
├── .python-version            # 3.12
├── config/
│   └── all-high/              # one folder per scenario
│       ├── full-pipeline.toml # shared settings, data cache, rep. periods, TEMOA
│       └── sectors/           # one TOML per module
│           ├── agriculture.toml
│           ├── commercial.toml
│           ├── electricity.toml
│           ├── industry.toml
│           └── residential.toml
└── .cache/                    # the data cache, if you installed it in the project
```

The pipeline adds two folders when it runs: `canoe-pwd/all-high/` (the databases) and
`temoa-outputs/all-high/` (TEMOA's logs). Both are in `.gitignore`, along with `.cache/`:
everything in them can be rebuilt from the configuration.

`pyproject.toml` pins the canoe the project was created with, so the project keeps
building the same database until you choose to [update canoe](#updating-canoe).

## 2. The data cache

The compiler doesn't download data while it runs. It reads a local copy of the CANOE
data lake, the **cache**:

```
.cache/
├── silver/
│   ├── 2026-08-10/      # a snapshot of the data lake
│   └── ...              # newer snapshots, added next to the old ones
└── renewables/          # wind and solar resource bins of the electricity module
```

The pipeline reads one snapshot, `cache_date` in `config/all-high/full-pipeline.toml`:

```toml
[compiler.base.data_cache_config]
cache_dir = "../../.cache"
cache_date = "2026-08-10"
```

The cache is **immutable**: installing only adds files that aren't there yet and never
overwrites one. A newer download adds its snapshot next to the old ones, so a project
reading `2026-08-10` gives the same results however many times the cache is updated. It
also means one cache can serve all your projects.

If you skipped the download in `canoe init`, or want a cache shared by several projects:

```bash
uv run canoe cache install .cache            # inside the project
uv run canoe cache install ~/canoe-cache     # or anywhere else
uv run canoe cache status ~/canoe-cache      # what a cache folder holds
```

To use a cache somewhere else, set `cache_dir` to its folder (an absolute path, or a
path relative to the TOML's folder). If a run can't find its snapshot, it stops before
building anything:

```
The data cache at .cache lacks the 2026-08-10 snapshot and the renewables. Install it with: canoe cache install .cache
```

## 3. Install the project

```bash
cd project-hydrogen
uv sync
```

`uv sync` creates `.venv/` with Python 3.12, canoe and the solver interfaces. From now on,
`uv run` runs commands in that environment. Check that the configuration is valid and
the cache is in place:

```bash
uv run canoe check config/all-high/full-pipeline.toml
```

```
config/all-high/full-pipeline.toml: valid
```

## 4. Run the pipeline

```bash
uv run main.py
```

`main.py` runs the four steps of the pipeline in order. It's yours to change: open it
and follow along.

```python
def main() -> None:
    config = load_pipeline_config(CONFIG)

    # 1. Compile
    run_compiler(config.compiler)
    db_path = config.db_path

    # 2. Your edits
    edit_database(db_path)

    # 3. Representative periods
    reduced = build_representative_periods(
        db_path, config.working_directory, config.representative_periods_config
    )
    ...

    # 4. Temoa
    run_temoa(db_path, temoa_config)
```

### Step 1: Compile

The compiler builds the database from scratch, in `canoe-pwd/all-high/canoe.sqlite`:

1. An empty database with the regions, periods and time slices of `[compiler.base]`.
2. The **end-use sectors** (`[compiler.sectors]`: agriculture, commercial, industry,
   residential), each adding its demands and the technologies that can serve them.
3. The **electricity** module, supplying the electricity the sectors consume, with the
   generators, storage and trade behind it.
4. The **fuel** module, supplying the other fuels the sectors and electricity consume:
   imports, distribution and prices.
5. The **emissions** step: CO2, CH4, N2O and their CO2-equivalents.

The database follows the CANOE schema, TEMOA's schema plus metadata: every row says
where it comes from (`data_source`, `notes`, data quality indicators). See [Model
Architecture](what_is_canoe/model_architecture.md) for how the modules fit together.

### Step 2: Your edits

`edit_database` changes the compiled database before it's reduced and solved:

```python
def edit_database(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        # 20% cheaper new solar
        connection.execute(
            "UPDATE cost_invest SET cost = cost * 0.8 WHERE tech LIKE 'E_SOL_PV%'"
        )
        connection.commit()
```

Every run compiles the database again, so edits live in code rather than in the database:
the project stays reproducible from its files. The tables and their columns are those of
the CANOE schema (`cost_invest`, `efficiency`, `demand`, `limit_capacity`, ...); open
`canoe.sqlite` with any SQLite browser to explore them.

### Step 3: Representative periods

TEMOA can't practically optimize 365 days of every year, so this step reduces the
database to a few representative days. The compiled database is left as it is; the
reduced copy is written next to it, as `canoe-pwd/all-high/canoe_16d.sqlite`.

```toml
[representative_periods_config.clustering]
kind = "tsam_collection"
collection = "weather2018-hierarchical-pca6"
n_periods = 16           # representative days, forced days included
forced_days = ["D041"]   # a day that is always kept (the 10th of February)
```

The days come from a clustering packaged with canoe, made from 2018 weather data. Change
`n_periods` to trade accuracy for solve time.

### Step 4: TEMOA

TEMOA builds the optimization model from the reduced database and solves it:

```toml
[temoa_config]
solver = "gurobi"
scenario_mode = "perfect_foresight"   # "build_only" builds the model without solving it
output_path = "../../temoa-outputs/all-high"
```

The results are written into the reduced database (`canoe_16d.sqlite`), in the
`output_*` tables. TEMOA's log goes to a time-stamped folder in
`temoa-outputs/all-high/`.

## 5. Look at the results

The results are tables of the reduced database:

| Table | What it holds |
|---|---|
| `output_objective` | The total system cost |
| `output_built_capacity` | New capacity built, by region, technology and vintage |
| `output_net_capacity` | Capacity available in each period |
| `output_flow_out`, `output_flow_in` | Energy produced and consumed by each technology |
| `output_emission` | Emissions by technology and period |
| `output_cost` | Costs by technology and period |

For example, with Python and pandas:

```python
import sqlite3
import pandas as pd

with sqlite3.connect("canoe-pwd/all-high/canoe_16d.sqlite") as connection:
    built = pd.read_sql(
        "SELECT region, tech, vintage, capacity FROM output_built_capacity", connection
    )
```

## 6. Change the configuration

The pipeline TOML, `config/all-high/full-pipeline.toml`, has one section per part of the
pipeline:

| Section | What it configures |
|---|---|
| `[compiler.base]` | Settings shared by every module: database, periods, provinces, GDP and population projections, currency year |
| `[compiler.base.data_cache_config]` | The data cache and the snapshot it reads |
| `[compiler.sectors]` | The end-use sectors to build, one TOML each in `sectors/` |
| `[compiler.electricity]` | The electricity module (`sectors/electricity.toml`) |
| `[compiler.fuel]` | The fuel module: price sources and how they're combined |
| `[representative_periods_config]` | The representative days |
| `[temoa_config]` | The solver and how TEMOA runs |

Some common changes:

- **Model other provinces**: `provinces = ["QC", "ON"]` in `[compiler.base]`.
- **Change the horizon**: `future_periods` and `period_step`.
- **Leave a sector out**: comment its line in `[compiler.sectors]`.
- **Skip a step**: remove its section; without `[representative_periods_config]`, TEMOA
  runs on the full database, and without `[temoa_config]` the pipeline stops before
  TEMOA.

**Inherited settings.** Each sector TOML takes the shared settings of
`[compiler.base]` (periods, provinces, GDP projection, ...) unless it sets its own: add
`demand_projection_point = "period_start"` to `sectors/industry.toml` to change it for
industry only.

**Paths.** A relative path in a TOML is relative to the folder of that TOML, not to the
folder you run from: in `full-pipeline.toml`, `sectors/commercial.toml` is next to it and
`../../.cache` is the project's `.cache/`.

After changing a TOML, check it:

```bash
uv run canoe check config/all-high/full-pipeline.toml          # valid?
uv run canoe check --show config/all-high/full-pipeline.toml   # every setting, resolved
```

Every setting is documented in the [Configuration Reference](reference/index.md).

## 7. Make your own scenario

A scenario is a folder of configuration files. To make one, copy an existing one:

```bash
cp -r config/all-high config/cheap-solar
```

Then, in `config/cheap-solar/full-pipeline.toml`, change the folders the scenario writes
to, so it doesn't overwrite `all-high`:

```toml
working_directory = "../../canoe-pwd/cheap-solar"
# [compiler.base]
db_output_dir = "../../canoe-pwd/cheap-solar/canoe.sqlite"
# [temoa_config]
output_path = "../../temoa-outputs/cheap-solar"
```

and run it, from `main.py` (point `CONFIG` to `config/cheap-solar/full-pipeline.toml`) or
from the command line:

```bash
uv run canoe run config/cheap-solar/full-pipeline.toml
```

## Running from the command line

`main.py` is the place for your own steps; when you don't need them, the `canoe` command
runs a configuration directly:

| Command | What it does |
|---|---|
| `uv run canoe run CONFIG` | Compile, reduce to representative periods and run TEMOA, as configured (no edits) |
| `uv run canoe compile CONFIG` | Build the database only |
| `uv run canoe check CONFIG` | Validate the TOMLs and check the data cache, without running |
| `uv run canoe cache install [FOLDER]` | Download the data cache into a folder |
| `uv run canoe cache status [FOLDER]` | Show the snapshots a cache folder holds |

`uv run canoe --help` and `uv run canoe <command> --help` describe every option.

## Solvers

The project installs the Python interfaces of its solvers (`canoe[solvers]`), but the
solvers themselves need their own setup:

- **Gurobi** (`solver = "gurobi"`, the default): needs a license for a model of CANOE's
  size. Academic licenses are free at [gurobi.com](https://www.gurobi.com/academia/).
- **HiGHS** (`solver = "appsi_highs"`): open source, installed with canoe, no license.
  Slower on large models, and it doesn't report duals, so also set
  `save_duals = false`.

If TEMOA can't find the solver, the run stops with a link to its installation
instructions.

## Updating canoe

A project keeps the canoe it was created with. To move to a newer one:

```bash
uv lock --upgrade-package canoe
uv sync
uv run canoe check config/all-high/full-pipeline.toml
```

A newer canoe can add or change settings: `canoe check` says which ones the TOMLs need
to change. The files of the project (`main.py`, the TOMLs) are not updated; to see what
a new project looks like, create one in a scratch folder with `canoe init`.

## Troubleshooting

**`The data cache at ... lacks the 2026-08-10 snapshot`**: the cache isn't where
`cache_dir` points, or doesn't have that snapshot. Install it with the command the
message gives, or fix `cache_dir`.

**`Invalid configuration in ...`**: a setting has a wrong value or name; the message
lists each error with its place in the TOML (e.g. `compiler.base.provinces.0`).

**`File not found: ...`**: a TOML names a file that doesn't exist; check the path
relative to that TOML's folder.

**`project-hydrogen is not empty`**: `canoe init` only creates projects in a new or
empty folder.

Still stuck? Open an [issue](https://github.com/CANOE-main/CANOE/issues) (see
[Contributing](contributing.md) for what to include).

---
title: Quickstart
description: Run CANOE end-to-end, from the master database to a solved TEMOA model
---

# Quickstart

This walks through running CANOE from the published master database to a solved TEMOA model, in
four stages: **download the data → filter it → apply representative periods → run TEMOA.**

For the concepts behind each stage, see [Model
Architecture](../what_is_canoe/model_architecture.md).

## Step 1: Get the master database

Download the CANOE 3.1 master database from
[Google Drive](https://drive.google.com/drive/folders/1FIWK6YTJIK5gEhJ4o5742rgYE99fkaQU).

This database contains both the high-resolution module output and the low-resolution CEF
alternative for every sector, across all scenarios and regions (see [Model
Architecture](../what_is_canoe/model_architecture.md#from-sectors-to-a-master-database))

## Step 2: Filter to your case of interest

Use [`canoe_interface`](https://github.com/CANOE-main/canoe_interface) to narrow the master
database down to a specific region, sector, and scenario combination.

**Option A — download the executable (no setup required):**
Go to the [releases page](https://github.com/CANOE-main/canoe_interface/releases) and download the
Windows executable.

**Option B — run from source:**

```bash
git clone https://github.com/CANOE-main/canoe_interface.git
cd canoe_interface
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

In the app:

1. Point it at the master database you downloaded in Step 1.
2. Select the region, sector, and scenario configuration you want — this determines the
   resolution (high-res module output vs. low-res CEF) and scope of the output.
3. Submit to process. The filtered database is written to your chosen output location.

## Step 3: Apply representative periods

The filtered database still has finer temporal resolution than TEMOA can practically optimize
over. [`representative_periods`](https://github.com/CANOE-main/representative_periods) reduces it
to a manageable set of representative time periods via clustering.

```bash
git clone https://github.com/CANOE-main/representative_periods.git
cd representative_periods
conda env create -f environment.yml
conda activate canoe-backend
```

!!! danger "Required: patch the `tsam` library"
    This tool needs a modified `timeseriesaggregation.py` inside your installed `tsam` package —
    it won't work correctly otherwise. Find your `tsam` install path with:

    ```bash
    python -c "import tsam, os; print(os.path.dirname(tsam.__file__))"
    ```

    Then replace that file with the one in the repo root (macOS/Linux, with the conda env active):

    ```bash
    cp ./timeseriesaggregation.py $(python -c "import tsam, os; print(os.path.dirname(tsam.__file__))")/
    ```

Then:

1. Place your filtered database from Step 2 into `input_sqlite/`.
2. Edit `config.yaml` to set your clustering parameters and select which time series columns to use.
3. Run the full workflow:

    ```bash
    python process_all.py
    ```

4. Pick up the result from `output_sqlite/` — this is your TEMOA-ready database.

## Step 4: Run TEMOA

Clone the CANOE fork of TEMOA:

```bash
git clone https://github.com/CANOE-main/temoa.git
cd temoa
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Copy `data_files/my_configs/config_sample.toml` and point it at your database from Step 3, then run:

```bash
python main.py --config data_files/my_configs/config_sample.toml
```

Output lands in a time-stamped folder under `output_files/`, including logs and result tables.

!!! info "Solver required"
    TEMOA needs a solver (e.g. Gurobi, CPLEX, or the free `cbc`) available on your system. Solver
    setup isn't covered in this quickstart yet — see the environment setup page once it's written.

## Next steps

- Read [Model Architecture](../what_is_canoe/model_architecture.md) to understand what each stage
  above actually did.
- See the [Data Guide](../data_guide/index.md) for sector-specific data details.
- Hit an issue? Check [Contributing](contributing.md) for the issue template.

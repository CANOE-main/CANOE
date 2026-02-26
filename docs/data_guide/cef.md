# CEF Data

This page details the extraction and processing of Canada's Energy Futures (CEF) data for use in CANOE. This pipeline is used to convert annual energy demand projections for lower-resolution sectors (which act as "black boxes") into Temoa-compatible databases.

## Data Sources

### Primary Energy Data
- **Canada's Energy Future (CER/CEF)**: The core primary data source. End-use demand data for various sectors (e.g., `end-use-demand.csv`) is sourced from the Canadian Energy Regulator (CER) [Energy Futures Report](https://www.cer-rec.gc.ca/en/data-analysis/canada-energy-future/).

### Auxiliary & Mapping Data
- Custom CSV mapping files (`regions.csv`, `commodities.csv`, `sectors.csv`) are utilized to map CEF-specific variables to CANOE-compatible naming conventions and architectures.

---

## Processing & Assumptions

### 1. Data Ingestion & Filtering
The pipeline reads the CEF demand projections directly from the downloaded CSV files and filters them appropriately according to the configured scenarios (e.g., Global Net-zero) and geographic boundaries.

### 2. Dimension Mapping
CEF regions, energy branches (sectors), and fuels undergo transformation directly into CANOE's internal naming schema. For instance:
- Commercial electricity maps to `C_elc`.
- Residential natural gas maps to `R_ng`.
- Industrial biofuel maps to `I_bio`.
- Transportation gasoline maps to `T_gsl`.

### 3. Load Distribution (Optional)
If configured within the scenario generation, Demand Specific Distributions (DSD) can be applied specifically to electricity demands produced by the CEF projections. This establishes high-resolution regional load profiles for the optimization horizon.

---

## Final Data

The pipeline outputs a Temoa-compatible SQLite database encompassing the processed energy demands:

- `Technology` and `Commodity`: Broad sector representation nodes (e.g., `C_COM`, `R_RES`, `I_IND`, `T_TRP`) and their required resource commodities.
- `Demand`: Processed annual demand values matched securely to corresponding CANOE time periods.
- `Efficiency`: Basic energy conversion links associating the fuel supply distributions to the centralized sectoral demand technologies.

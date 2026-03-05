# Agriculture Sector

This page details the end-to-end data flow for the CANOE Agriculture Sector model, from raw external sources to the structured SQLite tables.

## Data Sources

### Primary Energy Data
- **NRCan Comprehensive Energy Use Database (CEUD)**: Provides the base-year energy demand and input shares for the agriculture sector by province and the Atlantic aggregate.
- **Statistics Canada (Table 25-10-0029-01)**: Provides regional shares used to distribute the Atlantic aggregate values into individual provinces (PEI, NB, NS, NLLAB).

### Auxiliary Data
- **CER Energy Futures (Macro Indicators)**: GDP series for the Global Net-zero scenario, used as scaling factors to project future demands based on economic growth.

---

## Processing & Assumptions

### 1. Base Year Demand and Scaling
The model establishes the base period using data from NRCan. For subsequent model years, agricultural energy demand is scaled linearly according to the CER GDP growth ratios.

### 2. Atlantic Province Allocation
Because NRCan groups the Atlantic provinces (ATL) together, the pipeline uses demographic and economic shares from Statistics Canada to disaggregate the ATL demand into specific values for Prince Edward Island, New Brunswick, Nova Scotia, and Newfoundland and Labrador.

### 3. Share Computation and Balancing
Input shares for various commodities are computed (`LimitTechInputSplitAnnual`). Any missing data points (n.a., X) are treated as remainder-to-100%, and values exceeding 100% are appropriately trimmed to maintain a balanced energy flow. Efficiency is derived sequentially based on these splits.

---

## Final Data

The pipeline generates an SQLite output database containing:

- `Demand` and `ExistingCapacity`: Baseline capacity and scaled energy demand time series.
- `Technology` and `Commodity`: Definition of the agriculture pseudo-technology (`A_AGRI`) and required energy carriers (e.g., `A_ng`, `A_dsl`, `A_gsl`, `A_elc`, `A_prop`).
- `Efficiency` and `LimitTechInputSplitAnnual`: Derived conversion efficiencies and fractional input requirements.
- `CostInvest`: Seeded placeholder cost values for tracking investments.
- `DataSet` & `DataSource`: Specific metadata rows establishing data provenance (e.g., `[A1]` NRCan, `[A2]` CER).

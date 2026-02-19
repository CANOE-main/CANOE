# Fuels Sector

This section provides a technical overview of the data pipeline for the fuel sector, covering how raw data is sourced, normalized, and transformed into the final SQLite database.

## Data Sources

The aggregator draws from a mix of international energy APIs, technical reports, and localized biofuel studies to ensure comprehensive coverage of the fuel commodity landscape.

| Source | Data Category | Key Information |
| :--- | :--- | :--- |
| **EIA API (AEO 2025)** | Fossil Fuels | Natural gas, coal, oil, gasoline, diesel, and jet fuel prices. |
| **NREL ATB** | Alternative/Renewable | Biomass, wood, uranium, and synthetic jet fuel (SPK) price assumptions. |
| **Wolinetz & Harrison (2023)** | Canadian Biofuels | Ethanol and renewable diesel prices, including transportation costs in Ontario. |
| **Local Metrics** | Emissions & Metadata | `direct_comb_emission.csv` and `upstream_emissions_fuels.csv` for intensity factors. |

> [!NOTE]
> EIA data is fetched dynamically and cached locally in `cache/dataframes.pkl` to minimize API calls and ensure consistent results across runs.

---

## Processing & Assumptions

To create a unified dataset across disparate sources, the following transformations and assumptions are applied:

### 1. Normalization & Units
All financial data is normalized to a common model unit: **2020 M$/PJ**.
- **Energy Conversion**: MMBtu values are converted to Petajoules (PJ) using standard higher heating value (HHV) factors.
- **Inflation Adjustment**: GDP deflators are applied to convert prices from various vintage years (e.g., 2022 or 2025) to the **2020 base year**.
- **Currency Adjustment**: USD values are converted to CAD where applicable based on predefined exchange rate factors.

### 2. Price Proxies
Where direct market data is unavailable for specific fuel types, proxies are used based on similar physical properties:
- **Marine Diesel Oil (MDO)**: Assumed to be **0.9x** the price of transport diesel.
- **LNG/CNG**: Proxied to transport natural gas (T_ng).
- **LPG**: Proxied to propane prices (T_prop or R_prop).
- **Coke/Petcoke**: Proxied to industrial coal prices.

### 3. Data Integration
The `aggregator.py` script orchestrates the following:
1. **Schema Initialization**: Creates the SQLite structure defined in `input/schema_3_1.sql`.
2. **Runtime Framing**: Filters EIA data for requested periods and provinces.
3. **Calculated Tables**: Generates `CostVariable` (prices), `Efficiency` (utilization), and `EmissionActivity` (intensities).

---

## Final Data

The pipeline results in a structured SQLite database (`output/CAN_fuel.sqlite`) containing the following core tables used for modeling:

- **CostVariable**: Spatially and temporally explicit fuel prices (Province/Period/Tech).
- **EmissionActivity**: Direct and upstream CO2e intensities per unit of fuel consumed.
- **Efficiency**: Standardized energy output-to-input ratios (typically 1.0 for supply-side imports).
- **Technologies & Commodities**: Dimensional tables defining the scope of the fuel sector.
- **Metadata**: Tracking of the run version, timestamp, and author for data provenance.


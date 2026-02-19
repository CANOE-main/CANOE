# Commercial Sector

This page details the end-to-end data flow for the CANOE Commercial Sector model, from raw external sources through processing and assumptions to the final aggregated dataset.

## Data Sources

The model aggregates data from several primary and auxiliary sources:

### Primary Energy & Technology Data
- **NRCan Comprehensive Energy Use Database (CEUD)**: The core source for historical energy consumption, building stock, and end-use breakdowns in Canada.
- **EIA Annual Energy Outlook (AEO)**: Provides technology-specific assumptions, including capital costs, operation and maintenance costs, and efficiencies for both existing and new commercial equipment.
- **NREL ComStock**: Used for high-resolution end-use load profiles (Demand Specific Distributions - DSDs) across various building types and climate zones.

### Auxiliary & Mapping Data
- **Renewables Ninja**: Provides population-weighted temperature and humidity data for weather normalization.
- **Statistics Canada**: Population projections used for scaling future energy demands.
- **Canada Energy Regulator (CER)**: GDP and other macro indicators for economic projections.
- **US EPA**: GHG emission factors for calculating the carbon intensity of different fuel commodities.

---

## Processing & Assumptions

The aggregation process involves several complex steps to harmonize disparate data sources:

### 1. Aggregation Logic
The model iterates through each model region (provinces) and period (vintages). It calculates the energy balance by combining the building stock intensity (from NRCan) with technology performance characteristics (from AEO).

### 2. Weather Normalization
To ensure temporal consistency, timeseries data is normalized to a specific **Weather Year (2018)**. This involves mapping ComStock load profiles to Canadian regional weather patterns using temperature and humidity correlations.

### 3. Key Assumptions
- **Electrification**: The model assumes a gradual transition of non-electric fuel consumption (e.g., natural gas, oil) to electricity. A default factor (e.g., 62% by 2050) is used to model this linear shift.
- **Currency & Inflation**: All financial data is converted to a base currency (**CAD**) and adjusted for inflation using the GDP deflator or other specific indices (e.g., construction CPI).
- **Technology Stock**: It differentiates between *existing capacity* (inherited stock) and *new capacity* (future additions), each with distinct efficiency and cost trajectories.

---

## Final Data

The output of the aggregation is a comprehensive SQLite database (`commercial.sqlite`) structured for use in the CANOE optimization model.

### Key Output Tables
- `Efficiency`: Maps technologies and vintages to their energy conversion efficiencies.
- `DemandSpecificDistribution`: Contains high-resolution hourly load profiles for different end-uses.
- `Technology` & `Commodity`: Define the available equipment and energy carriers (C_oil, C_ng, C_elc, etc.) in the sector.
- `EmissionActivity`: Tracks the CO2-equivalent emissions associated with fuel consumption.

### Distribution
The final dataset is typically output to SQLite, but can be cloned to **Excel** (`commercial.xlsx`) for manual review and reporting purposes.

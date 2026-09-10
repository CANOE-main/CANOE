# Electricity Sector

This repository aggregates the Canadian electricity sector for the CANOE model. It processes raw data from various national and international sources into a unified, aggregated format suitable for large-scale energy system modeling.

For in-depth details about the electricity sector: [Detailed Electricity](https://canoe-main.github.io/canoe-electricity/)

## Data Sources

The aggregation process draws from several primary databases and datasets:

- **[CODERS](https://cme-emh.ca/en/coders/)**: The Canadian Open-Source Database for Energy Research and Systems-Modelling is the primary source for existing capacity, generator types, and generic technology data.
- **[NREL Annual Technology Baseline (ATB)](https://atb.nrel.gov/)**: Used for cost projections (CAPEX/OPEX), efficiency metrics (heat rates), and future technology parameters. It is particularly used for "new" technology candidates.
- **[IESO Public Data](http://reports.ieso.ca/public/)**: Provides hourly production and demand data for Ontario, which is used to derive representative capacity factors and demand profiles.
- **[Renewables.ninja](https://www.renewables.ninja/)**: Used for high-resolution variable renewable energy (VRE) capacity factors (wind and solar).
- **Internal Configuration**:
    - `params.yaml`: Main configuration for model years, currencies, and aggregation switches.
    - `generator_technologies.csv`: Defines the mapping between CODERS/ATB techs and the internal model tech codes.
    - `atb_master_tables.csv`: Maps specific spreadsheet locations in the NREL ATB workbook.

## Processing & Assumptions

The aggregation script (`electricity_sector.py`) follows a structured pipeline:

1. **Pre-processing**: Loads configuration and cleans base parameters.
2. **Temporal & Spatial Aggregation**:
    - **Time**: Converts hourly data into representative days/slices (e.g., peak demand days, average seasonal days).
    - **Regions**: Aggregates data at the provincial level (e.g., AB, BC, ON, QC).
3. **Existing vs. New Capacity**:
    - **Existing**: Aggregated from CODERS snapshots for a specific base year (default 2020). Small capacities below a threshold (0.001 GW) are filtered out.
    - **New**: Technology candidates are generated based on ATB projections, with options for batched capacity limits.
4. **Technology Assumptions**:
    - **VRE Modeling**: Solar and wind are modeled with performance degradation (solar) and specific LCOE/Capacity Factor sorting.
    - **CCS Retrofits**: Optional flags allow for modeling carbon capture and storage retrofits on existing fossil fuel plants.
    - **Interties**: Both boundary (external to model) and endogenous (between provinces) interties are included.
5. **Currency and Inflation**: All costs are converted to a common currency (CAD) and adjusted for inflation using indices like the GDP deflator.

### Wind and Solar capacity factors

Maximum capacities for new wind and solar were derived from a geospatial assessment of developable land in Ontario. The province was divided into grid cells of approximately 25 km, matching the ERA5 reanalysis data (Hersbach et al., 2020) used for hourly wind and solar resources. Within each cell, water, wetlands, built-up areas (Natural Resources Canada, 2022), protected areas (Environment and Climate Change Canada, 2023), and existing wind farms (Natural Resources Canada, 2020) were excluded, with cropland additionally excluded for solar. The remaining area was converted to installable capacity using the land-use intensities of Palmer-Wilson et al. (2019). Cells were then ranked by levelized cost of electricity, including connection to the nearest transmission line (OpenStreetMap contributors, 2024), and grouped into the resource bins used in CANOE. Each bin's capacity limit is the sum of installable capacity across its cells.

- Environment and Climate Change Canada. (2023). Canadian Protected and Conserved Areas Database (CPCAD). [[https://www.canada.ca/en/environment-climate-change/services/national-wildlife-areas/protected-conserved-areas-database.html]]
- Hersbach, H., et al. (2020). The ERA5 global reanalysis. Quarterly Journal of the Royal Meteorological Society, 146(730), 1999–2049. [[https://doi.org/10.1002/qj.3803]]
- Natural Resources Canada. (2020). Canadian Wind Turbine Database. [[https://open.canada.ca/data/en/dataset/79fdad93-9025-49ad-ba16-c26d718cc070]]
- Natural Resources Canada. (2022). 2020 Land Cover of Canada. [[https://open.canada.ca/data/en/dataset/ee1580ab-a23d-4f86-a09b-79763677eb47]]
- OpenStreetMap contributors. (2024). OpenStreetMap. [[https://www.openstreetmap.org]]
- Palmer-Wilson, K., et al. (2019). Impact of land requirements on electricity system decarbonisation pathways. Energy Policy, 129, 193–205. [[https://doi.org/10.1016/j.enpol.2019.01.071]]

## Final Data

The output of the aggregation process consists of:

- **SQLite Database (`electricity.sqlite`)**: A fully structured database containing all aggregated tables (Commodities, Technologies, Costs, Capacity Factors, etc.) according to the `canoe_dataset_schema.sql`.
- **Excel Summary (`electricity.xlsx`)**: A flattened version of the database for easier manual inspection and reporting.
- **Data Cache (`data_cache/`)**: Locally cached versions of pulled source data to allow for offline execution and reproducibility.
- **Provincial Summaries**: Processed grid data including demand profiles and reserve margins for each Canadian province.

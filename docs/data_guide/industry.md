# Industry Sector

This page documents the data lifecycle for the Industry sector in the CANOE database, covering the sources, ETL processing logic, and the resulting data structure.

For in-depth details about the industry sector: [Detailed Industry](https://canoe-main.github.io/canoe-industry/)


## 1. Data Sources

The industry pipeline integrates three primary external datasets to build a comprehensive view of energy demand and technological shares across Canada.

| Source | Dataset | Purpose |
| :--- | :--- | :--- |
| **NRCan** | Comprehensive Energy Use Database (CEUD) | Provides base-year energy demand by industry and fuel type. |
| **CER** | Energy Futures (Macro Indicators 2023) | Used for GDP-based growth scaling of future demand. |
| **StatCan** | Table 25-10-0029-01 | Used to allocate Atlantic aggregate data into specific provinces (PEI, NB, NS, NL). |

> [!NOTE]
> All external data is locally cached in the `cache/` directory to ensure reproducible builds.

## 2. Processing & Assumptions

The ETL pipeline transforms raw sectoral data into a standardized SQLite format using the following logic:

### Base Year & Temporal Scaling
- **Base Year**: Industrial energy demand is anchored to the NRCan CEUD base year (e.g., 2022).
- **GDP Scaling**: Future demand periods (specified in `params.yaml`) are projected by scaling base-year values with GDP growth trajectories from the **CER Global Net-zero** scenario.

### Atlantic Province Allocation
Because NRCan often aggregates Atlantic provinces, a specific split is performed:
1. Load aggregate Atlantic demand from NRCan.
2. Apply provincial shares derived from Statistics Canada Table 25-10-0029-01.
3. Distribute shares across **PEI, NB, NS, and NLLAB**.

### Tech Input Splits (Fuel Shares)
- Fuel shares for industrial technologies are derived from NRCan share tables.
- **Handling Missing Data**: Values marked as `n.a.` or `X` (confidential) are treated as the "remainder" to ensure total shares sum to 100%.
- **Normalization**: If aggregate shares exceed 100% due to source rounding, they are trimmed to fit.

### Efficiency
- All industrial technologies currently assume an `Efficiency = 1.0`, effectively mapping input energy commodities directly to sectoral demand commodities (e.g., `I_ng` $\rightarrow$ `I_d_cement`).

## 3. Final Data Output

The pipeline generates a SQLite database (typically `CAN_industry.sqlite`) containing the following key tables:

- **Demand**: Time-series demand rows per region and industry sub-sector.
- **Technology & Commodity**: Definitions for industrial processes and fuel types.
- **LimitTechInputSplitAnnual**: The calculated fuel mix per technology.
- **Efficiency**: Theoretical energy conversion performance.
- **CostInvest**: Placeholder investment costs for future capacity planning.
- **DataSet / DataSource**: Comprehensive metadata including citations for provenance.


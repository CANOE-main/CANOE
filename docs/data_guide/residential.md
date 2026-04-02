# Residential Sector

For in-depth details about the residential sector: [Detailed Residential](https://canoe-main.github.io/canoe-residential/)

The residential sector model aggregates data from several key industrial and governmental sources:

*   **NRCan Comprehensive Energy Use Database (CEUD):** Primary source for Canadian residential energy consumption, existing stock characteristics, and regional housing data.
*   **EIA Annual Energy Outlook (AEO):** Provides technology-specific assumptions, including capital costs, fixed O&M, and efficiencies for new and future residential technologies.
*   **NREL ResStock:** Utilized for high-resolution hourly energy consumption profiles (load shapes) across various housing archetypes and US states.
*   **US EPA GHG Emission Factors Hub:** Source for greenhouse gas emission factors (CO2, CH4, N2O) associated with various residential fuel types.
*   **Renewables Ninja:** Provides chronological ambient temperature and dew point data used to map US-based ResStock profiles to Canadian regional climates.

## Processing and Assumptions

The model performs several transformation steps to unify these disparate data sources into a cohesive regional database:

### Technology Vintaging
*   **Lifetimes:** Average lifetimes for residential equipment are calculated based on the mean of a **Weibull distribution** using parameters derived from AEO.
*   **Stock Representation:** Existing stock is represented through vintage-specific technologies, allowing for realistic retirement and replacement modeling.

### Currency and Efficiency Conversions
*   **Currency:** Financial data from US sources (EIA AEO) is converted to **CAD** and adjusted for inflation using a GDP deflator or CPI.
*   **Units:** All energy data is standardized to **PetaJoules (PJ)** and costs to **Million Dollars (M$)**. Efficiencies are converted to consistent dimensionless units (PJ\_out / PJ\_in).

### Demand Specific Distributions (DSD)
*   **Weather Mapping:** To adapt US-state-level demand profiles (ResStock) to Canadian provinces, the model correlates hourly energy use with ambient weather conditions.
*   **Mapping Logic:** Hourly profiles are realigned by taking the mean of matched weather hours (temperature and humidity) from Renewables Ninja data between the source US state and target Canadian province.

### Subsector Aggregation
*   The model handles five distinct subsectors independently before final merging: **Space Heating**, **Space Cooling**, **Water Heating**, **Lighting**, and **Appliances**.

## Final Data

The output of the aggregation process is a structured **SQLite database** (`residential.sqlite`) and an optional Excel workbook. Key data structures include:

*   **Commodities:** Definitions for fuel inputs (natural gas, electricity, wood, etc.) and end-use demands (heating, cooling, lighting).
*   **Technologies:** Comprehensive set of existing (NRCan) and future (AEO) equipment with associated efficiency and cost curves.
*   **DemandSpecificDistribution (DSD):** Normalized hourly profiles (8760 format) for each end-use demand and region.
*   **EmissionActivity:** Calculated emission factors per unit of energy output, facilitating integrated climate impact analysis.

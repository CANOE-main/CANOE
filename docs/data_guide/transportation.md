# Transportation Sector


This page provides an overview of the data pipeline for the transportation sector within the CANOE (Canadian Open Energy Model) framework. It outlines how raw data is gathered, processed, and transformed into the final models used for energy system analysis.

For in-depth details about the transportation sector: [Detailed Transportation](https://canoe-main.github.io/canoe-transportation/)

---

## Data Sources

The transportation sector model relies on a combination of regional spreadsheets, synthetic profiles, and national datasets.

### Spreadsheet Databases
The primary input data is stored in the `transportation/spreadsheet_database/` directory. Each spreadsheet contains several critical sheets:

- **Techs & Comms**: Definitions of vehicle technologies and energy commodities.
- **Demand**: Historical and projected energy or transport demand (e.g., VKT - Vehicle Kilometers Traveled).
- **ExCap**: Existing vehicle population by vintage (2000-2020).
- **Efficiency & Costs**: Characterization of vehicle performance and financial parameters.
- **CapFactor**: Constraints on vehicle usage and charging profile requirements.


### Charging Profiles
Synthetic Light-Duty Electric Vehicle (LD EV) charging profiles are sourced from the **RAMP-mobility** framework. These profiles provide hourly distribution of charging demand, which is critical for representing peak grid loads.

### External Dataset References
Key parameters (such as efficiency and cost trajectories) are benchmarked against:

- **NRCan**: Natural Resources Canada (Energy Use Data).
- **GREET**: Greenhouse gases, Regulated Emissions, and Energy use in Technologies model.
- **AEO**: EIA Annual Energy Outlook.
- **NHTS**: National Household Travel Survey.

---

## Processing & Assumptions

The raw data undergoes several transformation steps before it is model-ready.

### The Compiler (`compile_transport.py`)
A custom Python script translates the Excel spreadsheets into a Temoa-compatible SQLite format. Key logic includes:

1.  **Quinquennial Aggregation**:
    - Vehicle vintages from 2000 to 2020 are aggregated into 5-year periods (e.g., 2011-2015 → 2015) to maintain computational efficiency while preserving historical trends.
2.  **Profile Normalization**:
    - RAMP-mobility charging profiles are converted to the local time zone (`America/Toronto`), resampled to hourly resolution, and normalized to ensure total annual energy balance.
3.  **Data Quality Indexing (DQI)**:
    - Each data entry is assigned a quality score based on its data year, reliability, and representativeness.
4.  **Automatic Cleanup**:
    - The script filters out technologies with zero existing capacity or missing efficiency parameters to ensure model stability.
5.  **Emission Harmonization**:
    - Units for CH4 and N2O are converted from ktonnes to tonnes to align with other sectoral databases in CANOE.

---

## Final Data

The output of the processing pipeline is a set of SQLite databases optimized for the **Temoa** framework.

### Database Format
- **Scenario Variants**: Baseline, Low/High Growth, EV Growth, etc.
- **Schema**: Adheres to the `canoe_schema.sql` standard, enabling seamless integration with the broader CANOE ecosystem.
- **Granularity**: The final data includes hourly resolution for charging demands and annual/vintage resolution for vehicle stocks and efficiencies.

> [!NOTE]
> For more details on running the compilation or analysis, refer to the [README.md](https://github.com/CANOE-main/canoe-transportation).

# External Data Sources for CANOE Residential

- NRCan CEUD: Comprehensive Energy Use Database, residential tables, one set per province
  (the Atlantic provinces each have their own)
  Tables 3, 4, 8 and 10 (secondary energy use of lighting, space cooling, space heating and
  water heating), 13 (appliances), 14 (households by building type), 21 (heating system
  stock), 26 (heating system efficiencies), 27 (cooling system stock and efficiencies), 28
  (water heater stock) and 31 (appliance stock): base-year demands, existing capacity,
  efficiencies and capacity factors.
  NOTE: the cache has rounded values, an Atlantic table instead of one per province, and few
  years; the previous module's full-precision tables are in `data/` until it is fixed.

- NRCan Energy Use Data Handbook, table res_00_16 (unit energy consumption of appliances)
  Efficiency of existing clothes dryers and cooking ranges (electricity and natural gas).

- EIA AEO, Residential Demand Module technology menu (rsmess: RSCLASS, RSMEQP)
  Lifetime, efficiency and investment cost of the new technologies, by US census division.
  NOTE: not in the data lake cache; the previous module's file is in `data/`.

- AEO lighting data and IESO 2018 Ontario Residential End-Use Survey
  Efficacy, lamp life and costs of lamps; Ontario stock shares of bulb types.
  NOTE: hand-entered files of the previous module, in `data/`.

- Statistics Canada Tables 17-10-0009-01 and 17-10-0057-01 (population estimates and
  projections, scenario M1)
  Project the residential demands (`demand_driver = "population"`).
  NOTE: not in the data lake cache; extracts in `data/`.

- Statistics Canada Table 38-10-0048-01 (use of energy-saving lights)
  Lighting stock of each province relative to Ontario.
  NOTE: not in the data lake cache; the previous module's file is in `data/`.

- CER GDP projections (Canada's Energy Future 2023 macro indicators)
  Project the residential demands with `demand_driver = "gdp"`.

- NREL ResStock (amy2018, release 2, upgrade 16), by US state and housing type
  Hourly profiles of each end use (demand-specific distribution).

- Renewables Ninja weather (temperature and humidity, 2018), as US-to-Canada weather maps
  Map the space heating and cooling profiles to Canadian weather.

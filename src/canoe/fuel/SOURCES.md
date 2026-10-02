# External Data Sources for CANOE Fuel

- EIA Annual Energy Outlook 2025, Table 3 "Energy Prices by Sector and Source"
  (reference case, US average, real 2024 USD/MMBtu)
  Delivered prices of the fossil fuels and hydrogen by sector, projected to 2050.
  Used for the import and distribution costs of most fuels (see
  `canoe.fuel.prices.DELIVERED_PRICE_SOURCES`).

- NREL Annual Technology Baseline 2024 (electricity), fuel cost and heat rate of the
  default biopower and nuclear plants (2022 USD)
  Prices of bioenergy, wood and uranium, constant over the periods.

- Wolinetz & Harrison (2023), *Biofuels in Canada 2023*, Navius Research; NREL ATB
  Fixed prices of ethanol, renewable diesel (50% biodiesel, 50% HDRD) and synthetic
  jet fuel (2020 CAD/GJ).
  NOTE: not in the data lake cache yet; hard-coded until it is.

- Exchange rates and Canadian inflation (GDP deflator) by year
  Convert the prices to CAD of the model currency year.
  NOTE: not in the data lake cache yet; read from `canoe/common/data`.

- Combustion emission factors by sector and fuel: Government of Canada emission
  factors and reference values (ECCC), Nova Scotia QRV standards, Argonne GREET
  CO2, CH4 and N2O of burning each fuel, on the distribution technologies.
  NOTE: not in the data lake cache yet; read from `canoe/fuel/data` (the previous
  module's file) until it is.

- Upstream emission factors by fuel: ECCC Fuel Life Cycle Assessment model (2024),
  Argonne GREET
  CO2 of producing and delivering each fuel, on the import technologies.
  NOTE: not in the data lake cache yet; read from `canoe/fuel/data` (the previous
  module's file) until it is.

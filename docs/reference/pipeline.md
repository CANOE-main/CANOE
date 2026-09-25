# Pipeline and shared settings

Settings under `[compiler.base]` of the pipeline TOML, shared by every sector.

## Base configuration

::: canoe.initializer.CANOEBaseConfig
    options:
      show_source: false
      filters: ["!^_", "!^validate_from_toml$", "!^expand_path$"]

## Data cache

`[compiler.base.data_cache_config]`

::: canoe.common.cache_connector.config.GoldConnectorConfig
    options:
      show_source: false

## GDP projections

The GDP projections that scale the demands of every sector.

::: canoe.common.gdp.CERScenario
    options:
      show_source: false

::: canoe.common.gdp.GDPProjectionPoint
    options:
      show_source: false

## Emissions

`[compiler.base.emissions]`

::: canoe.emissions.config.EmissionsConfig
    options:
      show_source: false

::: canoe.common.emissions.GlobalWarmingPotential
    options:
      show_source: false
      filters: ["!^_", "!^factors$"]

## Provinces and fuels

::: canoe.common.provinces.CANOEProvince
    options:
      show_source: false
      filters: ["!^_", "!^short$", "!^is_atlantic$", "!^get_nrcan_code$"]

::: canoe.common.fuels.CANOEFuel
    options:
      show_source: false
      filters: ["!^_", "!^get_desc_name$", "!^get_price_fuel$", "!^from_str$"]

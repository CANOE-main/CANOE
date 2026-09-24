# Commercial

The commercial sector models space heating, space cooling and the rest of commercial
energy use (`other`), each as an end-use demand projected with GDP growth and served
by existing and new technologies. See the
[commercial data guide](../data_guide/commercial.md) for the data.

## Default configuration

```toml title="configuration/commercial-default.toml"
--8<-- "configuration/commercial-default.toml"
```

## Settings

::: canoe.commercial.config.CANOECommercialConfig
    options:
      show_source: false
      filters: ["!^_", "!^run$", "!^get_dataset_code$", "!^emissions_deprecated$"]

## End uses

`[end_uses."<end use name>"]`: an end use runs if and only if its table is present.

::: canoe.commercial.config.EndUsesConfig
    options:
      show_source: false
      filters: ["!^_", "!^get$", "!^enabled$", "!^weather_mapping$", "!^space_conditioning$", "!^new_technologies$"]

::: canoe.commercial.config.SpaceConditioningEndUseConfig
    options:
      show_source: false

::: canoe.commercial.technology_catalog.NewTechnology
    options:
      show_source: false

::: canoe.commercial.config.OtherEndUseConfig
    options:
      show_source: false

::: canoe.canoe_objects.fuel_serving_tech.FuelGrouping
    options:
      show_source: false

::: canoe.commercial.config.ElectrificationConfig
    options:
      show_source: false

## Data sources

::: canoe.commercial.config.CEUDConfig
    options:
      show_source: false

::: canoe.commercial.config.ComstockConfig
    options:
      show_source: false

::: canoe.commercial.config.AEOConfig
    options:
      show_source: false

## Time slices

`dsd_time_slices`: the time slices of the demand-specific distribution.

::: canoe.common.time_slices.AllTimeSlices
    options:
      show_source: false
      filters: ["!^_", "!^as_list$"]

::: canoe.common.time_slices.SpecificTimeSlices
    options:
      show_source: false
      filters: ["!^_", "!^as_list$"]

# Agriculture

The agriculture sector is a single technology (`A_AGRI`) with unlimited capacity
that turns the agriculture fuels into the agriculture energy demand (`A_D_AGRI`)
with efficiency 1. The demand is the NRCan CEUD total agriculture energy use of the
data year, projected with GDP growth; the fuel mix is fixed by annual input splits.
See the [agriculture data guide](../data_guide/agriculture.md) for the data.

## Default configuration

```toml title="configuration/agriculture-default.toml"
--8<-- "configuration/agriculture-default.toml"
```

## Settings

::: canoe.agriculture.config.CANOEAgricultureConfig
    options:
      show_source: false
      filters: ["!^_", "!^run$", "!^get_dataset_code$"]

::: canoe.agriculture.input_splits.InputSplitStrategy
    options:
      show_source: false
      filters: ["!^_", "!^uses_remainder_fuel$"]

::: canoe.agriculture.config.SUPPORTED_FUELS
    options:
      show_source: false

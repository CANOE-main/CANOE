# Configuration reference

A CANOE run is described by TOML files, validated into the configuration models
documented in this section. This reference is generated from the code, so it always
matches what the pipeline accepts.

## How the files fit together

The pipeline TOML (e.g. `configuration/full-pipeline.toml`) has two parts:

- `[compiler.base]`: settings shared by the whole model (database, periods,
  provinces, data cache, GDP projections, emissions), see
  [Pipeline and shared settings](pipeline.md).
- `[compiler.sectors]`: one entry per sector to build, pointing to that sector's own
  TOML file. Leave a sector out (or comment it) to skip it.

```toml
[compiler.sectors]
commercial = "commercial-default.toml"
agriculture = "agriculture-default.toml"
```

## Paths in configuration files

A relative path in a TOML is relative to the folder of that TOML, not to the folder
the pipeline runs from: above, `commercial-default.toml` sits next to the pipeline
TOML, and a path inside `commercial-default.toml` is relative to its own folder. The
pipeline's working directory (`working_directory`) and Temoa's outputs
(`output_path`), when left out, go to the folder the pipeline runs from.

Each sector TOML starts with `module_name`, which selects the sector's configuration
model:

- [Commercial](commercial.md): `module_name = "commercial"`
- [Agriculture](agriculture.md): `module_name = "agriculture"`

## Inherited settings

Sector settings marked as *inherited* take their value from `[compiler.base]`
unless the sector TOML sets them, so a sector can override a shared setting (e.g.
`data_version` or `demand_projection_point`) without changing the others. Leaving them
out, or setting them to `"inherited"`, uses the base value.

## Names in configuration files

- Provinces take their short code (`"ON"`, `"NLLAB"`, ...) or full name, see
  `CANOEProvince`.
- Fuels take their code (`"ELC"`, `"NG"`, `"DSL"`, ...), see `CANOEFuel`.
- Options with a fixed set of values (strategies, scenarios, ...) take the values
  listed in their enum.

"""
Objects that build CANOE data into the Temoa database.

Each entity gathers the values of one model object as labeled arrays (see
`labeled_array` and `array_types`), checks them, and writes the corresponding schema
rows in `build(db_conn)`:

- `technology.TechnologyEntity`: one technology with any number of inputs
  (efficiency, lifetime, existing capacity, costs, input splits, ...)
- `fuel_serving_tech.FuelServingTechnologyEntity`: the technologies that serve a
  demand from a set of fuels, one per fuel or a single shared one
- `demand.DemandEntity`: a demand commodity, its projection and its time profile

Values are stored with their metadata (notes, data source, data quality, units) as
`parameter.Parameter`; `parameter.RowOptions` decides how that metadata is spread over
the rows. Entities never commit: the caller owns the connection and the transaction.
"""

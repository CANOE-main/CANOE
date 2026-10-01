# External Data Sources for CANOE Industry

- NRCan CEUD: Comprehensive Energy Use Database, industry tables (AB, BC, MB, SK, ON, QC and Atlantic)
  Tables 3-12, one per industry: its total energy use for the base-year demand of the
  subsector and its energy use by energy source for the fuel mix (input splits).
  Table 2 (energy use by industry) holds the same totals and is not read.

- CER GDP projections (Canada's Energy Future 2023 macro indicators)
  Used to project the subsector energy demands.

- Statistics Canada Table 25-10-0029-01, industry rows
  Used to split the Atlantic tables of the CEUD among PEI, NS, NB and NLLAB, by subsector.
  NOTE: not in the data lake cache yet; the shares are hard-coded until it is.

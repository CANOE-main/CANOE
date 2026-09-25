# External Data Sources for CANOE Agriculture

- NRCan CEUD: Comprehensive Energy Use Database, agriculture tables (AB, BC, MB, SK, ON, QC and Atlantic)
  Total energy use and energy use by fuel, used for the base-year demand and the fuel mix (input splits).

- CER GDP projections (Canada's Energy Future 2023 macro indicators)
  Used to project the agriculture energy demand.

- Statistics Canada Table 25-10-0029-01, "Agriculture, fishing, hunting and trapping"
  Used to split the Atlantic aggregate of the CEUD among PEI, NS, NB and NLLAB.
  NOTE: not in the data lake cache yet; the shares are hard-coded until it is.

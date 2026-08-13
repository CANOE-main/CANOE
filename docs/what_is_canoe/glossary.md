---
title: Glossary
description: Plain-language definitions of capacity-expansion and TEMOA terms used throughout the CANOE docs
---

# Glossary

Plain-language definitions for terms used throughout these docs.

**CEF (Canada's Energy Future)**
: The source of the low-resolution alternative demand projections stored alongside each sector's
  high-resolution module output in the [master database](#master-database). See [Model
  Architecture](model_architecture.md#from-sectors-to-a-master-database).

**Commodity**
: In TEMOA's network model, anything that flows between technologies — a fuel, a form of energy
  (like electricity), or a demand. Technologies consume and produce commodities.

**Cost-optimal**
: The solution TEMOA searches for: the lowest total-cost way of building and operating the modeled
  energy system while satisfying demand and any constraints in place.

**Filtering interface**
: The tool that narrows the [master database](#master-database) down to a specific case of interest —
  a region, a scenario, and which resolution track (high-res or low-res) to use per sector. See [Model
  Architecture](model_architecture.md#filtering-and-representative-periods).

**High resolution / Low resolution**
: The two parallel versions of each sector's demand data stored in the master database: high
  resolution is the sector modules' own bottom-up output; low resolution is the coarser, top-down
  CEF-based alternative. See [Model
  Architecture](model_architecture.md#from-sectors-to-a-master-database).

**Linker module**
: A module — Fuel or Electricity in CANOE — that doesn't represent its own end-use demand, but
  instead ties the sector demand models to energy prices, imports, and distribution. See [Model
  Architecture](model_architecture.md#linker-modules).

**Master database**
: The single SQLite database, following the TEMOA/CANOE schema, that all sector and linker
  modules write into — containing both high- and low-resolution tracks, before any filtering or
  temporal reduction. See [Model
  Architecture](model_architecture.md#from-sectors-to-a-master-database).

**Network**
: TEMOA's representation of an energy system: technologies and commodities connected together,
  evolving across time periods.

**Region**
: The geographic unit CANOE models at (see [Design Assumptions](design_assumptions.md#regions)
  for specifics once documented).

**Representative periods**
: The step that reduces a dataset's fine-grained temporal resolution down to a manageable set of
  representative time periods that TEMOA can practically optimize over. See [Model
  Architecture](model_architecture.md#filtering-and-representative-periods).

**Scenario**
: A distinct set of assumptions (e.g., a policy variant or regional variant) that CANOE's master
  database can represent alongside others.
  !!! note "Needs confirmation"
      This definition is inferred, not confirmed against team usage — flag if "scenario" means
      something more specific in practice (e.g., strictly policy variants vs. any assumption change).

**Schema (schema version)**
: The specific table names, column names, and data types that a TEMOA-based database must follow.
  CANOE's release tags track which schema version they're compatible with. See [CANOE vs.
  TEMOA](canoe_vs_temoa.md#how-theyre-versioned-together).

**Sector**
: One of CANOE's six demand-modeling areas: Electricity, Transportation, Industry, Residential,
  Commercial, and Fuels.

**TEMOA**
: Tools for Energy Model Optimization and Analysis — the open-source, Canada-agnostic
  optimization framework CANOE is built on. See [CANOE vs. TEMOA](canoe_vs_temoa.md).

**Technology**
: In TEMOA's network model, anything that converts one commodity into another — a power plant, a
  vehicle, a heating system — with associated costs, capacity, and lifetime.

[:octicons-arrow-left-24: Back to What is CANOE](index.md)

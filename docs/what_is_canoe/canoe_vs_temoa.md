---
title: CANOE vs. TEMOA
description: How CANOE and TEMOA relate to each other
---

# CANOE vs. TEMOA

CANOE and TEMOA are two separate projects.

## What TEMOA provides

[TEMOA](https://temoacloud.com/) (Tools for Energy Model Optimization and Analysis) is an
open-source framework for modeling multi-sector energy systems. It's not specific to Canada, or to
CANOE, it's used by other energy models worldwide.

TEMOA treats an energy system as a **network**: technologies that consume and produce commodities
(fuels, electricity, demands), connected together, evolving over a set of future time periods. Given that
network, TEMOA finds the **cost-optimal** way to operate it: which technologies to build, retire, and
run in each period to satisfy demand at the lowest total cost, subject to whatever constraints are
defined (emissions limits, resource availability, technology lifetimes, and so on).

TEMOA provides:

- Connections to the optimization engine and solver interface through `pyomo`
- The underlying database schema (table names, column names, data types) that any TEMOA-based
  model's input and output must follow
- The general modeling abstractions (technologies, commodities, time periods, regions) that a
  specific model (like CANOE) populates with real data

## What CANOE adds

CANOE is **an instance of TEMOA**: it doesn't change how TEMOA optimizes anything. What CANOE
contributes is the data.

??? Tip "Contributions of the CANOE team to TEMOA"
    While the two projects are separate, the CANOE team contributes to TEMOA core tools repository often.

Specifically, CANOE is the code and pipeline that:

- Aggregates open-source Canadian data across the electricity, agriculture, transportation, industry, residential,
  commercial, and fuels sectors
- Structures that data into an expanded TEMOA schema
- Provides tools for researchers to experiment with different scenarios and parameterizations

## How they're versioned together

Because CANOE's output has to match whatever schema TEMOA expects as input, the two are versioned
in step with each other. CANOE's own release tags track a **schema version**, so it's always clear which
version of CANOE is compatible with which version of the TEMOA schema — this matters most when
either project changes its table structure, since a mismatch there is a common source of run failures.

## Where to go next

<div class="grid cards" markdown>

-   :material-sitemap:{ .lg .middle } **Model Architecture**

    ---

    How CANOE's sectors, linker modules, and database schema fit together.

    [:octicons-arrow-right-24: Read more](model_architecture.md)


-   :material-book-alphabet:{ .lg .middle } **Glossary**

    ---

    Plain-language definitions of capacity-expansion and TEMOA terms.

    [:octicons-arrow-right-24: Read more](glossary.md)

</div>

[:octicons-arrow-left-24: Back to What is CANOE](index.md)

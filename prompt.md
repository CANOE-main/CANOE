I dug into the actual code — not just fuels but also `../canoe-commercial`, since that's the concrete downstream example. Here's what I found and how it bears on your proposal.

## What's actually happening today

`canoe_fuel/techcom.py:27-169` does three things from one input file (`input/fuel_list.csv`), keyed off rows like `C_oil,oil,oil,oil,...`:
1. Writes the sector's own demand commodity (`C_oil`) — not just fuel's own `F_oil`.
2. Derives the distribution tech name (`F_C_OIL`) by string convention (`techcom.py:110-114`).
3. Later, `costvariable.py` prices `F_C_OIL` and `emissionactivity.py` tags its emissions.

Meanwhile `canoe-commercial` (`input_files/fuel_commodities.csv`) hand-types `oil,C_oil,heating oil in the commercial sector,PJ,...` — the same commodity name, by hand, in a second repo, and `techcom.py` there writes it again (`INSERT OR IGNORE` saves you from a collision, not from drift). Worse, `electricity_patch.py` in commercial *independently reimplements* the `E_C_ELC` bridge-tech naming convention that `canoe_fuel/techcom.py` already generates generically — the same knowledge encoded twice, by two authors, with no shared source of truth. This is your exact complaint, and it's already visible as duplicated, hand-synced code, not a hypothetical.

Your own `develpment_docs/DECISIONS.md` even flags this as an open question ("Cross-sector fuel commodities... Revisit when designing cross-sector commodity balances... some `F_`-prefixed commodities may become the canonical shared representation that sector-specific distribution technologies consume directly"). So the direction you're proposing is the resolution to a question the team already wrote down and deferred. **I think it's the right direction.**

## The wrinkle you already anticipated is real, and it's load-bearing

Look at `costvariable.py:262-329`. For every upstream `F_<fuel>`, it groups all sectors' distribution techs sharing that fuel, takes the **minimum delivered cost across all of them** as the import/supply cost, and every other sector's distribution cost is `their_cost - that_minimum`. So commercial's `F_C_OIL` price is not computable until you know residential's, industrial's, etc. delivered oil costs too. On top of that, `_calc_cost` (`costvariable.py:49-125`) hardcodes direct cross-sector proxying — residential oil price literally is commercial's oil price (`r_oil → C_oil`), hydrogen for commercial/residential prices off industrial's hydrogen (`c_h2/r_h2 → I_h2`), etc.

This means a naive "sector asks, fuel answers immediately" interface would break on day one, but it *validates* your "consolidate" instinct — not as a nice-to-have, but as the only way this can work: **all sectors must register their requests before any sector's price can be resolved.**

## Where I need your call

That two-phase requirement (register-all → then-consolidate) forces a structural decision that's currently ambiguous in "define a linker interface": every `canoe-*` module today is a fully separate repo/CLI invocation that opens the same SQLite DB independently — there's no shared Python process for a function-call interface to live in. So "commercial calls fuel_distribution.request(...)" can't be a literal in-process call unless you also introduce a shared runtime that imports all sector packages together — a much bigger change than the fuels module alone.

The user answered: "How should a sector module actually "call" the fuel-distribution interface, given each canoe-* module today runs as an independent CLI process against a shared SQLite DB?"="I'm refactoring all the modules into a single repo, starting with the commercial one, into the CANOE sibling folder. I will have significant orchestration including caching and shared/inhereted configuration (like the periods). However, each module still "runs" on its own. I would move as much as I could to the modules themselves and then accumulate references to all the calls to fuel-related things that resolve at the end.", "Given prices can't be resolved until all sectors have registered, what should a sector module get back immediately vs. later?"="Names now, prices later is what I would like to do. Is it only prices that need to be deferred?". Read the answers carefully — they may request clarification, changes, or that you not proceed — and follow what they actually say.

Good question — let me verify that against the actual table-by-table dependencies rather than assume.

Confirmed by checking the actual emission CSVs — `direct_comb_emission.csv` is keyed by exact sector-prefixed commodity (`I_ng`, `E_ng`, `A_ng`, `R_ng` each have their own row, with genuinely different values per sector — e.g. N2O factor differs slightly), and `upstream_emissions_fuels.csv` is keyed by `F_<fuel>` only. Both are static reference tables, not derived from what other sectors registered.

**So: yes, price is the only thing that needs deferral.** Table by table:

| Table | Needs consolidate? | Why |
|---|---|---|
| `Commodity` (`C_oil`, `F_oil`) | No | Pure naming convention from `(sector, fuel)` |
| `Technology` (`F_C_OIL`) | No | Pure naming convention |
| `Efficiency` / `LifetimeTech` | No | Fixed values (`efficiency=1.0`, `lifetime=5`), keyed only to the tech's own name |
| `EmissionActivity` | No | Looked up from static CSVs keyed by the tech's own sector+fuel — verified above, no cross-sector read |
| `CostVariable` | **Yes** | The only one with real cross-sector coupling |

One subtlety worth flagging before you lock the design: `costvariable.py:74-121` (`_calc_cost`) isn't just "wait until everyone's registered" — it hardcodes a fixed proxy graph between *specific* sector-fuel pairs: `r_oil` always prices off `C_oil`, `c_h2`/`r_h2` always price off `I_h2`, `e_coal` off `I_coal`, `a_dsl` off `T_dsl`, etc. That's a real dependency, not just "cheapest wins" — if residential registers oil but commercial never does, there's no `C_oil` delivered cost to proxy off of, and today's code would silently fall through to "No base price... Returning 0" (`costvariable.py:41-46`). In the new design, `consolidate()` needs an explicit answer for "the proxy source sector-fuel was never registered" — either error loudly, or fall back to a direct EIA quote for the proxying sector instead of the reference sector. That's a modeling decision, not just plumbing, so worth deciding deliberately rather than inheriting the silent-zero behavior.

Given your answer on mechanism (in-process, one repo, modules still run individually but you accumulate calls), the shape I'd recommend:

- `fuel_distribution.request(sector, fuel_key, ...)` — called from within each sector module's own run. Writes `Commodity`/`Technology`/`Efficiency`/`LifetimeTech`/`EmissionActivity` immediately (idempotent, `INSERT OR IGNORE`, safe to call more than once for the same pair), returns the deterministic commodity/tech names synchronously so the sector module can wire its own rows against them right away.
- Internally, it also appends `(sector, fuel_key)` to an accumulator (module-level state or a small object the orchestrator holds).
- `fuel_distribution.consolidate()` — called once by the orchestrator after every sector module has run. Reads the accumulated set, does the min-cost split + proxy resolution, writes `CostVariable`.

This keeps the naming-convention logic and the "which fuels does commercial get" decision where you wanted them (in the sector module), while keeping the genuinely cross-sector pricing math centralized and deferred — matching what the current code actually requires, not just what would be convenient.

One more decision I'd flag but not block on: today the "cheapest sector wins the base import price" is implicit and can shift silently if a totally unrelated sector's price assumption changes. Worth deciding now whether to keep that as-is or make it an explicit, documented rule — but that's a modeling call for you, not something the architecture needs resolved to move forward.


Understood — I'll present it as a sketch here, not commit it to disk. I'll drop the mechanical stubs and keep just the shape.

## `naming.py` — pure, no dependency on other requests

```python
def commodity_name(sector: CANOESector, fuel: str) -> str:
    """('Commercial', 'oil') -> 'C_oil' — the sector's own demand commodity."""

def import_commodity_name(fuel: str) -> str:
    """'oil' -> 'F_oil' — shared upstream supply commodity, one per fuel."""

def distribution_tech_name(sector: CANOESector, fuel: str) -> str:
    """('Commercial', 'oil') -> 'F_C_OIL'."""

def import_tech_name(fuel: str) -> str:
    """'oil' -> 'F_IMP_OIL' — shared import tech."""
```

## `pricing.py` — the two alternative families, same discriminated-union shape as `TimeSliceSetVariant`

```python
class PriceDataAccess(Protocol):
    def get_data_from_X(self, sector: CANOESector, fuel: str, period: int) -> float: ...


# 1. Per (sector, fuel): where does its raw delivered cost come from?
class PriceSourceVariant(BaseModel, ABC):
    @abstractmethod
    def resolve(self, data: PriceDataAccess, sector: CANOESector, fuel: str, period: int) -> float: ...

class DirectQuote(PriceSourceVariant):
    kind: Literal["direct"] = "direct"
    # own series, no substitution — the default

class ProxyQuote(PriceSourceVariant):
    kind: Literal["proxy"] = "proxy"
    proxy_sector: CANOESector
    proxy_fuel: str
    # borrows another pair's raw quote as-is (r_oil -> C_oil today)

class ScaledProxyQuote(PriceSourceVariant):
    kind: Literal["scaled_proxy"] = "scaled_proxy"
    proxy_sector: CANOESector
    proxy_fuel: str
    multiplier: float
    # MDO = 0.9x T_dsl today

class FixedPrice(PriceSourceVariant):
    kind: Literal["fixed"] = "fixed"
    value: float
    # bio / uranium / ethanol / rdsl / spk today

PriceSource = Annotated[DirectQuote | ProxyQuote | ScaledProxyQuote | FixedPrice, Field(discriminator="kind")]


# 2. Given every registered sector's delivered cost for a shared fuel,
#    how do you split it into import floor + distribution markup?
class FuelSupplyPolicyVariant(BaseModel, ABC):
    @abstractmethod
    def resolve_floor(self, delivered: dict[CANOESector, float]) -> tuple[float, CANOESector | None]: ...

class CheapestRegisteredWins(FuelSupplyPolicyVariant):
    kind: Literal["cheapest_registered"] = "cheapest_registered"
    # today's behavior — min() across whoever's registered

class FixedReferenceSector(FuelSupplyPolicyVariant):
    kind: Literal["fixed_reference"] = "fixed_reference"
    reference_sector: CANOESector
    # makes "who sets wholesale" explicit instead of implicit-cheapest

class ExternalWholesaleSeries(FuelSupplyPolicyVariant):
    kind: Literal["external_series"] = "external_series"
    series_key: str
    # for fuels where a real wholesale quote exists, skip inference entirely

FuelSupplyPolicy = Annotated[
    CheapestRegisteredWins | FixedReferenceSector | ExternalWholesaleSeries,
    Field(discriminator="kind"),
]


# Per-fuel config, TOML-loadable — a fuel not listed gets all defaults
# (direct quote everywhere, cheapest-registered-wins), so today's behavior
# is the fallback and every override is opt-in.
class FuelPricingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supply_policy: FuelSupplyPolicy = Field(default_factory=CheapestRegisteredWins)
    price_source_overrides: dict[CANOESector, PriceSource] = Field(default_factory=dict)

    def price_source_for(self, sector: CANOESector) -> PriceSourceVariant:
        return self.price_source_overrides.get(sector, DirectQuote())

class FuelDistributionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: dict[str, FuelPricingRule] = Field(default_factory=dict)

    def rule_for(self, fuel: str) -> FuelPricingRule:
        return self.rules.get(fuel, FuelPricingRule())
```

TOML would read like:

```toml
[fuel_distribution.rules.h2.price_source_overrides.COM]
kind = "proxy"
proxy_sector = "IND"
proxy_fuel = "h2"

[fuel_distribution.rules.mdo.price_source_overrides.TRP]
kind = "scaled_proxy"
proxy_sector = "TRP"
proxy_fuel = "dsl"
multiplier = 0.9
```

## `registry.py` — the two-phase linker, shape only

```python
class FuelDistributionHandle(BaseModel):
    commodity: str
    tech: str
    import_commodity: str
    import_tech: str

class FuelDistribution:
    def __init__(self, base: CANOEBaseConfig, pricing: FuelDistributionConfig, data: PriceDataAccess): ...

    def request(self, sector: CANOESector, fuel: str, db_conn) -> FuelDistributionHandle:
        """Called from inside a sector module's own run(). Returns naming
        synchronously; writes Commodity/Technology/Efficiency/LifetimeTech/
        EmissionActivity immediately (idempotent, self-contained). Records
        (fuel -> {sectors}) for consolidate()."""

    def consolidate(self, db_conn) -> None:
        """Called once by the pipeline after every sector's run() has
        finished. Per fuel, per period: resolve each registered sector's
        delivered cost via its PriceSource, split via the fuel's
        FuelSupplyPolicy, write CostVariable for the import tech and every
        sector's distribution tech."""
```

The one behavior I baked in as a deliberate choice, not just plumbing: `consolidate()` should check whether a registered sector's `ProxyQuote`/`ScaledProxyQuote` points at a sector that *never itself registered* for that fuel, and warn (or error, depending on `validation_behavior`) — that's the silent-zero/opaque-floor case from `costvariable.py` today, made visible instead of implicit.

Open question for you before this goes further: `CANOEModule.run(self)` currently takes no arguments, but `request()` needs each sector module to hold a reference to the shared `FuelDistribution` instance. Do you want that threaded in as a constructor-injected runtime field on the sector config (like the commented-out `# Runtime data` fields in `commercial/config.py`), or as an explicit parameter on `run()` (which means changing the `CANOEModule` ABC signature)?


----

Good instinct to check — the request()/consolidate() design covers everything that's actually *about* a sector asking for a fuel, but three tables canoe-fuel writes today aren't triggered by any sector's request at all. Here's the full inventory, confirmed against every write in the module:

| Table | What's written | Covered by request()/consolidate()? |
|---|---|---|
| `Commodity` — `C_oil` etc. | Per `(sector, fuel)` demand commodity | **Yes** — `request()` |
| `Commodity` — `F_oil` etc. | Shared upstream supply commodity | **Yes** — `request()`, idempotent |
| `Commodity` — `F_ethos` | Shared external source node | **Mostly** — see below |
| `Commodity` — `co2`/`ch4`/`n2o`/`co2e` | Emission commodities, flag `e` | **No** |
| `Technology` — `F_IMP_<fuel>` / `F_<sector>_<fuel>` | Import + distribution techs | **Yes** — `request()` |
| `Efficiency` / `LifetimeTech` | Per tech, arbitrary defaults | **Yes** — `request()` |
| `EmissionActivity` | Per tech, static CSV lookup | **Yes** — `request()` |
| `CostVariable` | Import + distribution cost split | **Yes** — `consolidate()` |
| `DataSet` | One row per province, every run | **No** |
| `DataSource` | 8 fixed citation rows, every run | **No** |
| `SectorLabel` | 7 fixed rows, every run | **No** |

## The three gaps aren't the same kind of gap

**`co2`/`ch4`/`n2o`/`co2e` and `SectorLabel`** (`techcom.py:66-75`, `postprocessing.py:47-57`) are written unconditionally, regardless of which fuels get requested this run, and they aren't really fuel-module content at all — your own `DECISIONS.md` already says so explicitly: *"Preferred outcome is that canoe-base seeds these globally... this is out of scope for this round."* That "round" is over — you're now actually building `initializer.py`, which already writes `Region`/`TimePeriod`/`TimeSeason`/`global_discount_rate`/`CostEmission` as genuine global seed data. Adding four `Commodity` rows and seven `SectorLabel` rows there closes out a TODO you already wrote down, rather than re-implementing the same workaround inside `fuel_distribution`. This isn't a dynamic `fuel_distribution` needs to model at all — it's misplaced global data that has a real home now.

**`DataSet`/`DataSource`** (`postprocessing.py:13-45`) are provenance/citation bookkeeping for the fuel module's *own run* — "what data went into this, what version, who to cite" — not something any sector's request produces. Every other sector module has the exact same kind of step (you can see it in commercial's own `sources.py`/`post_processing.py` pattern, with its own separate citation list). This isn't part of the sector-facing contract (`request`/`consolidate`) at all; it's the same "module registers its own metadata once" step every module already needs, so `fuel_distribution` should get one too — call it something like `finalize()`, invoked once by the pipeline alongside `consolidate()`, not driven by the registered-fuel set.

**`F_ethos`** is the one genuine in-between case: it's shared infrastructure (the source commodity every `F_IMP_<fuel>` technology draws from), so it doesn't belong to any one `(sector, fuel)` pair — but unlike the emission commodities, it *is* fuel-distribution-specific, not something canoe-base has any reason to know about. Simplest fix: write it idempotently and lazily, the first time `request()` is ever called (same treatment as `F_oil` today, just unconditional-once instead of per-fuel). No new mechanism needed, just don't forget it when you port `techcom.py`'s logic in.

**Net:** the `request`/`consolidate` design is complete for everything that's genuinely a sector-fuel dynamic. What's missing is recognizing that three of canoe-fuel's current writes were never really about sector requests — two belong in `initializer.py` now that it exists, and one is ordinary per-module bookkeeping that wants its own `finalize()`, separate from the linker contract.

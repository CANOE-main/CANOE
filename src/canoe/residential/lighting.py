"""
Lighting: the existing lamps, the new lamps and the demand for light (Glmy).
Nothing in here touches the database.

Only Ontario has data on the lamps in use (IESO 2018 end-use survey, by single and
multi-family housing). Other provinces take Ontario's shares indexed to their use of
each type of energy-saving light relative to Ontario (StatCan), weighed by their
households in single and multi-family housing (NRCan CEUD table 14). The demand is
the CEUD lighting energy use times the average efficacy of the lamps; the existing
lamps are the share of each type of the light demanded in the first model period.

Lamp data (efficacy, life, costs) come from the AEO; lamp life in hours becomes a
lifetime in years with the share of the year lamps are on (`annual_capacity_factor`).
"""

from dataclasses import dataclass

import pandas as pd

from canoe.common import CANOEFuel, CANOEProvince
from canoe.common.periods import existing_stock_vintages

from .end_uses import ResidentialEndUse
from .entities import NewTechnologyParameters
from .existing_stock import (
    EndUseStock,
    capacity_factor_band,
    costs_while_alive,
    existing_technology_parameters,
)
from .technology_catalog import ExistingTechnology, NewTechnology


def efficacy_to_efficiency() -> float:
    """Glmy of light per PJ of electricity in one lm/W"""
    return 0.0317


def lamp_lifetime(life_hours: float, annual_capacity_factor: float) -> float:
    """
    Lifetime (years) of a lamp on `annual_capacity_factor` of the year, rounded.

    Examples
    --------
    >>> lamp_lifetime(14000, 0.0667)
    24.0
    """
    return float(round(life_hours / 8760 / annual_capacity_factor))


@dataclass(frozen=True)
class LightingStock:
    """
    The existing lamps (`stock`) and the parameters of the new lamps selected
    (`new_lamps`, see `entities.NewTechnologyParameters`).
    """

    stock: EndUseStock
    new_lamps: NewTechnologyParameters


def provincial_lamp_shares(
    ontario_shares: pd.DataFrame,
    energy_saving_lights: pd.DataFrame,
    household_shares: pd.DataFrame,
    provinces: list[CANOEProvince],
) -> pd.DataFrame:
    """
    Share of each lamp type in the lighting stock of each province.

    The use of each type of energy-saving light in a province (mean of the 2017 and
    2019 surveys, standing in for 2018, the year of the Ontario survey) over its use
    in Ontario indexes Ontario's shares; the indexed shares are normalised to 1 for
    single and multi-family housing separately, then weighed by the province's
    share of households in each (single family: single detached, single attached and
    mobile homes; multi family: apartments).

    params:
    - ontario_shares: see `loaders.get_ontario_lighting_shares`
    - energy_saving_lights: see `loaders.get_statcan_energy_saving_lights` (Ontario
      included)
    - household_shares: columns `province`, `building_type`, `share`, CEUD table 14

    Returns region, lamp, share
    """
    housing = {
        "single detached": "single_family",
        "single attached": "single_family",
        "mobile homes": "single_family",
        "apartments": "multi_family",
    }
    survey = energy_saving_lights.loc[energy_saving_lights["year"].isin([2017, 2019])]
    usage = survey.groupby(["province", "light_type"], as_index=False)["percent"].mean()
    ontario = usage.loc[usage["province"].isin([CANOEProvince.ONTARIO])]
    index = usage.merge(
        ontario[["light_type", "percent"]].rename(columns={"percent": "ontario"}),
        on="light_type",
    )
    index = index.assign(index=index["percent"] / index["ontario"])

    households = household_shares.assign(
        housing=[housing[b] for b in household_shares["building_type"]]
    )
    households = households.groupby(["province", "housing"])["share"].sum().unstack()

    frames: list[pd.DataFrame] = []
    for province in provinces:
        own_index = index.loc[index["province"].isin([province])].set_index(
            "light_type"
        )["index"]
        shares = ontario_shares.assign(
            single_family=ontario_shares["single_family"]
            * own_index.loc[ontario_shares["statcan_category"]].to_numpy(),
            multi_family=ontario_shares["multi_family"]
            * own_index.loc[ontario_shares["statcan_category"]].to_numpy(),
        )
        share = shares["single_family"] / shares["single_family"].sum() * float(
            households.loc[province, "single_family"]
        ) + shares["multi_family"] / shares["multi_family"].sum() * float(
            households.loc[province, "multi_family"]
        )
        frames.append(
            pd.DataFrame(
                {"region": province, "lamp": shares["lamp"], "share": share.to_numpy()}
            )
        )
    return pd.concat(frames, ignore_index=True)


def aeo_lamp_value(
    aeo_lighting: pd.DataFrame, lamp: str, metric: str, data_year: int | None
) -> float:
    """
    A lamp's value in the AEO lighting data: of the existing stock (`data_year`
    None), else of the latest year of the data before `data_year` (the first year if
    none), or of the existing stock if that year has no value, as the previous
    module.
    """
    rows = aeo_lighting.loc[
        (aeo_lighting["lamp"] == lamp) & (aeo_lighting["metric"] == metric)
    ]
    existing = rows.loc[rows["year"].isna(), "value"]
    if data_year is not None:
        years = sorted(int(y) for y in aeo_lighting["year"].dropna().unique())
        before = [y for y in years if y < data_year]
        year = before[-1] if before else years[0]
        value = rows.loc[rows["year"] == year, "value"]
        if len(value) == 1:
            return float(value.iloc[0])
    if len(existing) != 1:
        raise ValueError(f"No {metric} of lamp {lamp!r} in the AEO lighting data")
    return float(existing.iloc[0])


def lighting_stock(
    energy_use: pd.DataFrame,
    household_shares: pd.DataFrame,
    aeo_lighting: pd.DataFrame,
    ontario_shares: pd.DataFrame,
    energy_saving_lights: pd.DataFrame,
    stock_growth: pd.DataFrame,
    new_lamps: list[NewTechnology],
    annual_capacity_factor: float,
    currency_factor: float,
    provinces: list[CANOEProvince],
    model_periods: list[int],
    period_step: int,
    data_years: dict[int, int],
    capacity_tolerance: float,
    ceud_data_year: int,
) -> LightingStock:
    """
    The existing lamps, the new lamps and the base-year demand for light.

    - Demand: lighting energy use (CEUD table 3) times the average efficacy of the
      stock (lamp shares, see `provincial_lamp_shares`, times AEO efficacies).
    - Existing capacity (Glm): each lamp's share of the light demanded when the
      existing stock stands (the label year of the first model period), over
      `annual_capacity_factor`, spread over the vintages of its
      lifetime from its oldest vintage on. As the previous module, the vintages left
      keep the shares of the oldest ones (see `RESIDENTIAL_MODULE_BUGS.md`).
    - Existing lamps: AEO values of the existing stock (efficacy, lamp life,
      maintenance cost as fixed cost).
    - New lamps: AEO values of the latest year of the data before the data year of
      each vintage (efficacy, lamp life as lifetime by vintage, installation cost,
      maintenance cost).
    - Annual capacity factor: `annual_capacity_factor`, in every region.

    params:
    - energy_use: columns `province`, `energy_use` (PJ), CEUD table 3
    - household_shares: CEUD table 14, see `provincial_lamp_shares`
    - aeo_lighting, ontario_shares, energy_saving_lights: see the loaders
    - stock_growth: columns `region`, `growth`: growth of the demand from the CEUD
      data year to the label year of the first model period
    - new_lamps: the new technologies selected that are lamps
    - currency_factor: USD of the AEO cost year to CAD of the model currency year
    - data_years: model period (vintage) -> year its data is read at
    """
    lamps = [t for t in ExistingTechnology if t.spec().lamp is not None]
    lamp_of = {t: str(t.spec().lamp) for t in lamps}
    cost_factor = ResidentialEndUse.Lighting.cost_factor() * currency_factor

    def existing(metric: str) -> dict[ExistingTechnology, float]:
        return {
            t: aeo_lamp_value(aeo_lighting, lamp_of[t], metric, None) for t in lamps
        }

    efficacy = {
        t: v * efficacy_to_efficiency() for t, v in existing("efficacy").items()
    }
    lifetime = {
        t: lamp_lifetime(v, annual_capacity_factor)
        for t, v in existing("lamp_life").items()
    }
    shares = provincial_lamp_shares(
        ontario_shares, energy_saving_lights, household_shares, provinces
    )
    technology_of = {code: t for t, code in lamp_of.items()}
    shares = shares.assign(technology=[technology_of[c] for c in shares["lamp"]])
    shares = shares.assign(
        efficacy=[efficacy[t] for t in shares["technology"]],
    )
    average_efficacy = (
        (shares["share"] * shares["efficacy"]).groupby(shares["region"]).sum()
    )
    use = energy_use.set_index("province")["energy_use"]
    base_demand = pd.DataFrame(
        {
            "region": average_efficacy.index,
            "end_use": ResidentialEndUse.Lighting,
            "demand": average_efficacy.to_numpy()
            * use.loc[average_efficacy.index].to_numpy(),
        }
    )

    # Existing capacity: share of the light demanded when the existing stock stands
    first_demand = base_demand.merge(stock_growth, on="region")
    first_demand = first_demand.assign(
        demand=first_demand["demand"] * first_demand["growth"]
    )
    stock = shares.merge(first_demand[["region", "demand"]], on="region")
    stock = stock.assign(
        stock=stock["share"] * stock["demand"] / annual_capacity_factor
    )

    oldest = dict(zip(ontario_shares["lamp"], ontario_shares["oldest_vintage"]))
    vintage_rows: list[tuple[ExistingTechnology, int, float]] = []
    for t in lamps:
        by_vintage = existing_stock_vintages(lifetime[t], model_periods[0], period_step)
        oldest_vintage = oldest[lamp_of[t]]
        kept = [
            v for v in by_vintage if pd.isna(oldest_vintage) or v >= int(oldest_vintage)
        ]
        # The previous module paired the vintages kept with the first shares, by
        # position, dropping the share of the newest vintages
        vintage_rows.extend(zip([t] * len(kept), kept, list(by_vintage.values())))
    vintages = pd.DataFrame(vintage_rows, columns=["technology", "vintage", "share"])

    regions = pd.DataFrame({"region": provinces})
    existing_parameters = existing_technology_parameters(
        stock=stock[["region", "technology", "stock"]],
        efficiency=regions.merge(
            vintages[["technology", "vintage"]], how="cross"
        ).assign(
            fuel=CANOEFuel.Electricity,
            efficiency=lambda df: [efficacy[t] for t in df["technology"]],
        ),
        capacity_factor=regions.merge(
            pd.DataFrame({"technology": lamps}), how="cross"
        ).assign(factor=annual_capacity_factor),
        vintages=vintages,
        lifetime=pd.DataFrame(
            {"technology": lamps, "lifetime": [lifetime[t] for t in lamps]}
        ),
        fixed_cost=pd.DataFrame(
            {
                "technology": lamps,
                "cost": [v * cost_factor for v in existing("cost_maintain").values()],
            }
        ),
        provinces=provinces,
        model_periods=model_periods,
        capacity_tolerance=capacity_tolerance,
        efficiency_notes="AEO efficacy of the existing lamps, times 0.0317 (lm/W to "
        + "Glmy/PJ)",
        existing_capacity_notes="Ontario lamp shares by housing type (IESO, 2018), "
        + "indexed to the use of each type by province versus Ontario (StatCan, "
        + "2017-2019) and weighed by households by housing type (NRCan, "
        + f"{ceud_data_year}), times the light demanded at the start of the first model "
        + "period, "
        + "over the annual capacity factor",
        capacity_factor_notes="Lamps on 1.6 hours a day, the US national average "
        + "(DOE, 2012); lower bound 95% of it",
        lifetime_notes="AEO life of the existing lamps (hours) over the hours a year "
        + "they are on",
        fixed_cost_notes="AEO maintenance cost of the existing lamps",
    )

    # New lamps, by vintage
    new_rows: list[tuple[NewTechnology, int, float, float, float, float]] = []
    for t in new_lamps:
        lamp = str(t.spec().lamp)
        for vintage in model_periods:
            year = data_years[vintage]
            new_rows.append(
                (
                    t,
                    vintage,
                    aeo_lamp_value(aeo_lighting, lamp, "efficacy", year)
                    * efficacy_to_efficiency(),
                    lamp_lifetime(
                        aeo_lamp_value(aeo_lighting, lamp, "lamp_life", year),
                        annual_capacity_factor,
                    ),
                    aeo_lamp_value(aeo_lighting, lamp, "cost_install", year)
                    * cost_factor,
                    aeo_lamp_value(aeo_lighting, lamp, "cost_maintain", year)
                    * cost_factor,
                )
            )
    new = regions.merge(
        pd.DataFrame(
            new_rows,
            columns=[
                "technology",
                "vintage",
                "efficiency",
                "lifetime",
                "investment_cost",
                "fixed_cost",
            ],
        ),
        how="cross",
    ).assign(end_use=ResidentialEndUse.Lighting)
    new_fixed_cost = costs_while_alive(
        new[["region", "technology", "vintage", "fixed_cost"]].rename(
            columns={"fixed_cost": "cost"}
        ),
        new[["technology", "vintage", "lifetime"]].drop_duplicates(),
        model_periods,
    )
    new_lamp_parameters = NewTechnologyParameters(
        efficiency=new[["region", "technology", "vintage", "end_use", "efficiency"]],
        investment_cost=new[
            ["region", "technology", "vintage", "investment_cost"]
        ].rename(columns={"investment_cost": "cost"}),
        fixed_cost=new_fixed_cost[
            ["region", "technology", "vintage", "period", "cost"]
        ],
        lifetime=pd.DataFrame(columns=["region", "technology", "lifetime"]),
        lifetime_process=new[["region", "technology", "vintage", "lifetime"]],
        capacity_factor=capacity_factor_band(
            new[["region", "technology", "vintage", "end_use"]].assign(
                factor=annual_capacity_factor
            )
        ),
        efficiency_notes="AEO efficacy of the latest year of the data before the "
        + "vintage's data year, times 0.0317 (lm/W to Glmy/PJ)",
        investment_cost_notes="AEO installation cost of the latest year of the data "
        + "before the vintage's data year",
        fixed_cost_notes="AEO maintenance cost of the latest year of the data before "
        + "the vintage's data year",
        lifetime_notes="",
        lifetime_process_notes="AEO lamp life (hours) of the latest year of the data "
        + "before the vintage's data year, over the hours a year lamps are on",
        capacity_factor_notes="Lamps on 1.6 hours a day, the US national average "
        + "(DOE, 2012); lower bound 95% of it",
    )
    return LightingStock(
        stock=EndUseStock(
            technologies=lamps,
            parameters=existing_parameters,
            base_demand=base_demand,
            demand_notes=f"Lighting energy use (NRCan CEUD table 3, {ceud_data_year}) "
            + "times the average efficacy of the existing lamps. Indexed to the "
            + "demand driver",
            capacity_factor=existing_parameters.capacity_factor.loc[
                lambda df: df["operator"].astype(str) == "le",
                ["region", "technology", "factor"],
            ].drop_duplicates(),
        ),
        new_lamps=new_lamp_parameters,
    )

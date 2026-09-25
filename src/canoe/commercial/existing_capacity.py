from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from canoe.commercial.config import AEOConfig, CEUDConfig
import pandas as pd

from canoe.common import CANOEFuel, CANOEProvince, GoldConnectorConfig

from .end_uses import CommercialEndUse
from .loaders import (
    get_aeo_data,
    get_ceud_table,
    get_exchange_and_inflation_dfs,
    get_statcan_atlantic_fractions_table,
)
from .technology_catalog import NEW_TECHNOLOGIES, NewTechnology

# AEO CDM costs are in $/(kBtu/h); multiply to get M$/(PJ/y)
_AEO_COST_TO_M_PER_PJ = 0.108198


def compute_existing_tech_life_params(
    provinces: list[CANOEProvince],
    ceud_config: "CEUDConfig",
    data_cache_config: GoldConnectorConfig,
    aeo_config: "AEOConfig",
) -> pd.DataFrame:
    # Energy consumption by fuel
    province_ceud = _load_all_ceud_tables(provinces, ceud_config, data_cache_config)
    # For estimating existing stock efficiencies by end use and fuel from installed market shares in AEO CDM
    province_aeo_data = _load_aeo_data(provinces, aeo_config.us_census_mapping)

    # Prepare end use dataframe
    exs_dfs: list[pd.DataFrame] = []
    for province in provinces:
        df_exs = province_ceud[province]
        cdm_exs = province_aeo_data[province]

        # Add columns from AEO CDM to CEUD table
        # All these operations work under the assumption that the dfs are OWNED REFERENCES
        df_exs.drop(
            [euf for euf in df_exs.index if euf not in cdm_exs.index], inplace=True
        )
        for col in ["avg_eff", "avg_life", "avg_fixed_cost"]:
            df_exs[col] = df_exs.index.map(lambda euf: cdm_exs.loc[euf, col])  # noqa: B023  # pyright: ignore[reportUnknownLambdaType]

        ## Adjust units of fixed cost
        df_exs["avg_fixed_cost"] *= (
            _AEO_COST_TO_M_PER_PJ  # AEO CDM costs are in $/(kBtu/h); multiply to get M$/(PJ/y)
        )
        df_exs["avg_fixed_cost"] = _aeo_conv_curr(df_exs["avg_fixed_cost"])

        ## Multiply secondary energies by average efficiencies to get demanded output energies
        df_exs["dem"] = df_exs.index.map(
            lambda euf: df_exs.loc[euf, "sec"] * cdm_exs.loc[euf, "avg_eff"]  # noqa: B023  # pyright: ignore[reportUnknownLambdaType]
        )
        df_exs["province"] = province
        df_exs.reset_index(inplace=True)
        # df_dem = df_exs["dem"].groupby("end_use").sum()
        exs_dfs.append(df_exs)
    out_df = pd.concat(exs_dfs).reset_index(drop=True)
    out_df["fuel"] = out_df["fuel"].map(CANOEFuel.from_str)
    return out_df


def _load_all_ceud_tables(
    provinces: list[CANOEProvince],
    ceud_config: "CEUDConfig",
    data_cache_config: GoldConnectorConfig,
) -> dict["CANOEProvince", pd.DataFrame]:
    """
    Secondary energy consumption by end use and fuel from NRCan Comprehensive Energy Use Database
    """
    atlantic_fraction = get_statcan_atlantic_fractions_table(data_cache_config)

    province_ceud: dict[CANOEProvince, pd.DataFrame] = {}
    for province in provinces:
        # This table is consumption (PJ) per fuel for each end use
        sh_ceud = _merge_ceud_fuels(
            get_ceud_table(24, 2, 7, province, data_cache_config)[ceud_config.data_year]
        )
        sc_ceud = get_ceud_table(32, 2, 3, province, data_cache_config)[
            ceud_config.data_year
        ]

        # Filter out low-fraction fuels
        sc_ceud = sc_ceud.loc[
            sc_ceud / sc_ceud.sum() > ceud_config.space_cooling_tolerance
        ]

        # Aggregate into a single DataFrame
        df_sph = pd.DataFrame(data=sh_ceud.values, columns=["sec"])
        df_sph["end_use"] = "space heating"
        df_sph["fuel"] = sh_ceud.index
        df_spc = pd.DataFrame(data=sc_ceud.values, columns=["sec"])
        df_spc["end_use"] = "space cooling"
        df_spc["fuel"] = sc_ceud.index
        df_out = pd.concat([df_sph, df_spc])

        if province.is_atlantic():
            df_out = _apply_atlantic_fraction(df_out, province, atlantic_fraction)
        df_out.set_index(["end_use", "fuel"], inplace=True)
        province_ceud[province] = df_out
    return province_ceud


def load_total_secondary_energy(
    provinces: list[CANOEProvince],
    ceud_config: "CEUDConfig",
    data_cache_config: GoldConnectorConfig,
) -> pd.DataFrame:
    """
    Total commercial secondary energy use by fuel from NRCan CEUD (table 1).
    Returns one row per (province, fuel) with columns `province`, `fuel` (CANOEFuel), `sec`.
    """
    atlantic_fraction = get_statcan_atlantic_fractions_table(data_cache_config)

    frames: list[pd.DataFrame] = []
    for province in provinces:
        sec = _merge_ceud_fuels(
            get_ceud_table(1, 2, 7, province, data_cache_config)[
                ceud_config.data_year
            ].astype(float)
        )
        df = pd.DataFrame({"sec": sec.values, "fuel": sec.index})
        if province.is_atlantic():
            df = _apply_atlantic_fraction(df, province, atlantic_fraction)
        frames.append(df.assign(province=province))
    out = pd.concat(frames, ignore_index=True)
    out["fuel"] = out["fuel"].map(CANOEFuel.from_str)
    return out[["province", "fuel", "sec"]]  # pyright: ignore[reportReturnType]


def load_new_technology_params(
    new_technologies: dict[NewTechnology, list[CommercialEndUse]],
    provinces: list[CANOEProvince],
    us_census_mapping: dict[CANOEProvince, str],
) -> pd.DataFrame:
    """
    Efficiency, lifetime and costs of new technologies from the AEO CDM technology menu
    (ktek), for the AEO technology of each (technology, end use) in `technology_catalog`.

    Each province takes the values of its comparable US census division
    (`us_census_mapping`), as for the existing stock.

    NOTE: this changed from the previous version of the code, which used the first ktek
    row of each technology (always the New England census division) for every province.
    ktek values are the same across census divisions except for the ground-source heat
    pump heating maintenance cost (3.5 in New England, 3.75 elsewhere), so only that
    value changes, for provinces not mapped to New England.

    params:
    - new_technologies: technology -> end uses it serves, see `EndUsesConfig.new_technologies`

    Returns one row per (technology, end_use, province) with columns `technology`,
    `end_use`, `province`, `fuel`, `aeo_technology`, `efficiency`, `life` (years),
    `investment_cost` (M$/(PJ/y), CAD 2020) and `fixed_cost` (M$/(PJ/y) per year, CAD 2020).
    """
    columns = [
        "technology",
        "end_use",
        "province",
        "fuel",
        "aeo_technology",
        "efficiency",
        "life",
        "investment_cost",
        "fixed_cost",
    ]
    aeo = get_aeo_data()

    rows: list[dict[str, Any]] = []
    for technology, end_uses in new_technologies.items():
        spec = NEW_TECHNOLOGIES[technology]
        for end_use in end_uses:
            aeo_technology = spec.aeo_technologies[end_use]
            for province in provinces:
                census_division = us_census_mapping[province]
                match = aeo[
                    (aeo["techname"] == aeo_technology)
                    & (aeo["reg"] == census_division)
                ]
                if match.empty:
                    raise ValueError(
                        f"AEO technology {aeo_technology!r} ({technology.value}, "
                        + f"{end_use.get_full_name()}) not found for census division "
                        + f"{census_division!r} ({province.short()})"
                    )
                aeo_row = match.iloc[0]
                rows.append(
                    {
                        "technology": technology,
                        "end_use": end_use,
                        "province": province,
                        "fuel": spec.fuel,
                        "aeo_technology": aeo_technology,
                        "efficiency": aeo_row["efficiency"],
                        "life": aeo_row["life"],
                        "investment_cost": _aeo_conv_curr(
                            aeo_row["capcst"] * _AEO_COST_TO_M_PER_PJ
                        ),
                        "fixed_cost": _aeo_conv_curr(
                            aeo_row["maintcst"] * _AEO_COST_TO_M_PER_PJ
                        ),
                    }
                )
    return pd.DataFrame(rows, columns=columns)


def _merge_ceud_fuels(sec: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """
    Aggregate heavy/light oil and propane/natural gas as we dont have that technological
    resolution. Steam is dropped.
    """
    sec = sec.copy()
    sec["oil"] = sec["light fuel oil and kerosene"] + sec["heavy fuel oil"]
    sec["natural gas"] = sec["natural gas"] + sec["other"]
    return sec.drop(["other", "steam", "light fuel oil and kerosene", "heavy fuel oil"])


def _apply_atlantic_fraction(
    df: pd.DataFrame,
    province: CANOEProvince,
    atlantic_fraction: pd.Series,
) -> pd.DataFrame:
    """
    Scale the aggregated Atlantic CEUD `sec` column (by `fuel`) down to `province`.
    Fuels we don't have Statcan data for in the atlantic region are dropped.
    """
    province_fraction = atlantic_fraction.loc[province.value.lower()]
    df = df[df["fuel"].isin(province_fraction.index)]  # pyright: ignore[reportAssignmentType]
    return df.assign(sec=df["sec"] * province_fraction[df["fuel"]].values)


def _load_aeo_data(
    provinces: list[CANOEProvince], us_mapping: dict[CANOEProvince, str]
) -> dict["CANOEProvince", pd.DataFrame]:
    """
    Estimate incumbent space heating/cooling equipment efficiency, lifetime, and fixed
    cost by fuel from the EIA AEO Commercial Demand Module (CDM) technology data.

    The CDM's KTEK technology file characterizes the market shares, efficiencies, capital
    and maintenance costs, and lifetimes of commercial HVAC equipment vintages by US census
    division. Since no equivalent Canadian dataset exists, each province is mapped to a
    comparable US census division (`us_mapping`) and its installed technology shares are
    used as a proxy for the mix of existing equipment, weighting each technology's
    efficiency/life/cost by its (respectively service- or secondary-energy-based) share to
    get a single representative average value per province, end use, and fuel.
    """
    out_dict = {}
    for province in provinces:
        cdm_exs = get_aeo_data()
        cdm_exs = cdm_exs.loc[
            (
                (cdm_exs["serv"] == "space heating")
                | (cdm_exs["serv"] == "space cooling")
            )
        ]
        cdm_exs = cdm_exs.loc[cdm_exs["reg"] == us_mapping[province]]
        cdm_exs = cdm_exs.loc[~cdm_exs["techname"].str.contains("chiller")]
        cdm_exs.rename({"share": "serv_share"}, inplace=True, axis="columns")
        cdm_exs = cdm_exs.loc[cdm_exs["serv_share"] > 0]

        # Convert service energy share to secondary energy consumption share by dividing by efficiencies
        cdm_exs["sec_share"] = cdm_exs["serv_share"]
        for end_use in cdm_exs["serv"].unique():
            for fuel in cdm_exs["fuel"].unique():
                df = cdm_exs.loc[
                    (cdm_exs["serv"] == end_use) & (cdm_exs["fuel"] == fuel)
                ].copy()
                df["sec_share"] = df["serv_share"] / df["efficiency"]
                df["sec_share"] = df["sec_share"] / df["sec_share"].sum()
                df["serv_share"] = df["serv_share"] / df["serv_share"].sum()
                cdm_exs.loc[
                    (cdm_exs["serv"] == end_use) & (cdm_exs["fuel"] == fuel),
                    "sec_share",
                ] = df["sec_share"]
                cdm_exs.loc[
                    (cdm_exs["serv"] == end_use) & (cdm_exs["fuel"] == fuel),
                    "serv_share",
                ] = df["serv_share"]

        ## 3. Get average efficiency (and life) for each end use and fuel
        cdm_exs["avg_eff"] = cdm_exs["efficiency"] * cdm_exs["sec_share"]
        cdm_exs["avg_life"] = (cdm_exs["life"] * cdm_exs["serv_share"]).round()
        cdm_exs["avg_fixed_cost"] = cdm_exs["maintcst"] * cdm_exs["serv_share"]

        cdm_exs = cdm_exs.groupby(["serv", "fuel"]).sum()
        out_dict[province] = cdm_exs
    return out_dict


def _aeo_conv_curr(
    orig_cost: pd.DataFrame | pd.Series | float,
    orig_year: int = 2022,  # aeo_currency_year
    orig_curr: str = "USD",  # aeo_currency
) -> Any:
    """
    Converts a cost from its original currency and year to the base currency and year

    params:
    - orig_cost: the original cost as given in the data source
    - orig_year: the original currency year in the data source. By default, aeo_currency_year from params.toml
    - orig_curr: the orignal currency in the data source (USD, EUR, GDP, AUD). By default, aeo_currency from params.toml

    For example, if the original cost from data is $2500 USD (2010),
    cost = conv_curr(2500, 2010, 'USD')
    """

    # Exchange rate and inflation tables
    exchange, inflation = get_exchange_and_inflation_dfs()

    # Currency and currency year for final data, converting to this
    base_curr = "CAD"
    base_currency_year = 2020

    # Multiplier for final currency (to normalise if not using CAD2020)
    base_fact = (
        exchange.loc[base_currency_year, base_curr]
        * inflation.loc[base_currency_year, "gdp_deflator"]
    )

    return (
        orig_cost
        * exchange.loc[orig_year, orig_curr]
        * inflation.loc[orig_year, "gdp_deflator"]
        / base_fact
    )

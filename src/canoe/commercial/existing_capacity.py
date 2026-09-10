from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from canoe.commercial.config import AEOConfig, CEUDConfig
import pandas as pd

from canoe.common import CANOEProvince, GoldConnectorConfig

from .loaders import get_aeo_data, get_ceud_table, get_statcan_atlantic_fractions_table


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
        # All these operations work under the assumption that the dfs are REFERENCES
        df_exs.drop(
            [euf for euf in df_exs.index if euf not in cdm_exs.index], inplace=True
        )
        for col in ["avg_eff", "avg_life", "avg_fixed_cost"]:
            df_exs[col] = df_exs.index.map(lambda euf: cdm_exs.loc[euf, col])  # noqa: B023  # pyright: ignore[reportUnknownLambdaType]

        ## Multiply secondary energies by average efficiencies to get demanded output energies
        df_exs["dem"] = df_exs.index.map(
            lambda euf: df_exs.loc[euf, "sec"] * cdm_exs.loc[euf, "avg_eff"]  # noqa: B023  # pyright: ignore[reportUnknownLambdaType]
        )
        df_exs["province"] = province
        df_exs.reset_index(inplace=True)
        # df_dem = df_exs["dem"].groupby("end_use").sum()
        exs_dfs.append(df_exs)
    return pd.concat(exs_dfs).reset_index()


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
        sh_ceud = get_ceud_table(24, 2, 7, province, data_cache_config)[
            ceud_config.base_year
        ]
        sc_ceud = get_ceud_table(32, 2, 3, province, data_cache_config)[
            ceud_config.base_year
        ]

        # Aggregate heavy/light oil and propane/natural gas as we dont have that technological resolution
        sh_ceud["oil"] = (
            sh_ceud["light fuel oil and kerosene"] + sh_ceud["heavy fuel oil"]
        )
        sh_ceud["natural gas"] = sh_ceud["natural gas"] + sh_ceud["other"]
        sh_ceud.drop(
            ["other", "steam", "light fuel oil and kerosene", "heavy fuel oil"],
            inplace=True,
        )
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
            # Some fuels we don't have data for in the atlantic region, so set to 0
            df_out = df_out[
                df_out["fuel"].isin(atlantic_fraction[province.value.lower()].index)  # pyright: ignore[reportArgumentType, reportAttributeAccessIssue]
            ]
            df_out["sec"] = (
                df_out["sec"]
                * atlantic_fraction.loc[province.value.lower()][df_out["fuel"]].values
            )
        df_out.set_index(["end_use", "fuel"], inplace=True)
        province_ceud[province] = df_out  # pyright: ignore[reportArgumentType]
    return province_ceud


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

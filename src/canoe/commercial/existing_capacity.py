from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import CANOECommercialConfig, CommercialEndUse
import pandas as pd

from canoe.common import CANOEProvince

from .loaders import get_ceud_table, get_statcan_atlantic_fractions_table


def compute_existing_capacity(cfg: "CANOECommercialConfig"):
    province_ceud = _load_all_ceud_tables(cfg)


def _load_all_ceud_tables(
    cfg: "CANOECommercialConfig",
) -> dict["CommercialEndUse", pd.DataFrame]:
    atlantic_fraction = get_statcan_atlantic_fractions_table(cfg)

    province_ceud = {}
    for province in cfg.provinces:
        # This table is consumption (PJ) per fuel for each end use
        sh_ceud = get_ceud_table(24, 2, 7, province, cfg.data_cache_config)[
            cfg.ceud_config.base_year
        ]
        sc_ceud = get_ceud_table(32, 2, 3, province, cfg.data_cache_config)[
            cfg.ceud_config.base_year
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
            sc_ceud / sc_ceud.sum() > cfg.ceud_config.space_cooling_tolerance
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
                df_out["fuel"].isin(atlantic_fraction[province.value.lower()].index)
            ]
            df_out["sec"] = (
                df_out["sec"]
                * atlantic_fraction.loc[province.value.lower()][df_out["fuel"]].values
            )
        df_out.set_index(["end_use", "fuel"], inplace=True)
        province_ceud[province] = df_out
    return province_ceud

from collections.abc import Sequence

import pandas as pd
import pytest

from canoe.common import CANOEFuel, CANOEFuelImport, CANOEProvince, CANOESector
from canoe.fuel.loaders import SourcePrices
from canoe.fuel.price_sources import (
    EIASeries,
    PriceFallback,
    combine_price_sources,
    eia_price_series,
    harmonize_atb_prices,
    harmonize_eia_prices,
    harmonize_fixed_prices,
    price_conversion_factor,
)
from canoe.fuel.prices import (
    check_price_coverage,
    delivered_prices_by_period,
    split_import_and_distribution,
)

ON, NS = CANOEProvince.ONTARIO, CANOEProvince.NOVA_SCOTIA
NG = CANOEFuel.NaturalGas


@pytest.mark.parametrize("previous", [False, True])
def test_every_eia_entry_names_a_series(previous: bool):
    for series in eia_price_series(previous).values():
        assert isinstance(series, EIASeries)
        assert series.sector.get_eia_sector() is not None
        assert series.fuel.get_eia_fuel(series.sector) is not None


def test_errors_only_change_existing_eia_entries():
    assert eia_price_series(True).keys() == eia_price_series(False).keys()


def _model_units(
    columns: list[str], rows: Sequence[tuple[object, ...]]
) -> SourcePrices:
    return SourcePrices(
        pd.DataFrame(rows, columns=[*columns, "price"]), "CAD", 2020, "$/GJ", "src"
    )


def _all_harmonized() -> pd.DataFrame:
    """Every (sector, fuel) of the default sources, priced 1.0, in Ontario."""
    eia = _model_units(
        ["eia_sector", "eia_fuel", "year"],
        list(
            dict.fromkeys(
                (s.sector.get_eia_sector(), s.fuel.get_eia_fuel(s.sector), 2030, 1.0)
                for s in eia_price_series(False).values()
            )
        ),
    )
    atb = _model_units(
        ["atb_technology"],
        [(t, 1.0) for t in {f.get_atb_technology() for f in CANOEFuel} - {None}],
    )
    fixed = _model_units(
        ["fuel"],
        [
            (f, 1.0)
            for f in (
                CANOEFuel.Ethanol,
                CANOEFuel.RenewableDiesel,
                CANOEFuel.SyntheticJetFuel,
            )
        ],
    )
    return combine_price_sources(
        [
            harmonize_eia_prices(eia, [ON], False),
            harmonize_atb_prices(atb, [ON], [2030]),
            harmonize_fixed_prices(fixed, [ON], [2030]),
        ],
        PriceFallback.PerSeries,
    )


class TestDefaultSources:
    def test_no_price_for_electricity_or_other_fuels(self):
        fuels = set(_all_harmonized()["fuel"])
        assert CANOEFuel.Electricity not in fuels
        assert CANOEFuel.Other not in fuels

    def test_sources_price_disjoint_fuels(self):
        # So the fallback does not change the default prices
        prices = _all_harmonized()
        per_fuel = combine_price_sources([prices], PriceFallback.PerFuel)
        assert len(per_fuel) == len(prices)
        assert not prices.duplicated(["region", "sector", "fuel", "year"]).any()


EXCHANGE = pd.DataFrame({"CAD": [1.0, 1.0], "USD": [1.25, 1.2]}, index=[2020, 2024])
INFLATION = pd.DataFrame({"gdp_deflator": [1.0, 0.9]}, index=[2020, 2024])


def _usd_eia() -> SourcePrices:
    return SourcePrices(pd.DataFrame(), "USD", 2024, "$/MMBtu", "EIA")


class TestPriceConversion:
    def test_converts_mmbtu_to_gj_and_usd_to_model_cad(self):
        factor = price_conversion_factor(_usd_eia(), 2020, EXCHANGE, INFLATION, False)
        assert factor == pytest.approx(1.2 * 0.9 / 1.055056)

    def test_previous_module_multiplies_by_the_fixed_factors(self):
        factor = price_conversion_factor(_usd_eia(), 2020, EXCHANGE, INFLATION, True)
        assert factor == pytest.approx(1.055 * 1.22 * 0.877689699)

    def test_previous_module_only_gives_2020_dollars(self):
        with pytest.raises(ValueError, match="gives 2020 CAD"):
            price_conversion_factor(_usd_eia(), 2022, EXCHANGE, INFLATION, True)

    def test_harmonizers_reject_unconverted_prices(self):
        with pytest.raises(ValueError, match="expected CAD \\$/GJ"):
            harmonize_eia_prices(_usd_eia(), [ON], False)


def _eia(rows: Sequence[tuple[str | None, str | None, int, float]]) -> SourcePrices:
    return _model_units(["eia_sector", "eia_fuel", "year"], rows)


class TestEIAHarmonization:
    def _prices(self) -> pd.DataFrame:
        # One row per series, though several entries read the same one
        eia = _eia(
            list(
                dict.fromkeys(
                    (
                        s.sector.get_eia_sector(),
                        s.fuel.get_eia_fuel(s.sector),
                        2030,
                        4.0,
                    )
                    for s in eia_price_series(False).values()
                )
            )
        )
        return harmonize_eia_prices(eia, [ON, NS], False)

    def test_proxy_series_and_factors(self):
        prices = self._prices()
        cng = prices.loc[
            prices["fuel"].isin([CANOEFuel.CompressedNaturalGas])
            & prices["region"].isin([ON])
        ]
        assert list(cng["price"]) == [pytest.approx(4.0 * 0.89)]
        assert cng["source"].iloc[0].endswith("× 0.89")

    def test_national_series_in_every_province(self):
        prices = self._prices()
        assert set(prices["region"]) == {ON, NS}
        assert len(prices.loc[prices["region"].isin([ON])]) == len(
            eia_price_series(False)
        )

    def test_rejects_a_missing_series(self):
        with pytest.raises(ValueError, match="no EIA series"):
            harmonize_eia_prices(_eia([]), [ON], False)


def _harmonized(
    rows: list[tuple[CANOEProvince, CANOESector, int, float]], source: str
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "region": r,
                "sector": s,
                "fuel": NG,
                "year": y,
                "price": p,
                "source": source,
            }
            for r, s, y, p in rows
        ],
        columns=["region", "sector", "fuel", "year", "price", "source"],
    )


class TestCombine:
    regional: pd.DataFrame = _harmonized(
        [(ON, CANOESector.Commercial, 2030, 9.0)], "regional"
    )
    national: pd.DataFrame = _harmonized(
        [
            (ON, CANOESector.Commercial, 2030, 8.0),
            (ON, CANOESector.Electricity, 2030, 3.0),
            (NS, CANOESector.Commercial, 2030, 8.0),
        ],
        "national",
    )

    def test_per_fuel_takes_the_whole_fuel_from_the_first_source(self):
        combined = combine_price_sources(
            [self.regional, self.national], PriceFallback.PerFuel
        )
        assert list(combined["source"]) == ["regional"]

    def test_per_series_fills_the_gaps(self):
        combined = combine_price_sources(
            [self.regional, self.national], PriceFallback.PerSeries
        )
        assert list(zip(combined["region"], combined["sector"], combined["price"])) == [
            (ON, CANOESector.Commercial, 9.0),
            (ON, CANOESector.Electricity, 3.0),
            (NS, CANOESector.Commercial, 8.0),
        ]


def test_coverage_drops_the_provinces_without_a_price():
    prices = _harmonized([(ON, CANOESector.Commercial, 2030, 9.0)], "")
    with pytest.raises(ValueError, match=r"commercial natural gas \(NS\)"):
        check_price_coverage(
            [CANOEFuelImport(CANOESector.Commercial, NG, (NS, ON))], prices, "error"
        )
    supplied = check_price_coverage(
        [CANOEFuelImport(CANOESector.Commercial, NG, (NS, ON))], prices, "warning"
    )
    assert [i.provinces for i in supplied] == [(ON,)]


PRICES = _harmonized(
    [
        (ON, CANOESector.Electricity, 2030, 3.0),
        (ON, CANOESector.Commercial, 2030, 9.0),
        (ON, CANOESector.Agriculture, 2030, 2.0),
        (NS, CANOESector.Electricity, 2030, 5.0),
        (NS, CANOESector.Commercial, 2030, 9.0),
    ],
    "src",
)


class TestDeliveredPrices:
    def test_reads_each_period_at_its_projection_year(self):
        delivered = delivered_prices_by_period(PRICES, [NG], {2025: 2030})
        assert list(zip(delivered["period"], delivered["year"])) == [(2025, 2030)] * 5

    def test_rejects_a_year_without_data(self):
        with pytest.raises(ValueError, match="in ON: no price in 2035"):
            delivered_prices_by_period(PRICES, [NG], {2025: 2035})

    def test_skips_fuels_not_supplied(self):
        assert delivered_prices_by_period(PRICES, [CANOEFuel.Coal], {2025: 2030}).empty


class TestSplit:
    def _split(self, imports: list[CANOEFuelImport]):
        return split_import_and_distribution(
            delivered_prices_by_period(PRICES, [NG], {2025: 2030}), imports, ""
        )

    def test_import_is_the_cheapest_entry_of_the_region_even_if_it_does_not_run(self):
        imports, distribution = self._split(
            [
                CANOEFuelImport(CANOESector.Commercial, NG, (ON, NS)),
                CANOEFuelImport(CANOESector.Agriculture, NG, (ON,)),
            ]
        )
        # Ontario: agriculture (2.0); Nova Scotia: electric power (5.0)
        assert list(zip(imports["region"], imports["cost"])) == [(NS, 5.0), (ON, 2.0)]
        assert "agriculture" in imports["notes"].iloc[1]
        assert list(
            zip(distribution["sector"], distribution["region"], distribution["cost"])
        ) == [
            (CANOESector.Commercial, ON, 7.0),
            (CANOESector.Commercial, NS, 4.0),
            (CANOESector.Agriculture, ON, 0.0),
        ]

    def test_each_fuel_is_imported_where_some_sector_takes_it(self):
        imports, distribution = self._split(
            [CANOEFuelImport(CANOESector.Commercial, NG, (NS,))]
        )
        assert list(imports["region"]) == [NS]
        assert list(distribution["region"]) == [NS]

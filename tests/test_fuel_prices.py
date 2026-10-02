import pandas as pd
import pytest

from canoe.common import CANOEFuel, CANOEFuelImport, CANOEProvince, CANOESector
from canoe.fuel.loaders import SourcePrices
from canoe.fuel.prices import (
    DELIVERED_PRICE_SOURCES,
    ATBFuelCost,
    EIASeries,
    FixedPrice,
    PriceSource,
    compute_delivered_prices,
    get_delivered_price_sources,
    price_conversion_factor,
    split_import_and_distribution,
)

ALL_SOURCES = list(get_delivered_price_sources(True).items()) + list(
    DELIVERED_PRICE_SOURCES.items()
)


@pytest.mark.parametrize(("key", "source"), ALL_SOURCES)
def test_every_source_names_a_series(
    key: tuple[CANOESector, CANOEFuel], source: PriceSource
):
    if isinstance(source, EIASeries):
        assert source.sector.get_eia_sector() is not None
        assert source.fuel.get_eia_fuel(source.sector) is not None
    elif isinstance(source, ATBFuelCost):
        assert source.fuel.get_atb_technology() is not None
    else:
        assert isinstance(source, FixedPrice)
        assert source.fuel == key[1]


def test_no_price_for_electricity_or_other_fuels():
    fuels = {fuel for _, fuel in DELIVERED_PRICE_SOURCES}
    assert CANOEFuel.Electricity not in fuels
    assert CANOEFuel.Other not in fuels


def test_errors_only_change_existing_entries():
    assert get_delivered_price_sources(True).keys() == DELIVERED_PRICE_SOURCES.keys()


EXCHANGE = pd.DataFrame({"CAD": [1.0, 1.0], "USD": [1.25, 1.2]}, index=[2020, 2024])
INFLATION = pd.DataFrame({"gdp_deflator": [1.0, 0.9]}, index=[2020, 2024])
NG = CANOEFuel.NaturalGas


def _eia(rows: list[tuple[str, str, int, float]]) -> SourcePrices:
    return SourcePrices(
        pd.DataFrame(rows, columns=["eia_sector", "eia_fuel", "year", "price"]),
        "USD",
        2024,
        "$/MMBtu",
        "EIA",
    )


def _empty(columns: list[str]) -> SourcePrices:
    return SourcePrices(
        pd.DataFrame(columns=[*columns, "price"]), "CAD", 2020, "$/GJ", ""
    )


class TestPriceConversion:
    def test_converts_mmbtu_to_gj_and_usd_to_model_cad(self):
        factor = price_conversion_factor(_eia([]), 2020, EXCHANGE, INFLATION, False)
        assert factor == pytest.approx(1.2 * 0.9 / 1.055056)

    def test_previous_module_multiplies_by_the_fixed_factors(self):
        factor = price_conversion_factor(_eia([]), 2020, EXCHANGE, INFLATION, True)
        assert factor == pytest.approx(1.055 * 1.22 * 0.877689699)

    def test_previous_module_only_gives_2020_dollars(self):
        with pytest.raises(ValueError, match="gives 2020 CAD"):
            price_conversion_factor(_eia([]), 2022, EXCHANGE, INFLATION, True)


SOURCES: dict[tuple[CANOESector, CANOEFuel], PriceSource] = {
    (CANOESector.Electricity, NG): EIASeries(CANOESector.Electricity, NG),
    (CANOESector.Commercial, NG): EIASeries(CANOESector.Commercial, NG),
    (CANOESector.Agriculture, NG): EIASeries(CANOESector.Industry, NG, 0.5),
}


class TestDeliveredPrices:
    def _delivered(self, projection_years: dict[int, int]) -> pd.DataFrame:
        eia = _eia(
            [
                ("Electric Power", "Natural Gas", 2030, 3.0),
                ("Commercial", "Natural Gas", 2030, 9.0),
                ("Industrial", "Natural Gas", 2030, 4.0),
            ]
        )
        return compute_delivered_prices(
            SOURCES,
            [NG],
            projection_years,
            eia,
            _empty(["atb_technology"]),
            _empty(["fuel"]),
        )

    def test_reads_each_period_at_its_projection_year(self):
        delivered = self._delivered({2025: 2030})
        assert list(
            zip(delivered["period"], delivered["year"], delivered["price"])
        ) == [
            (2025, 2030, 3.0),
            (2025, 2030, 9.0),
            (2025, 2030, 2.0),  # industrial series times 0.5
        ]

    def test_rejects_a_year_without_data(self):
        with pytest.raises(
            ValueError, match="no EIA price 'Electric Power : Natural Gas' in 2035"
        ):
            self._delivered({2025: 2035})

    def test_import_is_the_cheapest_entry_even_if_its_sector_does_not_run(self):
        imports, distribution = split_import_and_distribution(
            self._delivered({2025: 2030}),
            [
                CANOEFuelImport(CANOESector.Commercial, NG, (CANOEProvince.ONTARIO,)),
                CANOEFuelImport(CANOESector.Agriculture, NG, (CANOEProvince.ONTARIO,)),
            ],
            "",
        )
        # Agriculture (2.0) is cheaper than electric power (3.0): it sets the import
        assert list(imports["cost"]) == [2.0]
        assert "agriculture" in imports["notes"].iloc[0]
        assert list(zip(distribution["sector"], distribution["cost"])) == [
            (CANOESector.Commercial, 7.0),
            (CANOESector.Agriculture, 0.0),
        ]


def test_each_sector_is_supplied_in_its_provinces_and_imports_in_all_of_them():
    ON, NS = CANOEProvince.ONTARIO, CANOEProvince.NOVA_SCOTIA
    imports, distribution = split_import_and_distribution(
        TestDeliveredPrices()._delivered({2025: 2030}),
        [
            CANOEFuelImport(CANOESector.Commercial, NG, (NS,)),
            CANOEFuelImport(CANOESector.Agriculture, NG, (ON,)),
        ],
        "",
    )
    # In the order of CANOEProvince
    assert list(imports["region"]) == [NS, ON]
    assert list(zip(distribution["sector"], distribution["region"])) == [
        (CANOESector.Commercial, NS),
        (CANOESector.Agriculture, ON),
    ]

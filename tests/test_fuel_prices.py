from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pytest

from canoe.common import CANOEFuel, CANOEFuelImport, CANOEProvince, CANOESector
from canoe.fuel.loaders import SourcePrices
from canoe.fuel.price_sources import (
    EIASeries,
    PriceFallback,
    atb_price_table,
    check_price_table,
    combine_price_sources,
    convert_to_model_units,
    eia_price_series,
    eia_price_table,
    expand_price_table,
    fixed_price_table,
    price_conversion_factor,
    read_price_table,
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


def _source(columns: list[str], rows: Sequence[tuple[object, ...]]) -> SourcePrices:
    return SourcePrices(
        pd.DataFrame(rows, columns=[*columns, "price"]), "USD", 2024, "$/MMBtu", "src"
    )


def _eia(price: float = 4.0) -> SourcePrices:
    """Every series the EIA entries read, once, in 2030."""
    return _source(
        ["eia_sector", "eia_fuel", "year"],
        list(
            dict.fromkeys(
                (s.sector.get_eia_sector(), s.fuel.get_eia_fuel(s.sector), 2030, price)
                for s in eia_price_series(False).values()
            )
        ),
    )


def _default_tables() -> list[pd.DataFrame]:
    atb = _source(
        ["atb_technology"],
        [(t, 1.0) for t in {f.get_atb_technology() for f in CANOEFuel} - {None}],
    )
    fixed = _source(
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
    return [
        eia_price_table(_eia(), False),
        atb_price_table(atb),
        fixed_price_table(fixed),
    ]


class TestDefaultSources:
    def test_tables_are_price_tables(self):
        for table in _default_tables():
            check_price_table(table, "default")

    def test_no_price_for_electricity_or_other_fuels(self):
        fuels = {f for table in _default_tables() for f in table["fuel"]}
        assert CANOEFuel.Electricity not in fuels
        assert CANOEFuel.Other not in fuels

    def test_sources_price_disjoint_fuels(self):
        # So the fallback does not change the default prices
        fuels = [set(table["fuel"]) for table in _default_tables()]
        assert sum(len(f) for f in fuels) == len(set().union(*fuels))

    def test_eia_proxy_series_and_factors(self):
        eia = eia_price_table(_eia(), False)
        cng = eia.loc[eia["fuel"].isin([CANOEFuel.CompressedNaturalGas])]
        assert list(cng["price"]) == [pytest.approx(4.0 * 0.89)]
        assert cng["source"].iloc[0].endswith("× 0.89")
        assert cng["region"].isna().all()

    def test_eia_rejects_a_missing_series(self):
        with pytest.raises(ValueError, match="no EIA series"):
            eia_price_table(_source(["eia_sector", "eia_fuel", "year"], []), False)


EXCHANGE = pd.DataFrame({"CAD": [1.0, 1.0], "USD": [1.25, 1.2]}, index=[2020, 2024])
INFLATION = pd.DataFrame({"gdp_deflator": [1.0, 0.9]}, index=[2020, 2024])


class TestPriceConversion:
    def test_converts_mmbtu_to_gj_and_usd_to_model_cad(self):
        factor = price_conversion_factor(
            "USD", 2024, "$/MMBtu", 2020, EXCHANGE, INFLATION, False
        )
        assert factor == pytest.approx(1.2 * 0.9 / 1.055056)

    def test_previous_module_multiplies_by_the_fixed_factors(self):
        factor = price_conversion_factor(
            "USD", 2024, "$/MMBtu", 2020, EXCHANGE, INFLATION, True
        )
        assert factor == pytest.approx(1.055 * 1.22 * 0.877689699)

    def test_previous_module_only_gives_2020_dollars(self):
        with pytest.raises(ValueError, match="gives 2020 CAD"):
            price_conversion_factor(
                "USD", 2024, "$/MMBtu", 2022, EXCHANGE, INFLATION, True
            )

    def test_converts_each_row_from_its_own_currency(self, tmp_path: Path):
        table = read_price_table(
            _csv(
                tmp_path,
                "ON,COM,NG,2030,1.0,USD,2024,$/MMBtu\nON,IND,NG,2030,1.0,CAD,2020,$/GJ",
            )
        )
        converted = convert_to_model_units(table, 2020, EXCHANGE, INFLATION, False)
        assert list(converted["price"]) == [
            pytest.approx(1.2 * 0.9 / 1.055056),
            pytest.approx(1.0),
        ]
        assert set(converted["units"]) == {"$/GJ"}

    def test_unknown_units_name_the_source(self, tmp_path: Path):
        table = read_price_table(
            _csv(
                tmp_path,
                "ON,COM,NG,2030,1.0,CAD,2020,$/kWh,my series",
                header=f"{_HEADER},source",
            )
        )
        with pytest.raises(ValueError, match="my series: Unknown price units"):
            convert_to_model_units(table, 2020, EXCHANGE, INFLATION, False)


_HEADER = "region,sector,fuel,year,price,currency,currency_year,units"


def _csv(tmp_path: Path, rows: str, header: str = _HEADER) -> Path:
    path = tmp_path / "prices.csv"
    path.write_text(f"{header}\n{rows}\n")
    return path


class TestPriceFile:
    def test_reads_codes_and_names_in_any_format(self, tmp_path: Path):
        table = read_price_table(
            _csv(
                tmp_path,
                "ON,COM,NG,2030,9.5,CAD,2023,$/GJ\n"
                + "Nova Scotia,commercial,natural gas,2030,9.5,CAD,2023,$/GJ",
            )
        )
        assert list(zip(table["region"], table["sector"], table["fuel"])) == [
            (ON, CANOESector.Commercial, NG),
            (NS, CANOESector.Commercial, NG),
        ]
        assert list(table["source"]) == ["prices.csv", "prices.csv"]

    def test_lists_every_row_that_cannot_be_read(self, tmp_path: Path):
        path = _csv(
            tmp_path,
            "ON,COM,kerosene,2030,9.5,CAD,2023,$/GJ\n"
            + "ON,COM,NG,2030,cheap,CAD,2023,$/GJ\n"
            + "ON,,NG,2030,9.5,CAD,2023,$/GJ",
        )
        with pytest.raises(ValueError) as error:
            read_price_table(path)
        message = str(error.value)
        assert "line 2: Unknown fuel 'kerosene'" in message
        assert "line 3:" in message
        assert "line 4: empty sector" in message

    def test_rejects_missing_and_unknown_columns(self, tmp_path: Path):
        path = _csv(tmp_path, "ON,COM,NG,9.5", header="region,sector,fuel,cost")
        with pytest.raises(ValueError, match="missing columns .*'price'.*unknown"):
            read_price_table(path)

    def test_rejects_prices_given_twice(self, tmp_path: Path):
        path = _csv(
            tmp_path,
            "ON,COM,NG,2030,9.5,CAD,2023,$/GJ\nOntario,C,NaturalGas,2030,9.0,CAD,2023,$/GJ",
        )
        with pytest.raises(ValueError, match="prices given twice"):
            check_price_table(read_price_table(path), "file")

    def test_empty_region_and_year_apply_to_all(self, tmp_path: Path):
        table = read_price_table(_csv(tmp_path, ",COM,NG,,9.5,CAD,2023,$/GJ"))
        expanded = expand_price_table(table, [ON, NS], [2030, 2035])
        assert len(expanded) == 4
        assert set(expanded["region"]) == {ON, NS}
        assert set(expanded["year"]) == {2030, 2035}

    def test_empty_rows_cannot_overlap_explicit_ones(self, tmp_path: Path):
        table = read_price_table(
            _csv(
                tmp_path,
                ",COM,NG,2030,9.5,CAD,2023,$/GJ\nON,COM,NG,2030,9.0,CAD,2023,$/GJ",
            )
        )
        with pytest.raises(ValueError, match="Prices given twice"):
            expand_price_table(table, [ON, NS], [2030])

    def test_leaves_out_other_provinces(self, tmp_path: Path):
        table = read_price_table(_csv(tmp_path, "AB,COM,NG,2030,9.5,CAD,2023,$/GJ"))
        assert expand_price_table(table, [ON], [2030]).empty


def _priced(
    rows: list[tuple[CANOEProvince, CANOESector, int, float]], source: str
) -> pd.DataFrame:
    """Prices in the model units, as given to `canoe.fuel.prices`."""
    return pd.DataFrame(
        [
            {
                "region": r,
                "sector": s,
                "fuel": NG,
                "year": y,
                "price": p,
                "currency": "CAD",
                "currency_year": 2020,
                "units": "$/GJ",
                "source": source,
            }
            for r, s, y, p in rows
        ]
    )


class TestCombine:
    regional: pd.DataFrame = _priced(
        [(ON, CANOESector.Commercial, 2030, 9.0)], "regional"
    )
    national: pd.DataFrame = _priced(
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
    prices = _priced([(ON, CANOESector.Commercial, 2030, 9.0)], "")
    with pytest.raises(ValueError, match=r"commercial natural gas \(NS\)"):
        check_price_coverage(
            [CANOEFuelImport(CANOESector.Commercial, NG, (NS, ON))], prices, "error"
        )
    supplied = check_price_coverage(
        [CANOEFuelImport(CANOESector.Commercial, NG, (NS, ON))], prices, "warning"
    )
    assert [i.provinces for i in supplied] == [(ON,)]


PRICES = _priced(
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

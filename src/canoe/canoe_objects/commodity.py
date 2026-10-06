"""
Fuel and source commodities.

Examples in this module run against `db`, an in-memory CANOE database prepared in
`canoe_objects/conftest.py` (data sets `COMDOC*`).
"""

from sqlite3 import Connection

from canoe_schema.v4_0 import Commodity, CommodityTypeCode

from canoe.common import CANOEFuel, CANOESector
from canoe.common.db_tools import write_label
from canoe.common.naming import DatasetIdentifier, get_fuel_commodity_in_sector


class FuelCommodityEntity:
    """
    A fuel as consumed by a sector, e.g. natural gas in the commercial sector (`C_ng`).

    Technologies take these commodities as inputs, so they must be built before the
    technologies that use them. Building the same fuel twice is harmless (insert or
    ignore).

    Parameters
    ----------
    sector : CANOESector
        Sector consuming the fuel.
    fuel : CANOEFuel
        The fuel.
    flag : CommodityTypeCode
        Commodity type, e.g. physical (`p`) for electricity and annual (`a`) for
        fuels whose supply is balanced over the year.
    data_id : DatasetIdentifier
        Data set of the `commodity` row (sector-wide, no region).
    units : str
        Units of the commodity, PJ by default (fuel flows are energy).

    Examples
    --------
    >>> from canoe.common.naming import DatasetIdentifier
    >>> natural_gas = FuelCommodityEntity(
    ...     sector=CANOESector.Commercial,
    ...     fuel=CANOEFuel.NaturalGas,
    ...     flag=CommodityTypeCode.A,
    ...     data_id=DatasetIdentifier(CANOESector.Commercial, "DOC", "001"),
    ... )
    >>> natural_gas.name
    'C_ng'
    >>> natural_gas.build(db)
    >>> db.execute(
    ...     "SELECT name, flag, description, units, data_id FROM commodity"
    ... ).fetchall()
    [('C_ng', 'a', 'natural gas fuel for Commercial sector', 'PJ', 'COMDOC001')]
    """

    def __init__(
        self,
        sector: CANOESector,
        fuel: CANOEFuel,
        flag: CommodityTypeCode,
        data_id: DatasetIdentifier,
        units: str = "PJ",
    ) -> None:
        self.sector: CANOESector = sector
        self.fuel: CANOEFuel = fuel
        self.flag: CommodityTypeCode = flag
        self.data_id: DatasetIdentifier = data_id
        self.units: str = units

    @property
    def name(self) -> str:
        """Commodity name, see `get_fuel_commodity_in_sector`"""
        return get_fuel_commodity_in_sector(self.sector, self.fuel)

    def build(self, db_conn: Connection):
        """
        Write the `commodity` row and its `commodity_label`.

        Parameters
        ----------
        db_conn : Connection
            Open connection; the caller manages the transaction.
        """
        commodity = Commodity(
            name=self.name,
            flag=self.flag,
            description=f"{self.fuel.get_desc_name()} fuel for {self.sector.name} sector",
            units=self.units,
            data_id=self.data_id.get_dataset_code(),
        )
        sql, params = Commodity.to_insert_or_ignore_sql(commodity)
        write_label(db_conn, commodity)
        db_conn.execute(sql, params)


class SourceCommodityEntity:
    """
    A source commodity (flag `s`): the starting point of supply chains, e.g. the
    `F_ethos` the fuel imports take as input. Temoa's source trace starts from these
    commodities.

    Technologies take it as input, so it must be built before them. Building it
    twice is harmless (insert or ignore).

    Parameters
    ----------
    name : str
        Commodity name.
    description : str
        Description in the `commodity` table.
    data_id : DatasetIdentifier
        Data set of the `commodity` row (sector-wide, no region).
    units : str, optional
        Units of the commodity, e.g. PJ for the supply point of fuels.

    Examples
    --------
    >>> from canoe.common.naming import DatasetIdentifier
    >>> SourceCommodityEntity(
    ...     name="C_ethos",
    ...     description="supply point of the commercial fuels",
    ...     data_id=DatasetIdentifier(CANOESector.Commercial, "DOC", "001"),
    ...     units="PJ",
    ... ).build(db)
    >>> db.execute(
    ...     "SELECT name, flag, description, units, data_id FROM commodity"
    ... ).fetchall()
    [('C_ethos', 's', 'supply point of the commercial fuels', 'PJ', 'COMDOC001')]
    """

    def __init__(
        self,
        name: str,
        description: str,
        data_id: DatasetIdentifier,
        units: str | None = None,
    ) -> None:
        self.name: str = name
        self.description: str = description
        self.data_id: DatasetIdentifier = data_id
        self.units: str | None = units

    def build(self, db_conn: Connection):
        """
        Write the `commodity` row and its `commodity_label`.

        Parameters
        ----------
        db_conn : Connection
            Open connection; the caller manages the transaction.
        """
        commodity = Commodity(
            name=self.name,
            flag=CommodityTypeCode.S,
            description=self.description,
            units=self.units,
            data_id=self.data_id.get_dataset_code(),
        )
        sql, params = Commodity.to_insert_or_ignore_sql(commodity)
        write_label(db_conn, commodity)
        db_conn.execute(sql, params)

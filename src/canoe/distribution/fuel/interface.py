from sqlite3 import Connection

from canoe_schema.v4_0 import Commodity

from canoe.common import CANOEFuel
from canoe.distribution.fuel import CANOEFuelDistributionConfig


# def register_fuels(
#     fuels: list[CANOEFuel] | CANOEFuel,
#     distribution_config: CANOEFuelDistributionConfig,
#     conn: Connection,
# ) -> bool:
#     """
#     Register fuel commodities in commodity and commodity label tables
#     """

#     fuel_list: list[CANOEFuel] = [fuels] if isinstance(fuels, CANOEFuel) else fuels
#     for fuel in fuel_list:
#         # write label
#         commodity = Commodity(
#             name=
#         )
#         write_label(conn, )
#         ...
#     return True

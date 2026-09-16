import pytest

from canoe.common.fuels import CANOEFuel


class TestFromStr:
    # --- Value string matches (e.g. CANOE codes) ---

    def test_value_exact(self):
        assert CANOEFuel.from_str("ELC") == CANOEFuel.Electricity

    def test_value_diesel(self):
        assert CANOEFuel.from_str("DSL") == CANOEFuel.Diesel

    def test_value_compressed_natural_gas(self):
        assert CANOEFuel.from_str("CNG") == CANOEFuel.CompressedNaturalGas

    def test_all_members_by_value(self):
        for fuel in CANOEFuel:
            assert CANOEFuel.from_str(fuel.value) == fuel

    # --- Member name matches ---

    def test_name_exact(self):
        assert CANOEFuel.from_str("Electricity") == CANOEFuel.Electricity

    def test_name_lowercase(self):
        assert CANOEFuel.from_str("electricity") == CANOEFuel.Electricity

    def test_name_uppercase(self):
        assert CANOEFuel.from_str("ELECTRICITY") == CANOEFuel.Electricity

    def test_name_camel_case(self):
        assert CANOEFuel.from_str("NaturalGas") == CANOEFuel.NaturalGas

    def test_all_members_by_name(self):
        for fuel in CANOEFuel:
            assert CANOEFuel.from_str(fuel.name) == fuel

    # --- Space / separator normalisation ---

    def test_name_with_spaces(self):
        assert CANOEFuel.from_str("natural gas") == CANOEFuel.NaturalGas

    def test_name_with_spaces_title_case(self):
        assert CANOEFuel.from_str("Natural Gas") == CANOEFuel.NaturalGas

    def test_name_with_underscores(self):
        assert CANOEFuel.from_str("natural_gas") == CANOEFuel.NaturalGas

    def test_multiword_with_spaces(self):
        assert (
            CANOEFuel.from_str("compressed natural gas")
            == CANOEFuel.CompressedNaturalGas
        )

    def test_multiword_with_mixed_separators(self):
        assert (
            CANOEFuel.from_str("Compressed_Natural_Gas")
            == CANOEFuel.CompressedNaturalGas
        )

    # --- Invalid inputs ---

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            CANOEFuel.from_str("")

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError):
            CANOEFuel.from_str("Unicorn")

    def test_error_message_contains_input(self):
        with pytest.raises(ValueError, match="NotAFuel"):
            CANOEFuel.from_str("NotAFuel")

    def test_partial_match_raises(self):
        # "gas" alone should not match NaturalGas or any other member
        with pytest.raises(ValueError):
            CANOEFuel.from_str("gas")

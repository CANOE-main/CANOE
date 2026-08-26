"""
A set of time slices, expressed either as a shorthand or as an explicit list.

Rust-enum-flavored: each variant is its own model tagged with a `kind`
discriminator, and `CANOETimeSliceSet` is the tagged union of variants —
Pydantic's `Field(discriminator=...)` is what plays the role of Rust's
`enum Foo { A(...), B(...) }` here, dispatching on `kind` the way Rust
dispatches on the variant tag.

To add a new way of specifying slices (e.g. "one per day of the week"),
add a variant model below and extend the union — nothing else needs to
change for it to become a legal `CANOETimeSliceSet`.
"""

from abc import ABC, abstractmethod
from typing import Annotated, ClassVar, Literal, override

from pydantic import BaseModel, Field


def hour_to_tod(hour: int) -> str:
    return f"H{(hour%24)+1:02d}"


def hour_to_day(hour: int) -> str:
    return f"D{(hour//24)+1:03d}"


class TimeSlice(BaseModel):
    hour: int
    season: str
    tod: str

    HOURS_PER_YEAR: ClassVar[int] = 8760

    @classmethod
    def all_year(cls) -> list["TimeSlice"]:
        return [cls(hour=h, season=hour_to_day(h), tod=hour_to_tod(h)) for h in range(cls.HOURS_PER_YEAR)]


class TimeSliceSetVariant(BaseModel, ABC):  # pyright: ignore[reportUnsafeMultipleInheritance]
    """Base of every `CANOETimeSliceSet` variant.

    Forces each variant to implement `as_list`, the same way a Rust trait
    forces every `impl` to define its methods — a variant missing it fails
    to instantiate rather than failing at first use.
    """

    @abstractmethod
    def as_list(self) -> list[TimeSlice]: ...


class AllTimeSlices(TimeSliceSetVariant):
    """Every hour of the year, 1..HOURS_PER_YEAR."""

    kind: Literal["all_year"] = "all_year"

    @override
    def as_list(self) -> list[TimeSlice]:
        return TimeSlice.all_year()


class SpecificTimeSlices(TimeSliceSetVariant):
    """An explicit, user-provided list of hours."""

    kind: Literal["specific"] = "specific"
    slices: list[TimeSlice]

    @override
    def as_list(self) -> list[TimeSlice]:
        return self.slices


# Add new variants here as they're implemented, e.g.:
CANOETimeSliceSet = Annotated[
    AllTimeSlices | SpecificTimeSlices,
    Field(discriminator="kind"),
]

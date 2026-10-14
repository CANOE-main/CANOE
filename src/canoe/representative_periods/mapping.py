"""
The result of a clustering: the season that represents each season of a database.

This is all the apply step needs from a clustering. Weights, segment fractions and
the chronological sequence follow from the mapping and the seasons of the database
it is applied to; nothing about how the clustering was found is kept here.
"""

from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, model_validator


class RepresentativeSeasonMapping(BaseModel):
    """
    The season that represents each season of a database.

    Keys and values are seasons of the database (days, e.g. `D001`). A representative
    always represents itself. Seasons left out of the mapping are not represented
    (e.g. days missing from the clustering's time series).

    The order of the mapping means nothing: methods that return seasons in order take
    the seasons of the database, in chronological order.

    Examples
    --------
    >>> mapping = RepresentativeSeasonMapping(
    ...     representative_of={"D003": "D003", "D001": "D003", "D002": "D002"}
    ... )
    >>> mapping.representatives(["D001", "D002", "D003"])
    ['D002', 'D003']
    >>> mapping.weights(["D001", "D002", "D003"])
    {'D002': 1, 'D003': 2}
    """

    model_config = ConfigDict(frozen=True, use_attribute_docstrings=True)  # pyright: ignore[reportUnannotatedClassAttribute]

    representative_of: dict[str, str]
    """Season -> the season that represents it."""

    @model_validator(mode="after")
    def _check_representatives(self) -> "RepresentativeSeasonMapping":
        if not self.representative_of:
            raise ValueError("The mapping has no seasons")
        not_self = sorted(
            {
                rep
                for rep in self.representative_of.values()
                if self.representative_of.get(rep) != rep
            }
        )
        if not_self:
            raise ValueError(
                f"Representatives must represent themselves, these do not: {not_self}"
            )
        return self

    def representatives(self, seasons: Sequence[str]) -> list[str]:
        """
        The representative seasons, in the order of `seasons`.

        Parameters
        ----------
        seasons
            Every season of the database, in chronological order. Must include every
            season of the mapping.
        """
        unknown = sorted(set(self.representative_of) - set(seasons))
        if unknown:
            raise ValueError(
                f"Seasons of the mapping not in the given seasons: {unknown}"
            )
        return [s for s in seasons if self.representative_of.get(s) == s]

    def weights(self, seasons: Sequence[str]) -> dict[str, int]:
        """
        Number of seasons each representative stands for (itself included), in the
        order of `seasons` (see `representatives`).
        """
        counts = Counter(self.representative_of.values())
        return {rep: counts[rep] for rep in self.representatives(seasons)}

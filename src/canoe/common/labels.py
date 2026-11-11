"""
Matching of free-form labels (from user files, configs, other sources) to CANOE
enums, used by their `from_str` (e.g. `CANOEFuel.from_str`).

Labels are compared normalized: case-insensitive, letters and digits only, so
`"Natural gas"`, `"natural_gas"`, `"NATURAL-GAS"` and `"NaturalGas"` are the same.
"""

from enum import Enum


def normalize_label(text: str) -> str:
    """
    `text` lowercase, with letters and digits only.

    Examples
    --------
    >>> normalize_label("Liquefied petroleum gas (LPG)")
    'liquefiedpetroleumgaslpg'
    """
    return "".join(c for c in text.casefold() if c.isalnum())


def match_label[E: Enum](text: str, labels: dict[E, list[str]], kind: str) -> E:
    """
    The member of `labels` one of whose labels matches `text` (see
    `normalize_label`).

    params:
    - labels: the labels each member is known by; the first one is shown in errors
    - kind: what the members are, for errors (e.g. `"fuel"`)

    Raises
    ------
    ValueError
        If no label matches `text`.
    AssertionError
        If a label names two members (a mistake in `labels`).
    """
    by_label: dict[str, E] = {}
    for member, member_labels in labels.items():
        for label in member_labels:
            named = by_label.setdefault(normalize_label(label), member)
            assert named == member, f"{kind} label {label!r} names {named} and {member}"
    key = normalize_label(text)
    if key not in by_label:
        raise ValueError(
            f"Unknown {kind} {text!r}; expected a code or name such as "
            + ", ".join(member_labels[0] for member_labels in labels.values())
        )
    return by_label[key]

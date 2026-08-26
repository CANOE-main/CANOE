"""
Lets a config field say "inherit this from `base` if I'm not set".

A sector config declares an inheritable field like:

    future_periods: list[int] = inherit()

If the TOML sets the field, it's validated as a normal `list[int]`. If it's
left out (or explicitly set to `"inherited"`), `InheritsFromBase` fills it in
from `base` in a `model_validator(mode="before")` — before per-field
validation runs. That means the field keeps its real declared type
everywhere: on the model, and at every place that reads it.
"""

from collections.abc import Callable
from enum import Enum
from typing import Any, ClassVar, TypeVar, cast, override

from pydantic import BaseModel, ValidationInfo, model_validator


class Inherited(str, Enum):
    """Sentinel marking a field as 'take this value from `base`'."""

    TOKEN = "inherited"

    @override
    def __repr__(self) -> str:
        return "Inherited.TOKEN"


_T = TypeVar("_T")


def inherit() -> _T:  # pyright: ignore[reportInvalidTypeVarUse]
    """Default for a field that inherits from `base` when left unset.

    Statically typed as the field's own annotation (`str`, `Path`,
    `list[int]`, ...) so callers never see `Inherited` — only
    `InheritsFromBase` ever looks at the real runtime value, which is the
    `Inherited.TOKEN` sentinel. Pydantic doesn't validate class-level
    defaults, so the sentinel is never checked against the declared type.
    """
    return cast(_T, Inherited.TOKEN)


class InheritsFromBase(BaseModel):
    """Mixin: resolves fields left as `Inherited.TOKEN` against a `base` config.

    Subclasses may override `_INHERIT_RESOLVERS` to say *how* a field is
    derived from `base` (e.g. a rename, a unit conversion, a derived list).
    Fields with no entry there fall back to `getattr(base, field_name)` —
    i.e. "same name, copied as-is".

    `base` must be supplied via validation context:
        SomeConfig.model_validate(raw, context={"base": base_config})
    """

    _INHERIT_RESOLVERS: ClassVar[dict[str, Callable[[Any], Any]]] = {}

    @model_validator(mode="before")
    @classmethod
    def _resolve_inherited_fields(cls, data: Any, info: ValidationInfo) -> Any:  # pyright: ignore[reportRedeclaration]
        if not isinstance(data, dict):
            return data
        data: dict[str, Any] = data  # pyright: ignore[reportUnknownVariableType]  # noqa: PLW0127

        pending = [
            name
            for name, field in cls.model_fields.items()
            if field.default is Inherited.TOKEN
            and data.get(name, Inherited.TOKEN.value) == Inherited.TOKEN.value
        ]
        if not pending:
            return data

        base = (info.context or {}).get("base")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if base is None:
            raise ValueError(
                f"{cls.__name__} has mandatory fields missing "  # pyright: ignore[reportImplicitStringConcatenation]
                f"[{', '.join(pending)}]"
            )

        for name in pending:
            resolver = cls._INHERIT_RESOLVERS.get(name)
            if resolver is not None:
                data[name] = resolver(base)
            elif hasattr(base, name):  # pyright: ignore[reportUnknownArgumentType]
                data[name] = getattr(base, name)  # pyright: ignore[reportUnknownArgumentType]
            else:
                raise ValueError(
                    f"Cannot inherit '{name}': base config has no attribute "  # pyright: ignore[reportImplicitStringConcatenation]
                    f"'{name}' and {cls.__name__} defines no resolver "
                    "for it in _INHERIT_RESOLVERS."
                )

        return data

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _OpBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class RenameColumn(_OpBase):
    kind: Literal["rename"]
    from_: str = Field(alias="from")
    to: str


class CoerceType(_OpBase):
    kind: Literal["coerce_type"]
    column: str
    to: Literal["int", "float", "bool", "string", "date", "datetime"]


class ParseDate(_OpBase):
    kind: Literal["parse_date"]
    column: str
    format: str


class DropNulls(_OpBase):
    kind: Literal["drop_nulls"]
    columns: list[str]


class FillNull(_OpBase):
    kind: Literal["fill_null"]
    column: str
    value: str | int | float | bool


class Trim(_OpBase):
    kind: Literal["trim"]
    column: str


class Lowercase(_OpBase):
    kind: Literal["lowercase"]
    column: str


Operation = Annotated[
    RenameColumn | CoerceType | ParseDate | DropNulls | FillNull | Trim | Lowercase,
    Field(discriminator="kind"),
]

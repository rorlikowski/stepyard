"""Internal helpers for attaching Stepyard metadata to callables."""

from __future__ import annotations

from typing import Any, TypeVar, cast

from pydantic import BaseModel

F = TypeVar("F")


def stamp_node(
    func: F,
    name: str,
    metadata: dict[str, Any],
    input_model: type[BaseModel],
) -> F:
    stamped = cast(Any, func)
    stamped.__stepyard_node__ = True
    stamped.__stepyard_name__ = name
    stamped.__stepyard_metadata__ = metadata
    stamped.__stepyard_input_model__ = input_model
    return cast(F, stamped)


def stamp_trigger(func: F, name: str, input_model: type[BaseModel]) -> F:
    stamped = cast(Any, func)
    stamped.__stepyard_trigger__ = True
    stamped.__stepyard_name__ = name
    stamped.__stepyard_input_model__ = input_model
    return cast(F, stamped)


def stamp_input_collector(func: F, node_name: str) -> F:
    stamped = cast(Any, func)
    stamped.__stepyard_input_collector__ = node_name
    return cast(F, stamped)

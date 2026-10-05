"""mmth: multiple dispatch for Python, inspired by Julia."""

from mmth.multimethod import Multimethod, dispatch, dispatchmethod, inherit
from mmth.typemap import (
    AmbiguousMatchError,
    ChainTypeMap,
    NoMatchError,
    TypeMap,
)

__all__ = [
    "dispatch",
    "Multimethod",
    "dispatchmethod",
    "inherit",
    "TypeMap",
    "ChainTypeMap",
    "NoMatchError",
    "AmbiguousMatchError",
]

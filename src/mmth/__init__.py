"""mmth: multiple dispatch for Python, inspired by Julia."""

from mmth.multimethod import Multimethod, dispatch, dispatchmethod, inherit
from mmth.typemap import AmbiguousMatchError, NoMatchError, TypeMap

__all__ = [
    "dispatch",
    "Multimethod",
    "dispatchmethod",
    "inherit",
    "TypeMap",
    "NoMatchError",
    "AmbiguousMatchError",
]

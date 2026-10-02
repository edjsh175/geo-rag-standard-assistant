"""Narrow compatibility helpers used while orchestration is being decomposed."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Mapping


def supported_kwargs(
    callable_obj: Callable[..., Any],
    kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Filter optional kwargs for legacy test doubles without hiding call errors."""

    signature = inspect.signature(callable_obj)
    parameters = signature.parameters
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
        return dict(kwargs)
    return {key: value for key, value in kwargs.items() if key in parameters}


__all__ = ["supported_kwargs"]

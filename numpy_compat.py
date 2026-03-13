from __future__ import annotations


def ensure_numpy_legacy_aliases() -> None:
    try:
        import numpy as np
    except ImportError:
        return

    legacy_aliases = {
        "short": "int16",
        "ushort": "uint16",
        "uint": "uint64",
        "single": "float32",
        "double": "float64",
        "cfloat": "complex128",
        "cdouble": "complex128",
        "clongdouble": "clongdouble",
    }

    for alias, target in legacy_aliases.items():
        if hasattr(np, alias):
            continue
        replacement = getattr(np, target, None)
        if replacement is not None:
            setattr(np, alias, replacement)

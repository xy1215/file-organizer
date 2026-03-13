from __future__ import annotations

import sys
from pathlib import Path


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_resource_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def app_path(*parts: str) -> Path:
    return get_app_dir().joinpath(*parts)


def resource_path(*parts: str) -> Path:
    return get_resource_dir().joinpath(*parts)

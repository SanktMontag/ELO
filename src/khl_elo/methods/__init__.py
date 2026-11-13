"""Rating methods. Each is selected by name and configured by config/methods/<name>.toml."""

from __future__ import annotations

from ..config import load_method_config
from .base import Method
from .legacy_v0 import LegacyV0
from .v1 import V1
from .v2_dev import V2Dev

REGISTRY: dict[str, type[Method]] = {
    "legacy-v0": LegacyV0,
    "v1": V1,
    "v2-dev": V2Dev,
}


def get_method(name: str, overrides: dict | None = None) -> Method:
    if name not in REGISTRY:
        raise KeyError(f"Unknown method {name!r}; choose from {sorted(REGISTRY)}")
    cfg = load_method_config(name)
    if overrides:
        cfg = {**cfg, **overrides}
    return REGISTRY[name](cfg)

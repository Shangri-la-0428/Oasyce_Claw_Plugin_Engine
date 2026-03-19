"""Shared utility helpers for the Oasyce thin-client."""

from __future__ import annotations

OAS_DECIMALS = 8


def to_units(oas: float) -> int:
    """Convert OAS (float) to integer units (1 OAS = 10^8 units)."""
    return int(oas * 10**OAS_DECIMALS)


def from_units(units: int) -> float:
    """Convert integer units back to OAS."""
    return units / 10**OAS_DECIMALS

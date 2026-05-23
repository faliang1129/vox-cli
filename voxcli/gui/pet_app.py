"""Backward-compatible desktop pet entrypoint."""

from __future__ import annotations

from .pet import PetCoordinator, run_pet_app

__all__ = ["PetCoordinator", "run_pet_app"]

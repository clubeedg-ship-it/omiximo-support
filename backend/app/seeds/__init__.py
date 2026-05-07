"""Seed data package for Omiximo Support.

Each module exposes a single async function that accepts an AsyncSession and
inserts the relevant reference data. Seed functions are idempotent: they skip
rows that already exist based on a natural key check.
"""

from app.seeds.templates import seed_templates

__all__ = ["seed_templates"]

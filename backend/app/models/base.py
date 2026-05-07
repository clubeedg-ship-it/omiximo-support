"""Declarative base shared by all ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-wide SQLAlchemy declarative base.

    All models inherit from this class. The metadata attached here is the
    single source of truth for Alembic autogenerate.
    """

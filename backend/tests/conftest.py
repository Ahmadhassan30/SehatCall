"""
Shared pytest configuration for DAWA P0-A tests.
"""
import pytest


# Use asyncio as the default async backend for pytest-asyncio
pytest_plugins = ("anyio",)

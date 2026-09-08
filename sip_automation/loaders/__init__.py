"""
Source data loaders.

Loaders retrieve source datasets and return pandas DataFrames without
performing mappings, cleaning, validation, transformations, or database
writes.
"""

from sip_automation.loaders.base_loader import BaseLoader, LoadResult
from sip_automation.loaders.loader_factory import LoaderFactory

__all__ = [
    "BaseLoader",
    "LoadResult",
    "LoaderFactory",
]
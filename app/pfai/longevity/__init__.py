"""Longevity foundation package — scaffolds for 20–30 year platform evolution.

PHASE 1 delivers contracts + these non-wired scaffolds only.
Existing FastAPI/Dashboard/features remain the runtime surface.
"""

from .provider_registry import ProviderRegistry
from .safe_learning import SafeLearningPipeline
from .migration_runner import MigrationRunner
from .versioned_store import InMemoryVersionedStore
from .export_bundle import ExportBundleScaffold
from .compat_layer import CompatibilityLayer

__all__ = [
    "ProviderRegistry",
    "SafeLearningPipeline",
    "MigrationRunner",
    "InMemoryVersionedStore",
    "ExportBundleScaffold",
    "CompatibilityLayer",
]

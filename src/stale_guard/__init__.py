"""stale-guard -- tell whether data is fresh, not merely rewritten."""

from stale_guard.core import (
    LayerResult,
    Report,
    Source,
    Status,
    check,
)

__all__ = ["LayerResult", "Report", "Source", "Status", "check"]
__version__ = "0.1.0"

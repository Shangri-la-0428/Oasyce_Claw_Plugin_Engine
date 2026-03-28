from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re


def _version_from_local_pyproject() -> str | None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(), re.MULTILINE)
    if not match:
        return None
    return match.group(1)

try:
    __version__ = _version_from_local_pyproject() or version("oasyce")
except PackageNotFoundError:
    __version__ = _version_from_local_pyproject() or "2.3.1"

__all__ = [
    "__version__",
    "AccessLevel",
    "AccessControlConfig",
    "DataAccessProvider",
    "ReputationEngine",
    "ExposureRegistry",
    "LiabilityWindow",
    "OasyceClient",
    "OasyceServiceFacade",
    "ServiceResult",
]

# Data Security & Access Control (§11)
from oasyce.services.access import AccessLevel  # noqa: F401
from oasyce.services.access.config import AccessControlConfig  # noqa: F401
from oasyce.services.access.provider import DataAccessProvider  # noqa: F401
from oasyce.services.reputation import ReputationEngine  # noqa: F401
from oasyce.services.exposure.registry import ExposureRegistry  # noqa: F401
from oasyce.services.exposure.window import LiabilityWindow  # noqa: F401

# Service Facade (unified entry point)
from oasyce.services.facade import OasyceServiceFacade, ServiceResult  # noqa: F401

# Chain client is optional at import time. Formal chain operations still require
# its runtime dependencies, but package import should not fail in local-only flows.
try:
    from oasyce.chain_client import OasyceClient  # noqa: F401
except Exception:  # pragma: no cover - degraded environments should still import the package
    OasyceClient = None  # type: ignore[assignment]

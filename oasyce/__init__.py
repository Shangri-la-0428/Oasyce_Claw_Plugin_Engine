__all__ = ["__version__"]
__version__ = "2.0.0"

# Data Security & Access Control (§11)
from oasyce.services.access import AccessLevel  # noqa: F401
from oasyce.services.access.config import AccessControlConfig  # noqa: F401
from oasyce.services.access.provider import DataAccessProvider  # noqa: F401
from oasyce.services.reputation import ReputationEngine  # noqa: F401
from oasyce.services.exposure.registry import ExposureRegistry  # noqa: F401
from oasyce.services.exposure.window import LiabilityWindow  # noqa: F401

# Core protocol (thin client → Go chain)
from oasyce.chain_client import OasyceClient  # noqa: F401

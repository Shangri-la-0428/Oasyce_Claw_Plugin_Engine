"""
Capability Delivery & Settlement Protocol.

Enables providers to list AI capabilities (with API endpoints),
and consumers to invoke them through an escrow-protected pipeline:

  Provider registers:  endpoint_url + encrypted_api_key + pricing
  Consumer invokes:    lock_escrow → proxy_call → verify_quality → settle

Modules:
  registry   — CapabilityEndpoint registration & encrypted key storage
  gateway    — InvocationGateway proxies calls to provider endpoints
  escrow     — EscrowLedger locks/releases funds atomically
  settlement — SettlementProtocol ties it all together
"""

from oasyce_plugin.services.capability_delivery.registry import (
    CapabilityEndpoint,
    EndpointRegistry,
)
from oasyce_plugin.services.capability_delivery.gateway import (
    InvocationGateway,
    InvocationResult,
)
from oasyce_plugin.services.capability_delivery.escrow import (
    EscrowLedger,
    EscrowEntry,
    EscrowStatus,
)
from oasyce_plugin.services.capability_delivery.settlement import (
    SettlementProtocol,
    InvocationRecord,
    InvocationStatus,
)

__all__ = [
    "CapabilityEndpoint", "EndpointRegistry",
    "InvocationGateway", "InvocationResult",
    "EscrowLedger", "EscrowEntry", "EscrowStatus",
    "SettlementProtocol", "InvocationRecord", "InvocationStatus",
]

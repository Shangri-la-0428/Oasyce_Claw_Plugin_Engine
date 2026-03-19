"""Settlement module proto type stubs.

These dataclasses mirror the protobuf messages defined in the Go chain's
proto/oasyce/settlement/v1/ directory. They are used by chain_client.py
for request/response validation until buf-generated betterproto classes
replace them.
"""

from dataclasses import dataclass


@dataclass
class MsgCreateEscrow:
    buyer: str = ""
    seller: str = ""
    amount: str = ""
    asset_id: str = ""


@dataclass
class MsgReleaseEscrow:
    escrow_id: str = ""
    sender: str = ""


@dataclass
class Escrow:
    id: str = ""
    buyer: str = ""
    seller: str = ""
    amount: str = ""
    asset_id: str = ""
    status: str = ""

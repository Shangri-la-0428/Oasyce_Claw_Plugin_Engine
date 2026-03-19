"""Data rights module proto type stubs.

These dataclasses mirror the protobuf messages defined in the Go chain's
proto/oasyce/datarights/v1/ directory. They are used by chain_client.py
for request/response validation until buf-generated betterproto classes
replace them.
"""

from dataclasses import dataclass


@dataclass
class MsgRegisterDataAsset:
    creator: str = ""
    name: str = ""
    fingerprint: str = ""
    rights_type: str = ""
    tags: str = ""
    description: str = ""


@dataclass
class MsgBuyShares:
    buyer: str = ""
    asset_id: str = ""
    amount: str = ""


@dataclass
class DataAsset:
    id: str = ""
    creator: str = ""
    name: str = ""
    fingerprint: str = ""
    rights_type: str = ""
    tags: str = ""
    description: str = ""
    total_shares: str = ""
    price: str = ""
    status: str = ""

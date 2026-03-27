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
    description: str = ""
    content_hash: str = ""
    fingerprint: str = ""
    rights_type: str = ""
    tags: str = ""
    service_url: str = ""


@dataclass
class MsgBuyShares:
    buyer: str = ""
    asset_id: str = ""
    amount: str = ""


@dataclass
class MsgUpdateServiceUrl:
    creator: str = ""
    asset_id: str = ""
    service_url: str = ""


@dataclass
class MsgUpdateServiceUrlResponse:
    pass


@dataclass
class DataAsset:
    id: str = ""
    owner: str = ""
    name: str = ""
    description: str = ""
    content_hash: str = ""
    fingerprint: str = ""
    rights_type: str = ""
    tags: str = ""
    total_shares: str = ""
    status: str = ""
    parent_asset_id: str = ""
    version: int = 1
    service_url: str = ""

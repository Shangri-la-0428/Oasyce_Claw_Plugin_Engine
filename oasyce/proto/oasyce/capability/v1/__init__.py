"""Capability module proto type stubs.

These dataclasses mirror the protobuf messages defined in the Go chain's
proto/oasyce/capability/v1/ directory. They are used by chain_client.py
for request/response validation until buf-generated betterproto classes
replace them.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class MsgRegisterCapability:
    creator: str = ""
    name: str = ""
    endpoint: str = ""
    price: str = ""
    tags: str = ""
    description: str = ""


@dataclass
class MsgInvokeCapability:
    sender: str = ""
    capability_id: str = ""
    input_data: str = ""


@dataclass
class Capability:
    id: str = ""
    creator: str = ""
    name: str = ""
    endpoint: str = ""
    price: str = ""
    tags: str = ""
    description: str = ""
    status: str = ""
    invocation_count: int = 0

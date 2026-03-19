"""Reputation module proto type stubs.

These dataclasses mirror the protobuf messages defined in the Go chain's
proto/oasyce/reputation/v1/ directory. They are used by chain_client.py
for request/response validation until buf-generated betterproto classes
replace them.
"""

from dataclasses import dataclass


@dataclass
class MsgSubmitFeedback:
    sender: str = ""
    target: str = ""
    score: int = 0
    comment: str = ""
    asset_id: str = ""


@dataclass
class Reputation:
    address: str = ""
    score: int = 0
    total_feedback: int = 0
    positive_feedback: int = 0
    negative_feedback: int = 0

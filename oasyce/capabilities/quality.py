"""Quality Gate — structural validation + auto-settlement for capability outputs.

For deterministic capabilities: validates output against output_schema.
For all: checks output is non-empty and within size limits.
Returns PASS / WARN / FAIL with reasons.
"""

from __future__ import annotations

import enum
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


class QualityVerdict(str, enum.Enum):
    """Quality gate evaluation outcome."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class QualityResult:
    """Result of a quality gate evaluation."""

    invocation_id: str
    verdict: QualityVerdict
    reasons: List[str] = field(default_factory=list)
    evaluated_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class FlagRecord:
    """A flagged invocation awaiting manual review."""

    invocation_id: str
    reason: str
    flagged_at: int = field(default_factory=lambda: int(time.time()))


class QualityError(Exception):
    """Raised on quality gate operation errors."""


# Default size limits
_DEFAULT_MAX_OUTPUT_SIZE = 10_485_760  # 10 MB


class QualityGate:
    """Evaluates capability outputs and triggers optimistic settlement.

    Parameters
    ----------
    get_invocation : callable
        (invocation_id) → invocation record with .capability_id, .output_payload, .state
    get_manifest : callable
        (capability_id) → CapabilityManifest with .output_schema, .quality, .limits
    settle_fn : callable or None
        (invocation_id) → SettlementResult — called on auto-settle (PASS).
    """

    def __init__(
        self,
        get_invocation: Callable[[str], Any],
        get_manifest: Callable[[str], Any],
        settle_fn: Optional[Callable] = None,
    ) -> None:
        self._get_invocation = get_invocation
        self._get_manifest = get_manifest
        self._settle_fn = settle_fn
        self._results: Dict[str, QualityResult] = {}
        self._flags: Dict[str, FlagRecord] = {}

    def evaluate(
        self,
        invocation_id: str,
        output: Dict[str, Any],
        capability_manifest: Any,
    ) -> QualityResult:
        """Evaluate output quality.

        Checks:
            1. Output is non-empty
            2. Output within size limits
            3. For deterministic capabilities: structural schema validation

        Returns:
            QualityResult with verdict and reasons.
        """
        reasons: List[str] = []
        verdict = QualityVerdict.PASS

        # 1. Non-empty check
        if not output:
            reasons.append("output is empty")
            verdict = QualityVerdict.FAIL

        # 2. Size limit check
        if output:
            try:
                output_size = len(json.dumps(output).encode("utf-8"))
            except (TypeError, ValueError):
                output_size = 0
                reasons.append("output is not JSON-serializable")
                verdict = QualityVerdict.FAIL

            max_size = _DEFAULT_MAX_OUTPUT_SIZE
            if capability_manifest is not None and hasattr(capability_manifest, "limits"):
                max_size = getattr(capability_manifest.limits, "max_output_size_bytes", max_size)
            if output_size > max_size:
                reasons.append(f"output size {output_size} exceeds limit {max_size}")
                verdict = QualityVerdict.FAIL

        # 3. Schema validation for deterministic capabilities
        if (
            capability_manifest is not None
            and hasattr(capability_manifest, "quality")
            and getattr(capability_manifest.quality, "verification_type", "") == "deterministic"
        ):
            schema = getattr(capability_manifest, "output_schema", {})
            schema_issues = self._validate_schema(output, schema)
            if schema_issues:
                reasons.extend(schema_issues)
                if verdict == QualityVerdict.PASS:
                    verdict = QualityVerdict.FAIL

        # 4. Warn if output has unexpected structure (non-deterministic)
        if (
            verdict == QualityVerdict.PASS
            and capability_manifest is not None
            and hasattr(capability_manifest, "output_schema")
        ):
            schema = getattr(capability_manifest, "output_schema", {})
            required = schema.get("required", [])
            missing = [k for k in required if k not in output]
            if missing:
                reasons.append(f"missing expected keys: {missing}")
                verdict = QualityVerdict.WARN

        result = QualityResult(
            invocation_id=invocation_id,
            verdict=verdict,
            reasons=reasons,
        )
        self._results[invocation_id] = result
        return result

    def auto_settle(self, invocation_id: str) -> Optional[Any]:
        """Trigger settlement if the quality result is PASS.

        Returns:
            Settlement result if PASS and settle_fn is set, else None.
        """
        result = self._results.get(invocation_id)
        if result is None:
            raise QualityError(f"no quality result for invocation {invocation_id}")
        if result.verdict == QualityVerdict.PASS and self._settle_fn is not None:
            return self._settle_fn(invocation_id)
        return None

    def flag(self, invocation_id: str, reason: str) -> FlagRecord:
        """Flag an invocation for manual review."""
        rec = FlagRecord(invocation_id=invocation_id, reason=reason)
        self._flags[invocation_id] = rec
        return rec

    def get_result(self, invocation_id: str) -> Optional[QualityResult]:
        """Return the quality evaluation result for an invocation."""
        return self._results.get(invocation_id)

    def get_flag(self, invocation_id: str) -> Optional[FlagRecord]:
        """Return the flag record for an invocation, if any."""
        return self._flags.get(invocation_id)

    @staticmethod
    def _validate_schema(
        output: Dict[str, Any],
        schema: Dict[str, Any],
    ) -> List[str]:
        """Structural schema validation for deterministic capabilities.

        Checks required keys and basic type matching against properties.
        """
        issues: List[str] = []
        if not schema:
            return issues

        required = schema.get("required", [])
        missing = [k for k in required if k not in output]
        if missing:
            issues.append(f"missing required keys: {missing}")

        properties = schema.get("properties", {})
        for key, prop in properties.items():
            if key in output:
                expected_type = prop.get("type")
                if expected_type and not _check_type(output[key], expected_type):
                    issues.append(
                        f"key '{key}' expected type '{expected_type}', "
                        f"got {type(output[key]).__name__}"
                    )

        return issues


def _check_type(value: Any, json_type: str) -> bool:
    """Check if a Python value matches a JSON Schema type."""
    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    expected = _TYPE_MAP.get(json_type)
    if expected is None:
        return True  # unknown type, skip
    return isinstance(value, expected)

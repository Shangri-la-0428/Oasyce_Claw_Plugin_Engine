"""Parameter registry — registers governable parameters with type and range constraints.

Each governable parameter has a module, key, type, min/max, and a callable
applier that performs the hot-update when a proposal is executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from oasyce_plugin.consensus.governance.types import UNGOVERNABLE_KEYS


@dataclass
class ParameterSpec:
    """Specification for a single governable parameter."""
    module: str
    key: str
    value_type: Type           # int, float, str, bool
    current_value: Any
    min_value: Any = None      # inclusive lower bound (numeric only)
    max_value: Any = None      # inclusive upper bound (numeric only)
    description: str = ""
    applier: Optional[Callable[[Any], None]] = None  # hot-update callback

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module": self.module,
            "key": self.key,
            "value_type": self.value_type.__name__,
            "current_value": self.current_value,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "description": self.description,
        }


class ParameterRegistry:
    """Registry of governable protocol parameters.

    Register parameters at engine init time, then governance proposals
    validate against this registry before applying changes.
    """

    def __init__(self) -> None:
        self._params: Dict[str, ParameterSpec] = {}  # key = "module.key"

    @staticmethod
    def _fqn(module: str, key: str) -> str:
        return f"{module}.{key}"

    def register(self, module: str, key: str, value_type: Type,
                 current_value: Any, min_value: Any = None,
                 max_value: Any = None, description: str = "",
                 applier: Optional[Callable[[Any], None]] = None) -> None:
        """Register a governable parameter."""
        if key in UNGOVERNABLE_KEYS:
            raise ValueError(f"parameter '{key}' is not governable")
        fqn = self._fqn(module, key)
        self._params[fqn] = ParameterSpec(
            module=module, key=key, value_type=value_type,
            current_value=current_value, min_value=min_value,
            max_value=max_value, description=description,
            applier=applier,
        )

    def get(self, module: str, key: str) -> Optional[ParameterSpec]:
        return self._params.get(self._fqn(module, key))

    def get_current_value(self, module: str, key: str) -> Any:
        spec = self.get(module, key)
        return spec.current_value if spec else None

    def validate_change(self, module: str, key: str,
                        new_value: Any) -> Tuple[bool, str]:
        """Validate a proposed parameter change.

        Returns (True, "") on success, (False, error) on failure.
        """
        if key in UNGOVERNABLE_KEYS:
            return False, f"parameter '{key}' is not governable"

        fqn = self._fqn(module, key)
        spec = self._params.get(fqn)
        if spec is None:
            return False, f"unknown parameter '{fqn}'"

        # Type check
        if not isinstance(new_value, spec.value_type):
            try:
                new_value = spec.value_type(new_value)
            except (ValueError, TypeError):
                return False, (
                    f"type mismatch for '{fqn}': "
                    f"expected {spec.value_type.__name__}, got {type(new_value).__name__}"
                )

        # Range check (numeric)
        if spec.min_value is not None and new_value < spec.min_value:
            return False, f"'{fqn}' value {new_value} below minimum {spec.min_value}"
        if spec.max_value is not None and new_value > spec.max_value:
            return False, f"'{fqn}' value {new_value} above maximum {spec.max_value}"

        return True, ""

    def apply_change(self, module: str, key: str, new_value: Any) -> bool:
        """Apply a parameter change — updates current_value and calls applier.

        Returns True if successful.
        """
        fqn = self._fqn(module, key)
        spec = self._params.get(fqn)
        if spec is None:
            return False

        # Coerce type
        if not isinstance(new_value, spec.value_type):
            new_value = spec.value_type(new_value)

        spec.current_value = new_value
        if spec.applier is not None:
            spec.applier(new_value)
        return True

    def list_parameters(self, module: Optional[str] = None) -> List[ParameterSpec]:
        """List all registered parameters, optionally filtered by module."""
        specs = list(self._params.values())
        if module:
            specs = [s for s in specs if s.module == module]
        return specs

    def to_dict_list(self, module: Optional[str] = None) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self.list_parameters(module)]

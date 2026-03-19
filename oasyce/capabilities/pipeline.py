"""Capability Pipeline — chain multiple capabilities into a single invocation.

Each step in the pipeline is an independent capability with its own escrow
and settlement. The output of step N becomes the input of step N+1.

    pipeline = Pipeline([
        PipelineStep("translate", {"target_lang": "en"}),
        PipelineStep("summarize", {"max_length": 100}),
        PipelineStep("image_gen", {}),
    ])
    result = executor.run(pipeline, initial_input, consumer_id)

Economics: each step settles independently. The consumer pays for all steps.
If step N fails, steps 0..N-1 are already settled, step N is refunded.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineStep:
    """A single step in a pipeline."""

    capability_id: str
    params: Dict[str, Any] = field(default_factory=dict)
    # Runtime fields (filled during execution)
    state: StepState = StepState.PENDING
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    invocation_id: Optional[str] = None
    price: float = 0.0
    shares_minted: float = 0.0
    error: Optional[str] = None
    duration_ms: int = 0


@dataclass
class Pipeline:
    """An ordered sequence of capability steps."""

    pipeline_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    steps: List[PipelineStep] = field(default_factory=list)
    created_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def completed_steps(self) -> int:
        return sum(1 for s in self.steps if s.state == StepState.COMPLETED)

    @property
    def is_complete(self) -> bool:
        return all(s.state == StepState.COMPLETED for s in self.steps)

    @property
    def is_failed(self) -> bool:
        return any(s.state == StepState.FAILED for s in self.steps)

    @property
    def total_cost(self) -> float:
        return sum(s.price for s in self.steps if s.state == StepState.COMPLETED)

    @property
    def total_shares(self) -> float:
        return sum(s.shares_minted for s in self.steps if s.state == StepState.COMPLETED)

    @property
    def final_output(self) -> Optional[Dict[str, Any]]:
        if not self.is_complete:
            return None
        return self.steps[-1].output_data

    def summary(self) -> Dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "step_count": self.step_count,
            "completed": self.completed_steps,
            "is_complete": self.is_complete,
            "is_failed": self.is_failed,
            "total_cost": round(self.total_cost, 6),
            "total_shares": round(self.total_shares, 4),
            "total_duration_ms": sum(s.duration_ms for s in self.steps),
            "steps": [
                {
                    "capability_id": s.capability_id,
                    "state": s.state.value,
                    "price": round(s.price, 6),
                    "shares": round(s.shares_minted, 4),
                    "duration_ms": s.duration_ms,
                    "error": s.error,
                }
                for s in self.steps
            ],
        }


class PipelineError(Exception):
    """Raised when pipeline execution fails."""

    def __init__(
        self, message: str, step_index: int = -1, partial_results: Optional[Pipeline] = None
    ):
        super().__init__(message)
        self.step_index = step_index
        self.partial_results = partial_results


# Type alias for the step executor function
StepExecutor = Callable[[str, str, Dict[str, Any], float], Dict[str, Any]]
"""(capability_id, consumer_id, input_data, max_price) → {
    invocation_id, price, shares_minted, output
}"""


class PipelineExecutor:
    """Executes capability pipelines step by step.

    Parameters
    ----------
    execute_step : callable
        Function that invokes a single capability and returns result.
        Signature: (capability_id, consumer_id, input_data, max_price) → dict
        Must return: {invocation_id, price, shares_minted, output}
    max_price_per_step : float
        Default max price for each step.
    """

    def __init__(
        self,
        execute_step: StepExecutor,
        max_price_per_step: float = 50.0,
    ) -> None:
        self._execute = execute_step
        self._max_price = max_price_per_step
        self._pipelines: Dict[str, Pipeline] = {}

    def run(
        self,
        pipeline: Pipeline,
        initial_input: Dict[str, Any],
        consumer_id: str,
        max_price_per_step: Optional[float] = None,
    ) -> Pipeline:
        """Execute a pipeline end-to-end.

        Each step's output is merged with the next step's params to form
        its input. If a step fails, remaining steps are marked SKIPPED.

        Returns the pipeline with all steps filled in.
        """
        if not pipeline.steps:
            raise PipelineError("pipeline has no steps")

        max_price = max_price_per_step or self._max_price
        current_input = dict(initial_input)

        for i, step in enumerate(pipeline.steps):
            # Merge step params into input
            step_input = {**current_input, **step.params}
            step.input_data = step_input
            step.state = StepState.RUNNING

            t0 = time.time()
            try:
                result = self._execute(
                    step.capability_id,
                    consumer_id,
                    step_input,
                    max_price,
                )
                step.duration_ms = int((time.time() - t0) * 1000)
                step.state = StepState.COMPLETED
                step.invocation_id = result.get("invocation_id", "")
                step.price = result.get("price", 0.0)
                step.shares_minted = result.get("shares_minted", 0.0)
                step.output_data = result.get("output", {})

                # Output becomes next step's input
                current_input = (
                    step.output_data
                    if isinstance(step.output_data, dict)
                    else {"result": step.output_data}
                )

            except Exception as e:
                step.duration_ms = int((time.time() - t0) * 1000)
                step.state = StepState.FAILED
                step.error = str(e)

                # Skip remaining steps
                for remaining in pipeline.steps[i + 1 :]:
                    remaining.state = StepState.SKIPPED

                self._pipelines[pipeline.pipeline_id] = pipeline
                raise PipelineError(
                    f"step {i} ({step.capability_id}) failed: {e}",
                    step_index=i,
                    partial_results=pipeline,
                )

        self._pipelines[pipeline.pipeline_id] = pipeline
        return pipeline

    def get_pipeline(self, pipeline_id: str) -> Optional[Pipeline]:
        return self._pipelines.get(pipeline_id)

    def list_pipelines(self) -> List[Pipeline]:
        return list(self._pipelines.values())

"""Tests for Capability Pipeline."""

from __future__ import annotations

import pytest

from oasyce.capabilities.pipeline import (
    Pipeline,
    PipelineStep,
    PipelineExecutor,
    PipelineError,
    StepState,
)


# ── Mock executor ─────────────────────────────────────────────────────


def mock_executor(cap_id, consumer_id, input_data, max_price):
    """Simulates a capability invocation — transforms input deterministically."""
    if cap_id == "fail_cap":
        raise RuntimeError("simulated failure")

    # Each "capability" transforms the data in a predictable way
    transforms = {
        "uppercase": lambda d: {**d, "text": d.get("text", "").upper()},
        "add_prefix": lambda d: {**d, "text": "PREFIX_" + d.get("text", "")},
        "count_chars": lambda d: {**d, "char_count": len(d.get("text", ""))},
        "summarize": lambda d: {"summary": d.get("text", "")[:20] + "..."},
        "double": lambda d: {"value": d.get("value", 0) * 2},
        "add_ten": lambda d: {"value": d.get("value", 0) + 10},
    }

    transform = transforms.get(cap_id, lambda d: d)
    output = transform(input_data)

    return {
        "invocation_id": f"inv_{cap_id}_{consumer_id}",
        "price": 1.0,
        "shares_minted": 0.5,
        "output": output,
    }


# ── Pipeline basics ──────────────────────────────────────────────────


class TestPipeline:
    def test_empty_pipeline(self):
        p = Pipeline()
        assert p.step_count == 0
        assert p.is_complete is True  # vacuously true
        assert p.total_cost == 0.0

    def test_step_count(self):
        p = Pipeline(
            steps=[
                PipelineStep("a"),
                PipelineStep("b"),
                PipelineStep("c"),
            ]
        )
        assert p.step_count == 3
        assert p.completed_steps == 0
        assert p.is_complete is False

    def test_summary(self):
        p = Pipeline(steps=[PipelineStep("x")])
        s = p.summary()
        assert s["step_count"] == 1
        assert s["is_complete"] is False


# ── PipelineExecutor ─────────────────────────────────────────────────


class TestPipelineExecutor:
    @pytest.fixture
    def executor(self):
        return PipelineExecutor(execute_step=mock_executor)

    def test_single_step(self, executor):
        p = Pipeline(steps=[PipelineStep("uppercase")])
        result = executor.run(p, {"text": "hello"}, "bob")

        assert result.is_complete
        assert result.steps[0].state == StepState.COMPLETED
        assert result.steps[0].output_data["text"] == "HELLO"
        assert result.total_cost == 1.0
        assert result.total_shares == 0.5

    def test_two_step_chain(self, executor):
        p = Pipeline(
            steps=[
                PipelineStep("uppercase"),
                PipelineStep("add_prefix"),
            ]
        )
        result = executor.run(p, {"text": "hello"}, "bob")

        assert result.is_complete
        assert result.steps[0].output_data["text"] == "HELLO"
        assert result.steps[1].output_data["text"] == "PREFIX_HELLO"
        assert result.total_cost == 2.0

    def test_three_step_chain(self, executor):
        p = Pipeline(
            steps=[
                PipelineStep("uppercase"),
                PipelineStep("add_prefix"),
                PipelineStep("count_chars"),
            ]
        )
        result = executor.run(p, {"text": "hi"}, "carol")

        assert result.is_complete
        assert result.final_output["char_count"] == len("PREFIX_HI")

    def test_numeric_chain(self, executor):
        p = Pipeline(
            steps=[
                PipelineStep("double"),
                PipelineStep("add_ten"),
                PipelineStep("double"),
            ]
        )
        result = executor.run(p, {"value": 5}, "alice")

        # 5 → double → 10 → add_ten → 20 → double → 40
        assert result.final_output["value"] == 40
        assert result.total_cost == 3.0
        assert result.total_shares == 1.5

    def test_step_params_merge(self, executor):
        """Step params are merged into the input from previous step."""
        p = Pipeline(
            steps=[
                PipelineStep("uppercase"),
                PipelineStep("summarize"),
            ]
        )
        result = executor.run(p, {"text": "a long piece of text that needs summarizing"}, "bob")

        assert result.is_complete
        # summarize takes the uppercased text
        assert result.final_output["summary"].startswith("A LONG PIECE")

    def test_failure_mid_pipeline(self, executor):
        p = Pipeline(
            steps=[
                PipelineStep("uppercase"),
                PipelineStep("fail_cap"),
                PipelineStep("count_chars"),
            ]
        )

        with pytest.raises(PipelineError) as exc_info:
            executor.run(p, {"text": "hello"}, "bob")

        err = exc_info.value
        assert err.step_index == 1
        assert err.partial_results is not None
        assert err.partial_results.steps[0].state == StepState.COMPLETED
        assert err.partial_results.steps[1].state == StepState.FAILED
        assert err.partial_results.steps[2].state == StepState.SKIPPED

        # Step 0 was settled (cost incurred), step 1 failed
        assert err.partial_results.total_cost == 1.0

    def test_failure_first_step(self, executor):
        p = Pipeline(
            steps=[
                PipelineStep("fail_cap"),
                PipelineStep("uppercase"),
            ]
        )

        with pytest.raises(PipelineError) as exc_info:
            executor.run(p, {"text": "hi"}, "bob")

        assert exc_info.value.step_index == 0
        assert exc_info.value.partial_results.steps[1].state == StepState.SKIPPED

    def test_empty_pipeline_raises(self, executor):
        p = Pipeline(steps=[])
        with pytest.raises(PipelineError, match="no steps"):
            executor.run(p, {}, "bob")

    def test_pipeline_stored(self, executor):
        p = Pipeline(steps=[PipelineStep("uppercase")])
        executor.run(p, {"text": "test"}, "bob")

        stored = executor.get_pipeline(p.pipeline_id)
        assert stored is not None
        assert stored.is_complete

    def test_list_pipelines(self, executor):
        for i in range(3):
            p = Pipeline(steps=[PipelineStep("double")])
            executor.run(p, {"value": i}, "bob")

        assert len(executor.list_pipelines()) == 3

    def test_duration_tracked(self, executor):
        p = Pipeline(steps=[PipelineStep("uppercase")])
        executor.run(p, {"text": "timing"}, "bob")
        assert p.steps[0].duration_ms >= 0

    def test_summary_after_run(self, executor):
        p = Pipeline(
            steps=[
                PipelineStep("double"),
                PipelineStep("add_ten"),
            ]
        )
        executor.run(p, {"value": 3}, "alice")

        s = p.summary()
        assert s["is_complete"] is True
        assert s["total_cost"] == 2.0
        assert s["total_shares"] == 1.0
        assert len(s["steps"]) == 2
        assert s["steps"][0]["state"] == "completed"

    def test_custom_max_price(self, executor):
        p = Pipeline(steps=[PipelineStep("uppercase")])
        result = executor.run(p, {"text": "hi"}, "bob", max_price_per_step=0.01)
        # Mock executor doesn't check price, but the parameter is passed through
        assert result.is_complete

    def test_invocation_ids_stored(self, executor):
        p = Pipeline(
            steps=[
                PipelineStep("uppercase"),
                PipelineStep("add_prefix"),
            ]
        )
        executor.run(p, {"text": "x"}, "carol")

        assert p.steps[0].invocation_id == "inv_uppercase_carol"
        assert p.steps[1].invocation_id == "inv_add_prefix_carol"

"""Tests for the Work Value Engine — task lifecycle + value calculation."""

import os
import tempfile

import pytest

from oasyce_plugin.services.work_value import (
    TaskType,
    TaskStatus,
    WorkTask,
    WorkValueEngine,
    calculate_task_value,
    TASK_BASE_PRICES,
)


@pytest.fixture
def engine(tmp_path):
    db = str(tmp_path / "test_work.db")
    eng = WorkValueEngine(db_path=db)
    yield eng
    eng.close()


# ── Value calculation ───────────────────────────────────────────────

class TestCalculateTaskValue:
    def test_base_only(self):
        assert calculate_task_value(10.0) == 10.0

    def test_quality_scales(self):
        assert calculate_task_value(10.0, quality=0.5) == 5.0

    def test_complexity_scales(self):
        assert calculate_task_value(10.0, complexity=2.0) == 20.0

    def test_reputation_bonus(self):
        v = calculate_task_value(10.0, reputation_bonus=0.2)
        assert v == pytest.approx(12.0)

    def test_urgency_scales(self):
        v = calculate_task_value(10.0, urgency=1.5)
        assert v == pytest.approx(15.0)

    def test_full_formula(self):
        # 10 * 0.8 * 1.5 * (1 + 0.1) * 1.2 = 15.84
        v = calculate_task_value(10.0, quality=0.8, complexity=1.5,
                                 reputation_bonus=0.1, urgency=1.2)
        assert v == pytest.approx(15.84)

    def test_clamp_quality(self):
        # quality clamped to [0, 1]
        assert calculate_task_value(10.0, quality=2.0) == 10.0
        assert calculate_task_value(10.0, quality=-1.0) == 0.0

    def test_clamp_complexity(self):
        # complexity clamped to [0.5, 3.0]
        assert calculate_task_value(10.0, complexity=0.1) == pytest.approx(5.0)
        assert calculate_task_value(10.0, complexity=10.0) == pytest.approx(30.0)

    def test_clamp_reputation(self):
        # clamped to [0, 0.5]
        assert calculate_task_value(10.0, reputation_bonus=1.0) == pytest.approx(15.0)

    def test_clamp_urgency(self):
        assert calculate_task_value(10.0, urgency=0.1) == pytest.approx(5.0)
        assert calculate_task_value(10.0, urgency=5.0) == pytest.approx(20.0)


# ── Base prices ─────────────────────────────────────────────────────

class TestBasePrices:
    def test_validation_price(self):
        assert TASK_BASE_PRICES[TaskType.VALIDATION] == 2.0

    def test_arbitration_price(self):
        assert TASK_BASE_PRICES[TaskType.ARBITRATION] == 50.0

    def test_verification_price(self):
        assert TASK_BASE_PRICES[TaskType.VERIFICATION] == 5.0

    def test_moderation_price(self):
        assert TASK_BASE_PRICES[TaskType.MODERATION] == 3.0


# ── Task lifecycle ──────────────────────────────────────────────────

class TestTaskLifecycle:
    def test_create_task(self, engine):
        task = engine.create_task(TaskType.VALIDATION, "tx_abc123")
        assert task.task_id.startswith("wt_")
        assert task.task_type == TaskType.VALIDATION
        assert task.trigger_tx == "tx_abc123"
        assert task.status == TaskStatus.PENDING
        assert task.base_value == 2.0
        assert task.created_at > 0

    def test_assign_task(self, engine):
        task = engine.create_task(TaskType.VERIFICATION, "tx_buy_001")
        assigned = engine.assign_task(task.task_id, "worker_node_1")
        assert assigned is not None
        assert assigned.status == TaskStatus.ASSIGNED
        assert assigned.assigned_to == "worker_node_1"
        assert assigned.assigned_at > 0

    def test_assign_non_pending_fails(self, engine):
        task = engine.create_task(TaskType.VALIDATION, "tx_1")
        engine.assign_task(task.task_id, "w1")
        # Try to assign again
        result = engine.assign_task(task.task_id, "w2")
        assert result is None

    def test_complete_task(self, engine):
        task = engine.create_task(TaskType.MODERATION, "tx_flag_01")
        engine.assign_task(task.task_id, "w1")
        completed = engine.complete_task(task.task_id, '{"ok": true}')
        assert completed is not None
        assert completed.status == TaskStatus.COMPLETED
        assert completed.result_data == '{"ok": true}'
        assert completed.completed_at > 0

    def test_complete_non_assigned_fails(self, engine):
        task = engine.create_task(TaskType.VALIDATION, "tx_1")
        result = engine.complete_task(task.task_id)
        assert result is None

    def test_evaluate_task(self, engine):
        task = engine.create_task(TaskType.ARBITRATION, "tx_dispute_01")
        engine.assign_task(task.task_id, "arb_1")
        engine.complete_task(task.task_id, '{"verdict": "delist"}')
        evaluated = engine.evaluate_task(task.task_id, quality_score=0.9,
                                         reputation_bonus=0.1)
        assert evaluated is not None
        assert evaluated.status == TaskStatus.EVALUATED
        assert evaluated.quality_score == 0.9
        assert evaluated.final_value > 0
        # 50 * 0.9 * 1.0 * 1.1 * 1.0 = 49.5
        assert evaluated.final_value == pytest.approx(49.5)

    def test_settle_task(self, engine):
        task = engine.create_task(TaskType.VERIFICATION, "tx_buy_02")
        engine.assign_task(task.task_id, "v1")
        engine.complete_task(task.task_id)
        engine.evaluate_task(task.task_id, quality_score=1.0)
        settled = engine.settle_task(task.task_id)
        assert settled is not None
        assert settled.status == TaskStatus.SETTLED
        assert settled.settled_at > 0
        assert settled.final_value == 5.0

    def test_fail_task(self, engine):
        task = engine.create_task(TaskType.VALIDATION, "tx_1")
        engine.assign_task(task.task_id, "w1")
        failed = engine.fail_task(task.task_id)
        assert failed is not None
        assert failed.status == TaskStatus.FAILED

    def test_full_lifecycle(self, engine):
        """End-to-end: create → assign → complete → evaluate → settle."""
        task = engine.create_task(TaskType.VALIDATION, "tx_register_01",
                                  complexity=1.2, urgency=1.1)
        assert task.status == TaskStatus.PENDING

        task = engine.assign_task(task.task_id, "validator_node_x")
        assert task.status == TaskStatus.ASSIGNED

        task = engine.complete_task(task.task_id, '{"valid": true}')
        assert task.status == TaskStatus.COMPLETED

        task = engine.evaluate_task(task.task_id, quality_score=0.95,
                                    reputation_bonus=0.05)
        assert task.status == TaskStatus.EVALUATED
        # 2.0 * 0.95 * 1.2 * 1.05 * 1.1 ≈ 2.6334
        assert task.final_value == pytest.approx(2.6334)

        task = engine.settle_task(task.task_id)
        assert task.status == TaskStatus.SETTLED


# ── Query methods ───────────────────────────────────────────────────

class TestQueries:
    def test_get_task(self, engine):
        t = engine.create_task(TaskType.VALIDATION, "tx_1")
        fetched = engine.get_task(t.task_id)
        assert fetched is not None
        assert fetched.task_id == t.task_id

    def test_get_nonexistent(self, engine):
        assert engine.get_task("wt_nonexistent") is None

    def test_list_tasks(self, engine):
        engine.create_task(TaskType.VALIDATION, "tx_1")
        engine.create_task(TaskType.ARBITRATION, "tx_2")
        tasks = engine.list_tasks()
        assert len(tasks) == 2

    def test_list_by_status(self, engine):
        t1 = engine.create_task(TaskType.VALIDATION, "tx_1")
        t2 = engine.create_task(TaskType.VERIFICATION, "tx_2")
        engine.assign_task(t1.task_id, "w1")
        pending = engine.list_tasks(status=TaskStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].task_id == t2.task_id

    def test_list_by_worker(self, engine):
        t1 = engine.create_task(TaskType.VALIDATION, "tx_1")
        t2 = engine.create_task(TaskType.VALIDATION, "tx_2")
        engine.assign_task(t1.task_id, "w1")
        engine.assign_task(t2.task_id, "w2")
        w1_tasks = engine.list_tasks(worker_id="w1")
        assert len(w1_tasks) == 1
        assert w1_tasks[0].assigned_to == "w1"

    def test_list_by_type(self, engine):
        engine.create_task(TaskType.VALIDATION, "tx_1")
        engine.create_task(TaskType.ARBITRATION, "tx_2")
        arbs = engine.list_tasks(task_type=TaskType.ARBITRATION)
        assert len(arbs) == 1

    def test_pending_tasks(self, engine):
        engine.create_task(TaskType.VALIDATION, "tx_1")
        t2 = engine.create_task(TaskType.VALIDATION, "tx_2")
        engine.assign_task(t2.task_id, "w1")
        pending = engine.pending_tasks()
        assert len(pending) == 1


# ── Stats ───────────────────────────────────────────────────────────

class TestStats:
    def test_worker_stats_empty(self, engine):
        stats = engine.worker_stats("nobody")
        assert stats["total_tasks"] == 0
        assert stats["total_earned"] == 0.0

    def test_worker_stats(self, engine):
        t = engine.create_task(TaskType.VERIFICATION, "tx_1")
        engine.assign_task(t.task_id, "w1")
        engine.complete_task(t.task_id)
        engine.evaluate_task(t.task_id, quality_score=1.0)
        engine.settle_task(t.task_id)

        stats = engine.worker_stats("w1")
        assert stats["total_tasks"] == 1
        assert stats["settled"] == 1
        assert stats["total_earned"] == 5.0
        assert stats["avg_quality"] == 1.0

    def test_global_stats(self, engine):
        engine.create_task(TaskType.VALIDATION, "tx_1")
        t2 = engine.create_task(TaskType.VERIFICATION, "tx_2")
        engine.assign_task(t2.task_id, "w1")
        engine.complete_task(t2.task_id)
        engine.evaluate_task(t2.task_id, quality_score=0.8)
        engine.settle_task(t2.task_id)

        stats = engine.global_stats()
        assert stats["total_tasks"] == 2
        assert stats["by_status"]["pending"] == 1
        assert stats["by_status"]["settled"] == 1
        assert stats["total_value_settled"] == pytest.approx(4.0)


# ── WorkTask.to_dict ────────────────────────────────────────────────

class TestWorkTaskDict:
    def test_to_dict(self, engine):
        task = engine.create_task(TaskType.VALIDATION, "tx_1")
        d = task.to_dict()
        assert d["task_id"] == task.task_id
        assert d["task_type"] == "validation"
        assert d["status"] == "pending"
        assert "base_value" in d
        assert "final_value" in d

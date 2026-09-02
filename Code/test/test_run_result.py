import pytest

from Contracts.run_result import failed_run_result


@pytest.mark.parametrize(
    ("stage", "workflow"),
    [("bootstrap", "bootstrap"), ("evolve", "evolve"), ("pattern", "evolve")],
)
def test_failed_run_result_has_one_cross_stage_contract(stage, workflow):
    result = failed_run_result(
        stage=stage,
        workflow=workflow,
        run_id="R_test",
        namespace="test",
        snapshot_id=None,
        parent_snapshot_id=None,
        error_code="TEST_FAILURE",
        error="test failure",
    )

    assert result == {
        "status": "FAILED",
        "stage": stage,
        "workflow": workflow,
        "run_id": "R_test",
        "namespace": "test",
        "snapshot_id": None,
        "parent_snapshot_id": None,
        "error_code": "TEST_FAILURE",
        "error": "test failure",
        "retryable": False,
    }

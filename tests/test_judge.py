from src.judge import decide
from src.models import OperatorCase


def case(**kwargs):
    payload = dict(case_id=1, category="mock", name_cn="mock", operator_name="Coverage.mock", code="x=1")
    payload.update(kwargs)
    return OperatorCase(**payload)


def dag_summary(**kwargs):
    payload = {
        "execute_code_seen": True,
        "execute_code_status": 200,
        "code_payload_match": True,
        "dag_count": 3,
        "dag_success_count": 3,
        "dag_failed_count": 0,
        "dag_missing_count": 0,
    }
    payload.update(kwargs)
    return payload


def test_successful_dags_default_to_review_not_false_pass():
    result = decide(case(), "SUCCESS", dag_summary(), 0.2, 0.01)
    assert result[:2] == ("UNCERTAIN", "REVIEW")


def test_explicit_execution_only_can_pass():
    result = decide(case(validation_mode="EXECUTION_ONLY"), "SUCCESS", dag_summary(), 0.2, 0.01)
    assert result[:2] == ("VALID", "PASS")


def test_failed_or_missing_dag_cannot_pass():
    failed = dag_summary(dag_success_count=2, dag_failed_count=1)
    assert decide(case(), "FAIL", failed, 0.2, 0.01)[1] == "FAIL"
    missing = dag_summary(dag_success_count=2, dag_missing_count=1)
    assert decide(case(), "SUCCESS", missing, 0.2, 0.01)[1] == "TIMEOUT"


def test_console_regex_is_deterministic():
    selected = case(validation_mode="CONSOLE_REGEX", expected_console_regex=r"R squared=0\.8")
    summary = dag_summary(dag_count=0, dag_success_count=0, execute_code_log="R squared=0.8")
    assert decide(selected, "SUCCESS", summary, None, 0.01, "done")[1] == "PASS"


def test_auth_expired_maps_to_explicit_skip():
    assert decide(case(), "AUTH_EXPIRED", {}, None, 0.01)[1] == "SKIPPED_AUTH_EXPIRED"


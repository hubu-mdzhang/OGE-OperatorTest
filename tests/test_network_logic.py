from src.models import NetworkRecord
from src.network import NetworkCollector
from src.utils import normalize_code


def collector(records, expected_code="print('x')"):
    item = NetworkCollector.__new__(NetworkCollector)
    item.records = records
    item.expected_code = expected_code
    item.active = False
    item.auth_expired = False
    item.auth_signal = ""
    return item


def test_code_normalization_only_handles_transport_eol_and_final_newline():
    assert normalize_code("a\r\nb\r\n") == normalize_code("a\nb")
    assert normalize_code("a  \nb") != normalize_code("a\nb")


def test_dag_correlation_ignores_unrelated_background_success():
    execute_code = NetworkRecord(
        record_id="net-1",
        kind="executeCode",
        method="POST",
        url="https://x/api/computation-api/executeCode",
        status=200,
        request_json={"code": "print('x')"},
        response_json={"log": "", "dags": {"a": "expected-1", "b": "expected-2"}},
    )
    expected_ok = NetworkRecord(
        record_id="net-2",
        kind="executeDag",
        method="POST",
        url="https://x/api/computation-api/executeDag?dagId=expected-1",
        status=200,
        response_json={"status": "success"},
        dag_id="expected-1",
    )
    unrelated_ok = NetworkRecord(
        record_id="net-3",
        kind="executeDag",
        method="POST",
        url="https://x/api/computation-api/executeDag?dagId=other",
        status=200,
        response_json={"status": "success"},
        dag_id="other",
    )
    summary = collector([execute_code, expected_ok, unrelated_ok]).summarize()
    assert summary["dag_count"] == 2
    assert summary["dag_success_count"] == 1
    assert summary["dag_missing_count"] == 1
    assert summary["unexpected_dag_ids"] == ["other"]
    assert summary["network_complete"] is False


def test_three_target_dags_with_one_failure_is_bound_exactly():
    records = [
        NetworkRecord(
            record_id="ec",
            kind="executeCode",
            method="POST",
            url="https://x/api/computation-api/executeCode",
            status=200,
            request_json={"code": "print('x')"},
            response_json={"dags": {"a": "1", "b": "2", "c": "3"}},
        )
    ]
    for dag_id, status in (("1", "success"), ("2", "success"), ("3", "failed")):
        records.append(
            NetworkRecord(
                record_id=f"dag-{dag_id}",
                kind="executeDag",
                method="POST",
                url=f"https://x/api/computation-api/executeDag?dagId={dag_id}",
                status=200,
                response_json={"status": status},
                dag_id=dag_id,
            )
        )
    summary = collector(records).summarize()
    assert summary["dag_count"] == 3
    assert summary["dag_success_count"] == 2
    assert summary["dag_failed_count"] == 1
    assert summary["dag_missing_count"] == 0


import csv

from src.models import CaseResult
from src.report import append_result_event, read_jsonl_events


def make_result(case_id: int) -> CaseResult:
    return CaseResult(
        run_id="ledger-test",
        case_id=case_id,
        category="mock",
        name_cn=f"case-{case_id}",
        operator_name=f"Operator.{case_id}",
        expected_result_type="UNKNOWN",
        enabled=True,
        source_status="READY",
        source_original_status="",
        source_development_status="",
        source_manual_test_status="",
        attempt=1,
        retry_count=0,
        execution_status="SUCCESS",
        result_status="UNCERTAIN",
        final_status="REVIEW",
        started_at="2026-08-12T00:00:00-07:00",
        finished_at="2026-08-12T00:00:01-07:00",
        duration_sec=1.0,
    )


def test_jsonl_and_csv_are_durable_for_more_than_204_events(tmp_path):
    jsonl = tmp_path / "results.jsonl"
    csv_path = tmp_path / "results.csv"
    for case_id in range(1, 251):
        assert append_result_event(make_result(case_id), jsonl, csv_path) == case_id
    assert len(read_jsonl_events(jsonl)) == 250
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 250


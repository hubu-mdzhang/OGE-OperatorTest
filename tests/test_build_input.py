from pathlib import Path

from tools.build_input import build_rows, write_csv


ROOT = Path(__file__).resolve().parents[1]


def test_excel_builds_canonical_204_row_csv(tmp_path):
    excel = ROOT / "input" / "source" / "副本算子排序表0806返修.xlsx"
    rows, report = build_rows(excel, "主要")
    assert report["passed"] is True
    assert report["total_records"] == 204
    assert report["executable_records"] == 189
    assert report["missing_code_records"] == 15
    assert report["missing_operator_name_records"] == 15
    assert report["duplicate_case_ids"] == {}
    assert list(report["duplicate_operator_names"]) == ["Feature Model Regress"]
    assert report["syntax_errors"] == []
    assert [row["case_id"] for row in rows] == list(range(1, 205))
    assert all(row["source_status"] == "READY" for row in rows[:189])
    assert all(row["source_status"] == "MISSING_OPERATOR_NAME_AND_CODE" for row in rows[189:])

    output = tmp_path / "operators.csv"
    write_csv(rows, output)
    assert output.read_bytes().startswith(b"\xef\xbb\xbf")


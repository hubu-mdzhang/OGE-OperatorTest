from pathlib import Path

import pytest

from src.loader import load_cases


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_csv_loads_204_and_preserves_history():
    cases = load_cases(ROOT / "input" / "operators.csv")
    assert len(cases) == 204
    assert len({case.case_id for case in cases}) == 204
    assert sum(case.has_code for case in cases) == 189
    assert sum(not case.has_code for case in cases) == 15
    assert cases[0].source_original_status
    assert cases[188].operator_name == "Feature Gaussian Mixture"
    assert cases[189].source_status == "MISSING_OPERATOR_NAME_AND_CODE"
    for case in cases[:189]:
        compile(case.code, f"<{case.case_id}:{case.operator_name}>", "exec")


def test_word_is_not_a_formal_scheduler_input():
    with pytest.raises(ValueError, match="正式调度输入仅支持"):
        load_cases(ROOT / "legacy.docx")


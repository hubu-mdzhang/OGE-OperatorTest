from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, List

from .models import OperatorCase


REQUIRED_COLUMNS = {
    "case_id",
    "category",
    "name_cn",
    "operator_name",
    "code",
    "expected_result_type",
    "enabled",
    "source_status",
}


def _as_bool(value: object, default: bool = True) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on", "是", "启用"}:
        return True
    if text in {"0", "false", "no", "n", "off", "否", "禁用"}:
        return False
    raise ValueError(f"enabled 不是合法布尔值: {value!r}")


def load_csv(path: str | Path) -> List[OperatorCase]:
    source = Path(path).resolve()
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - headers)
        if missing:
            raise ValueError(f"CSV 缺少必需字段: {', '.join(missing)}")

        cases: List[OperatorCase] = []
        for csv_row, row in enumerate(reader, start=2):
            raw_case_id = str(row.get("case_id") or "").strip()
            if not raw_case_id:
                raise ValueError(f"CSV 第 {csv_row} 行 case_id 为空")
            try:
                case_id = int(float(raw_case_id))
            except ValueError as exc:
                raise ValueError(f"CSV 第 {csv_row} 行 case_id 非整数: {raw_case_id!r}") from exc

            source_row_raw = str(row.get("source_row") or "0").strip()
            source_row = int(float(source_row_raw)) if source_row_raw else 0
            cases.append(
                OperatorCase(
                    case_id=case_id,
                    category=str(row.get("category") or "").strip(),
                    name_cn=str(row.get("name_cn") or "").strip(),
                    operator_name=str(row.get("operator_name") or "").strip(),
                    code=str(row.get("code") or "").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n"),
                    expected_result_type=str(row.get("expected_result_type") or "UNKNOWN").strip().upper(),
                    enabled=_as_bool(row.get("enabled"), default=True),
                    source_status=str(row.get("source_status") or "").strip() or "READY",
                    source_original_status=str(row.get("source_original_status") or "").strip(),
                    source_development_status=str(row.get("source_development_status") or "").strip(),
                    source_manual_test_status=str(row.get("source_manual_test_status") or "").strip(),
                    description=str(row.get("description") or "").strip(),
                    input_data_type=str(row.get("input_data_type") or "").strip(),
                    source_notes=str(row.get("source_notes") or "").strip(),
                    validation_mode=str(row.get("validation_mode") or "MANUAL_OR_MULTIMODAL").strip().upper(),
                    expected_console_regex=str(row.get("expected_console_regex") or "").strip(),
                    source_row=source_row,
                    source=str(source),
                )
            )

    counts: dict[int, int] = {}
    for case in cases:
        counts[case.case_id] = counts.get(case.case_id, 0) + 1
    duplicate_ids = sorted(case_id for case_id, count in counts.items() if count > 1)
    if duplicate_ids:
        raise ValueError(f"CSV 存在重复 case_id: {duplicate_ids}")
    return sorted(cases, key=lambda item: item.case_id)


def load_cases(path: str | Path) -> List[OperatorCase]:
    source = Path(path)
    if source.suffix.lower() != ".csv":
        raise ValueError("正式调度输入仅支持 .csv；请先运行 build_input.bat 由原始 Excel 生成 input/operators.csv")
    return load_csv(source)


def is_selected(
    case: OperatorCase,
    start_id: int | None = None,
    end_id: int | None = None,
    operator_contains: str | None = None,
) -> bool:
    if start_id is not None and case.case_id < start_id:
        return False
    if end_id is not None and case.case_id > end_id:
        return False
    needle = operator_contains.casefold() if operator_contains else None
    if needle and needle not in case.operator_name.casefold() and needle not in case.name_cn.casefold():
        return False
    return True


def filter_cases(
    cases: Iterable[OperatorCase],
    start_id: int | None = None,
    end_id: int | None = None,
    operator_contains: str | None = None,
) -> List[OperatorCase]:
    return [case for case in cases if is_selected(case, start_id, end_id, operator_contains)]

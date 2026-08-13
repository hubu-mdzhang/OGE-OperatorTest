from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from src.loader import filter_cases, load_cases
from src.runner import run_cases


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OGE 算子 CSV 驱动批量自动化测试 V2")
    parser.add_argument("--input", default="input/operators.csv", help="规范调度 CSV，默认 input/operators.csv")
    parser.add_argument("--config", default="config.yaml", help="配置文件，默认 config.yaml")
    parser.add_argument("--start-id", type=int, default=None, help="只执行 case_id 不小于该值的 READY 用例")
    parser.add_argument("--end-id", type=int, default=None, help="只执行 case_id 不大于该值的 READY 用例")
    parser.add_argument("--contains", default=None, help="只执行中/英文名包含该字符串的 READY 用例")
    parser.add_argument("--list-only", action="store_true", help="仅检查并列出 CSV，不启动浏览器")
    parser.add_argument("--resume", action="store_true", help="从 output/LATEST_RUN.txt 指向的批次断点恢复")
    parser.add_argument("--run-id", default=None, help="新建指定 Run ID，或配合 --resume 恢复指定批次")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    input_path = Path(args.input).resolve()
    config_path = Path(args.config).resolve()
    cases = load_cases(input_path)
    selected = filter_cases(cases, args.start_id, args.end_id, args.contains)
    source_counts = Counter(case.source_status for case in cases)
    executable = sum(1 for case in cases if case.enabled and case.has_code)
    missing_code = sum(1 for case in cases if not case.has_code)

    print(
        f"规范输入总数={len(cases)}，可执行={executable}，缺代码/英文名={missing_code}，"
        f"本次筛选命中={len(selected)}"
    )
    print("输入源状态: " + ", ".join(f"{key}={value}" for key, value in sorted(source_counts.items())))
    for case in cases[:10]:
        print(
            f"  {case.case_id:03d} [{case.category}] {case.name_cn} -> "
            f"{case.operator_name or '[NO OPERATOR NAME]'} ({case.source_status})"
        )
    if len(cases) > 10:
        print(f"  ... 另有 {len(cases) - 10} 条")

    if args.list_only:
        return
    run_cases(
        cases,
        config_path,
        input_path,
        start_id=args.start_id,
        end_id=args.end_id,
        contains=args.contains,
        resume=args.resume,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()

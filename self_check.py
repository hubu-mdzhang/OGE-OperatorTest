from __future__ import annotations

import compileall
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.loader import load_cases


ROOT = Path(__file__).resolve().parent


def check_compile() -> str:
    targets = [ROOT / "src", ROOT / "tools", ROOT / "main.py", ROOT / "login.py", ROOT / "self_check.py"]
    ok = True
    for target in targets:
        if target.is_dir():
            ok = compileall.compile_dir(target, quiet=1) and ok
        else:
            ok = compileall.compile_file(target, quiet=1) and ok
    if not ok:
        raise RuntimeError("Python compileall 失败")
    return "Python 源码编译检查通过"


def check_build_input() -> str:
    command = [
        sys.executable,
        str(ROOT / "tools" / "build_input.py"),
        "--excel",
        str(ROOT / "input" / "source" / "副本算子排序表0806返修.xlsx"),
        "--output",
        str(ROOT / "input" / "operators.csv"),
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60)
    if completed.returncode != 0:
        raise RuntimeError("build_input.py 失败:\n" + completed.stdout + "\n" + completed.stderr)
    report = json.loads((ROOT / "input" / "operators.build_report.json").read_text(encoding="utf-8"))
    expected = (report["total_records"], report["executable_records"], report["missing_code_records"])
    if expected != (204, 189, 15):
        raise RuntimeError(f"业务总表统计异常: {expected} != (204, 189, 15)")
    if report["duplicate_case_ids"] or report["syntax_errors"]:
        raise RuntimeError("输入质检存在重复编号或语法错误")
    if "Feature Model Regress" not in report["duplicate_operator_names"]:
        raise RuntimeError("未识别原表已知重复英文名")
    return "Excel→CSV 质检通过：总数=204，可执行=189，SKIPPED_NO_CODE=15，重复英文名已告警"


def check_csv() -> str:
    cases = load_cases(ROOT / "input" / "operators.csv")
    if len(cases) != 204 or sum(case.has_code for case in cases) != 189:
        raise RuntimeError("operators.csv 记录数异常")
    for case in cases[:189]:
        compile(case.code, f"<{case.case_id}:{case.operator_name}>", "exec")
    if any(case.has_code for case in cases[189:]):
        raise RuntimeError("190～204 不应伪造代码")
    return "规范 CSV 204 条加载通过，189 份代码语法通过，15 条无代码记录保留"


def check_har() -> str:
    data = json.loads((ROOT / "aaaa.har").read_text(encoding="utf-8-sig"))
    entries = data.get("log", {}).get("entries", [])
    execute_code = [
        entry
        for entry in entries
        if urlparse(entry.get("request", {}).get("url", "")).path.endswith("/api/computation-api/executeCode")
    ]
    execute_dag = [
        entry
        for entry in entries
        if urlparse(entry.get("request", {}).get("url", "")).path.endswith("/api/computation-api/executeDag")
    ]
    if not execute_code:
        raise RuntimeError("HAR 未发现 executeCode")
    latest = execute_code[-1]
    request_payload = json.loads(latest["request"]["postData"]["text"])
    response_payload = json.loads(latest["response"]["content"]["text"])
    expected = set((response_payload.get("dags") or {}).values())
    success = set()
    for entry in execute_dag:
        dag_id = (parse_qs(urlparse(entry["request"]["url"]).query).get("dagId") or [""])[0]
        payload = json.loads(entry["response"]["content"]["text"])
        if entry["response"]["status"] == 200 and payload.get("status") == "success":
            success.add(dag_id)
    if latest["response"]["status"] != 200 or not request_payload.get("code") or not expected <= success:
        raise RuntimeError("HAR executeCode/executeDag 契约检查失败")
    return f"真实 HAR 契约通过：目标 DAG={len(expected)}，逐 ID 成功={len(expected & success)}"


def check_pytest() -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=600,
    )
    if completed.returncode != 0:
        raise RuntimeError("pytest 失败:\n" + completed.stdout + "\n" + completed.stderr)
    line = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else "pytest passed"
    return f"自动化测试套件通过：{line}"


def main() -> None:
    checks = [check_compile, check_build_input, check_csv, check_har, check_pytest]
    print("OGE 算子自动化测试框架 V2 - 自检")
    print("=" * 72)
    for index, check in enumerate(checks, start=1):
        print(f"[{index}/{len(checks)}] PASS - {check()}")
    print("=" * 72)
    print("SELF-CHECK PASS")
    print("真实 OGE 登录态下仍建议先执行：run.bat --start-id 1 --end-id 1")


if __name__ == "__main__":
    main()

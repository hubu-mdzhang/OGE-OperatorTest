from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PIL import Image, ImageChops, ImageStat

from .models import OperatorCase


def image_change_ratio(before: str | Path, after: str | Path) -> Optional[float]:
    before_path, after_path = Path(before), Path(after)
    if not before_path.exists() or not after_path.exists():
        return None
    try:
        with Image.open(before_path) as before_image, Image.open(after_path) as after_image:
            before_rgb = before_image.convert("RGB")
            after_rgb = after_image.convert("RGB")
            if before_rgb.size != after_rgb.size:
                after_rgb = after_rgb.resize(before_rgb.size)
            diff = ImageChops.difference(before_rgb, after_rgb)
            means = ImageStat.Stat(diff).mean
            return float(sum(means) / (len(means) * 255.0))
    except Exception:
        return None


def decide(
    case: OperatorCase,
    execution_status: str,
    network_summary: dict,
    visual_ratio: Optional[float],
    diff_threshold: float,
    console_text: str = "",
) -> tuple[str, str, str]:
    """Return result_status, final_status and reason.

    Backend completion proves execution, not scientific/visual correctness. Unless a case
    explicitly opts into a deterministic validation mode, successful execution becomes
    SUCCESS + UNCERTAIN + REVIEW.
    """
    if execution_status == "AUTH_EXPIRED":
        return "NOT_EVALUATED", "SKIPPED_AUTH_EXPIRED", "登录状态失效，批次已安全停止"
    if execution_status == "TIMEOUT":
        return "NOT_EVALUATED", "TIMEOUT", "控制台或目标 DAG 等待超时"
    if execution_status != "SUCCESS":
        return "INVALID", "FAIL", "程序执行失败"

    execute_code_seen = bool(network_summary.get("execute_code_seen"))
    execute_code_status = network_summary.get("execute_code_status")
    code_match = network_summary.get("code_payload_match")
    dag_count = int(network_summary.get("dag_count") or 0)
    dag_success = int(network_summary.get("dag_success_count") or 0)
    dag_failed = int(network_summary.get("dag_failed_count") or 0)
    dag_missing = int(network_summary.get("dag_missing_count") or 0)
    execute_log = str(network_summary.get("execute_code_log") or "").strip()
    execute_error = str(network_summary.get("execute_code_error") or "").strip()

    if network_summary.get("auth_expired"):
        return "NOT_EVALUATED", "SKIPPED_AUTH_EXPIRED", str(network_summary.get("auth_signal") or "登录失效")
    if execute_code_status is not None and not 200 <= int(execute_code_status) < 300:
        detail = f"；{execute_error}" if execute_error else ""
        return "INVALID", "FAIL", f"executeCode HTTP 状态异常: {execute_code_status}{detail}"
    if code_match is False:
        return "INVALID", "FAIL", "executeCode 实际提交代码与 input/operators.csv 不一致"
    if dag_failed > 0:
        return "INVALID", "FAIL", f"目标 DAG={dag_count}，成功={dag_success}，失败={dag_failed}"
    if dag_missing > 0:
        return "NOT_EVALUATED", "TIMEOUT", f"目标 DAG={dag_count}，成功={dag_success}，缺失响应={dag_missing}"

    evidence_complete = False
    execution_evidence = ""
    if dag_count > 0 and dag_success == dag_count:
        evidence_complete = True
        execution_evidence = f"{dag_count} 个目标 DAG 全部 success"
    elif execute_code_seen and execute_log:
        evidence_complete = True
        execution_evidence = "executeCode 返回日志且控制台成功"
    elif execute_code_seen and dag_count == 0:
        evidence_complete = True
        execution_evidence = "executeCode 已完成但无 DAG/日志"

    mode = (case.validation_mode or "MANUAL_OR_MULTIMODAL").upper()
    if mode == "EXECUTION_ONLY":
        if evidence_complete:
            return "VALID", "PASS", f"显式 EXECUTION_ONLY 规则通过；{execution_evidence}"
        return "UNCERTAIN", "REVIEW", "显式 EXECUTION_ONLY，但确定性 Network 证据不完整"

    if mode == "CONSOLE_REGEX":
        pattern = case.expected_console_regex.strip()
        if not pattern:
            return "UNCERTAIN", "REVIEW", "CONSOLE_REGEX 未配置 expected_console_regex"
        target = "\n".join(part for part in (console_text, execute_log) if part)
        try:
            matched = bool(re.search(pattern, target, flags=re.MULTILINE))
        except re.error as exc:
            return "INVALID", "FAIL", f"expected_console_regex 非法: {exc}"
        if matched:
            return "VALID", "PASS", "确定性 Console 正则断言通过"
        return "INVALID", "FAIL", "确定性 Console 正则断言未通过"

    if mode == "GLOBE_CHANGED":
        if visual_ratio is None:
            return "UNCERTAIN", "REVIEW", "未取得可比较的 Globe 截图"
        if visual_ratio >= diff_threshold:
            return "VALID", "PASS", f"显式 GLOBE_CHANGED 规则通过，变化比例={visual_ratio:.6f}"
        return "INVALID", "FAIL", f"显式 GLOBE_CHANGED 规则未通过，变化比例={visual_ratio:.6f}"

    if not execute_code_seen:
        return "UNCERTAIN", "REVIEW", "控制台成功，但未捕获 executeCode；需检查网络接口契约"
    if evidence_complete:
        visual_note = ""
        if visual_ratio is not None:
            visual_note = f"；Globe 变化比例={visual_ratio:.6f}"
        return (
            "UNCERTAIN",
            "REVIEW",
            f"程序执行链成功（{execution_evidence}），但结果正确性无确定性 Oracle{visual_note}；进入人工/可选多模态复核",
        )
    return "UNCERTAIN", "REVIEW", "程序执行成功，但结果证据不足；进入人工/可选多模态复核"

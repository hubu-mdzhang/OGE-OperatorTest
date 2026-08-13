from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List

import yaml
from playwright.sync_api import BrowserContext, sync_playwright

from .judge import decide, image_change_ratio
from .loader import is_selected
from .models import CaseResult, ConsoleEntry, NetworkRecord, OperatorCase
from .network import NetworkCollector
from .oge_page import AuthExpiredError, OGEDevelopPage, WorkspaceContractError
from .report import (
    append_result_event,
    atomic_write_json,
    ensure_required_evidence,
    generate_results_xlsx,
    latest_results,
    save_case_json,
    write_console,
    write_network,
)


RETRYABLE_RESUME_STATUSES = {"SKIPPED_AUTH_EXPIRED", "SKIPPED_BATCH_ABORTED"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def make_run_id() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _launch_context(playwright: Any, cfg: dict, profile_dir: Path) -> BrowserContext:
    app = cfg["app"]
    kwargs: dict[str, Any] = {
        "user_data_dir": str(profile_dir),
        "headless": bool(app.get("headless", False)),
        "viewport": app.get("viewport") or None,
    }
    executable = app.get("browser_executable_path")
    channel = app.get("browser_channel")
    if executable:
        kwargs["executable_path"] = str(executable)
    elif channel:
        kwargs["channel"] = str(channel)
    try:
        return playwright.chromium.launch_persistent_context(**kwargs)
    except Exception as exc:
        if not app.get("fallback_to_playwright_chromium", True) or executable:
            raise
        print(f"[WARN] 启动 channel={channel!r} 失败，回退 Playwright Chromium: {exc}")
        kwargs.pop("channel", None)
        return playwright.chromium.launch_persistent_context(**kwargs)


def launch_persistent_context(playwright: Any, cfg: dict, base_dir: Path) -> BrowserContext:
    profile_dir = (base_dir / cfg["app"]["persistent_profile_dir"]).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    return _launch_context(playwright, cfg, profile_dir)


def _try_trace_start(context: BrowserContext, enabled: bool) -> bool:
    if not enabled:
        return False
    try:
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        return True
    except Exception:
        return False


def _try_trace_stop(context: BrowserContext, path: Path, started: bool) -> None:
    if not started:
        return
    try:
        context.tracing.stop(path=str(path))
    except Exception:
        try:
            context.tracing.stop()
        except Exception:
            pass


def _relative(path: Path, run_root: Path) -> str:
    try:
        return path.resolve().relative_to(run_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _selection_payload(start_id: int | None, end_id: int | None, contains: str | None) -> dict[str, Any]:
    return {"start_id": start_id, "end_id": end_id, "contains": contains or ""}


def _resolve_resume_root(output_root: Path, run_id: str | None) -> Path:
    if run_id:
        candidate = (output_root / "runs" / run_id).resolve()
    else:
        latest_file = output_root / "LATEST_RUN.txt"
        if not latest_file.exists():
            raise RuntimeError("没有可恢复的批次：output/LATEST_RUN.txt 不存在")
        raw = latest_file.read_text(encoding="utf-8").strip()
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (output_root / raw).resolve()
        else:
            candidate = candidate.resolve()
    runs_root = (output_root / "runs").resolve()
    if candidate != runs_root and runs_root not in candidate.parents:
        raise RuntimeError(f"LATEST_RUN 指向 output/runs 之外，拒绝恢复: {candidate}")
    if not candidate.exists():
        raise RuntimeError(f"恢复目录不存在: {candidate}")
    return candidate


def _prepare_run(
    cfg: dict,
    base_dir: Path,
    input_csv: Path,
    start_id: int | None,
    end_id: int | None,
    contains: str | None,
    resume: bool,
    requested_run_id: str | None,
) -> tuple[Path, dict[str, Any]]:
    output_root = (base_dir / cfg["output"]["root_dir"]).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    selection = _selection_payload(start_id, end_id, contains)
    input_hash = file_sha256(input_csv)

    if resume:
        run_root = _resolve_resume_root(output_root, requested_run_id)
        metadata_path = run_root / "run_metadata.json"
        if not metadata_path.exists():
            raise RuntimeError(f"恢复目录缺少 run_metadata.json: {run_root}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("input_sha256") != input_hash:
            raise RuntimeError("input/operators.csv 已变化，不能覆盖式恢复旧批次；请新建批次运行")
        old_selection = metadata.get("selection") or {}
        if selection == {"start_id": None, "end_id": None, "contains": ""}:
            selection = old_selection
        if selection != old_selection:
            raise RuntimeError(f"恢复参数必须与原批次一致：原={old_selection}，当前={selection}")
        metadata["batch_status"] = "RESUMING"
        metadata["resumed_at"] = now_iso()
        atomic_write_json(metadata_path, metadata)
        return run_root, metadata

    run_id = requested_run_id or make_run_id()
    run_root = output_root / "runs" / run_id
    if run_root.exists():
        raise RuntimeError(f"Run ID 已存在，拒绝覆盖: {run_root}")
    (run_root / "cases").mkdir(parents=True, exist_ok=False)
    (run_root / "input").mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_csv, run_root / "input" / "operators.csv")
    metadata = {
        "run_id": run_id,
        "batch_status": "INITIALIZING",
        "created_at": now_iso(),
        "input_csv": "input/operators.csv",
        "source_input_csv": str(input_csv),
        "input_sha256": input_hash,
        "selection": selection,
    }
    atomic_write_json(run_root / "run_metadata.json", metadata)
    (output_root / "LATEST_RUN.txt").write_text(str(run_root), encoding="utf-8")
    return run_root, metadata


def _case_root(run_root: Path, case: OperatorCase) -> Path:
    return run_root / "cases" / case.slug


def _evidence_paths(run_root: Path, root: Path) -> dict[str, str]:
    return {
        "evidence_dir": _relative(root, run_root),
        "source_path": _relative(root / "source.py", run_root),
        "result_path": _relative(root / "result.json", run_root),
        "console_path": _relative(root / "console.txt", run_root),
        "network_path": _relative(root / "network.json", run_root),
        "trace_path": _relative(root / "trace.zip", run_root),
        "result_screenshot_path": _relative(root / "result_screenshot.png", run_root),
        "globe_result_path": _relative(root / "globe_result.png", run_root),
    }


def _result_base(case: OperatorCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "category": case.category,
        "name_cn": case.name_cn,
        "operator_name": case.operator_name,
        "expected_result_type": case.expected_result_type,
        "enabled": case.enabled,
        "source_status": case.source_status,
        "source_original_status": case.source_original_status,
        "source_development_status": case.source_development_status,
        "source_manual_test_status": case.source_manual_test_status,
    }


def _skip_result(
    run_id: str,
    run_root: Path,
    case: OperatorCase,
    final_status: str,
    reason: str,
    batch_status: str,
) -> CaseResult:
    root = _case_root(run_root, case)
    ensure_required_evidence(root, case, final_status, reason)
    timestamp = now_iso()
    execution_status = "AUTH_EXPIRED" if final_status == "SKIPPED_AUTH_EXPIRED" else "SKIPPED"
    paths = _evidence_paths(run_root, root)
    result = CaseResult(
        run_id=run_id,
        **_result_base(case),
        attempt=0,
        retry_count=0,
        execution_status=execution_status,
        result_status="NOT_EVALUATED",
        final_status=final_status,
        started_at=timestamp,
        finished_at=timestamp,
        duration_sec=0.0,
        batch_status=batch_status,
        failure_reason=reason,
        **paths,
    )
    save_case_json(result, root / "result.json")
    return result


def _promote_attempt(attempt_dir: Path, case_root: Path) -> None:
    case_root.mkdir(parents=True, exist_ok=True)
    filenames = [
        "source.py",
        "console.txt",
        "network.json",
        "network_summary.json",
        "trace.zip",
        "result_screenshot.png",
        "globe_result.png",
        "globe_before.png",
    ]
    for filename in filenames:
        source = attempt_dir / filename
        if source.exists():
            shutil.copy2(source, case_root / filename)


def _append_and_checkpoint(
    result: CaseResult,
    run_root: Path,
    metadata: dict[str, Any],
) -> None:
    event_seq = append_result_event(result, run_root / "results.jsonl", run_root / "results.csv")
    metadata["last_case_id"] = result.case_id
    metadata["last_event_seq"] = event_seq
    metadata["updated_at"] = now_iso()
    atomic_write_json(run_root / "checkpoint.json", metadata)
    if result.final_status == "REVIEW":
        with (run_root / "review_queue.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "run_id": result.run_id,
                        "case_id": result.case_id,
                        "operator_name": result.operator_name,
                        "reason": result.failure_reason,
                        "result_screenshot_path": result.result_screenshot_path,
                        "globe_result_path": result.globe_result_path,
                        "result_path": result.result_path,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _load_case_result(path: Path) -> CaseResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["console_entries"] = [ConsoleEntry(**item) for item in payload.get("console_entries", [])]
    payload["network_records"] = [NetworkRecord(**item) for item in payload.get("network_records", [])]
    return CaseResult(**payload)


def _reconcile_ledger_from_evidence(
    cases: Iterable[OperatorCase],
    run_root: Path,
    metadata: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    """Recover rare missing ledger rows from already-fsynced per-case result.json files."""
    latest = latest_results(run_root / "results.jsonl")
    missing = [case for case in cases if case.case_id not in latest]
    for case in missing:
        result_path = _case_root(run_root, case) / "result.json"
        if not result_path.exists():
            continue
        result = _load_case_result(result_path)
        _append_and_checkpoint(result, run_root, metadata)
        latest[result.case_id] = result.to_dict()
    return latest


def _mark_remaining(
    cases: Iterable[OperatorCase],
    existing_latest: dict[int, dict[str, Any]],
    run_id: str,
    run_root: Path,
    metadata: dict[str, Any],
    final_status: str,
    reason: str,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        latest = existing_latest.get(case.case_id)
        if latest and latest.get("final_status") not in RETRYABLE_RESUME_STATUSES:
            continue
        result = _skip_result(run_id, run_root, case, final_status, reason, metadata["batch_status"])
        _append_and_checkpoint(result, run_root, metadata)
        existing_latest[case.case_id] = result.to_dict()
        results.append(result)
    return results


def _run_one_case(
    case: OperatorCase,
    run_id: str,
    run_root: Path,
    context: BrowserContext,
    oge: OGEDevelopPage,
    collector: NetworkCollector,
    cfg: dict,
) -> tuple[CaseResult, bool]:
    app = cfg["app"]
    max_attempts = max(1, int(app.get("max_attempts", 2)))
    retry_statuses = set(app.get("retry_final_statuses", ["FAIL", "TIMEOUT"]))
    case_root = _case_root(run_root, case)
    case_root.mkdir(parents=True, exist_ok=True)
    final_result: CaseResult | None = None
    auth_expired = False

    existing_attempts = list((case_root / "attempts").glob("attempt_*")) if (case_root / "attempts").exists() else []
    starting_attempt = len(existing_attempts) + 1
    for offset in range(max_attempts):
        attempt = starting_attempt + offset
        attempt_dir = case_root / "attempts" / f"attempt_{attempt}"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        (attempt_dir / "source.py").write_text(case.code, encoding="utf-8")
        (attempt_dir / "case.json").write_text(
            json.dumps(asdict(case), ensure_ascii=False, indent=2), encoding="utf-8"
        )

        started_at = now_iso()
        started_monotonic = time.monotonic()
        execution_status = "FAIL"
        console_entries = []
        network_summary: dict[str, Any] = {}
        records = []
        failure_reason = ""
        code_injection_mode = ""
        code_readback_match = None
        trace_started = _try_trace_start(context, bool(cfg["output"].get("save_trace", True)))
        collector.start_case(case.code)

        before_globe = attempt_dir / "globe_before.png"
        after_globe = attempt_dir / "globe_result.png"
        full_page = attempt_dir / "result_screenshot.png"
        try:
            oge.assert_workspace()
            if app.get("reload_before_each_case", True):
                oge.reload_isolated()
            oge.page.wait_for_timeout(int(app.get("pre_case_settle_ms", 500)))
            oge.screenshot_globe(str(before_globe))
            code_injection_mode, code_readback_match = oge.set_code(case.code)
            start_console = oge.console_count()

            # Ignore reload/background requests and collect only after code verification.
            collector.start_case(case.code)
            oge.click_run()
            execution_status, console_entries, failure_reason = oge.wait_for_completion(
                start_console,
                int(app.get("operator_timeout_sec", 240)),
            )
            if execution_status == "SUCCESS":
                collector.wait_until_complete(float(app.get("network_settle_timeout_sec", 30)))
                network_summary = collector.summarize()
                if network_summary.get("auth_expired"):
                    raise AuthExpiredError(str(network_summary.get("auth_signal") or "Network 认证失效"))
                if int(network_summary.get("dag_missing_count") or 0) > 0:
                    execution_status = "TIMEOUT"
                    failure_reason = "目标 DAG 未在 network_settle_timeout_sec 内全部返回"
                elif (
                    int(network_summary.get("dag_failed_count") or 0) > 0
                    or network_summary.get("code_payload_match") is False
                    or (
                        network_summary.get("execute_code_status") is not None
                        and not 200 <= int(network_summary["execute_code_status"]) < 300
                    )
                ):
                    execution_status = "FAIL"
            else:
                collector.wait_until_complete(min(2.0, float(app.get("network_settle_timeout_sec", 30))))
            oge.page.wait_for_timeout(int(app.get("render_settle_ms", 1200)))
        except AuthExpiredError as exc:
            execution_status = "AUTH_EXPIRED"
            auth_expired = True
            failure_reason = str(exc)
        except Exception as exc:
            execution_status = "FAIL"
            failure_reason = f"自动化异常: {type(exc).__name__}: {exc}"
        finally:
            records = collector.stop_case()
            network_summary = collector.summarize()
            try:
                oge.screenshot_globe(str(after_globe))
            except Exception:
                pass
            try:
                oge.screenshot_full_page(str(full_page))
            except Exception:
                pass
            _try_trace_stop(context, attempt_dir / "trace.zip", trace_started)

        finished_at = now_iso()
        duration = time.monotonic() - started_monotonic
        write_console(console_entries, attempt_dir / "console.txt")
        write_network(records, attempt_dir / "network.json")
        (attempt_dir / "network_summary.json").write_text(
            json.dumps(network_summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ensure_required_evidence(attempt_dir, case, execution_status, failure_reason or "evidence fallback")
        visual_ratio = image_change_ratio(before_globe, after_globe)
        console_text = "\n".join(entry.text for entry in console_entries)
        result_status, final_status, decision_reason = decide(
            case,
            execution_status,
            network_summary,
            visual_ratio,
            float(cfg["judging"].get("screenshot_diff_threshold", 0.01)),
            console_text,
        )
        combined_reason = "; ".join(part for part in (failure_reason, decision_reason) if part)

        _promote_attempt(attempt_dir, case_root)
        ensure_required_evidence(case_root, case, final_status, combined_reason)
        paths = _evidence_paths(run_root, case_root)
        final_result = CaseResult(
            run_id=run_id,
            **_result_base(case),
            attempt=attempt,
            retry_count=max(0, attempt - 1),
            execution_status=execution_status,
            result_status=result_status,
            final_status=final_status,
            started_at=started_at,
            finished_at=finished_at,
            duration_sec=duration,
            batch_status="RUNNING",
            execute_code_status=network_summary.get("execute_code_status"),
            execute_code_log=str(network_summary.get("execute_code_log") or ""),
            execute_code_seen=bool(network_summary.get("execute_code_seen")),
            network_complete=bool(network_summary.get("network_complete")),
            dag_count=int(network_summary.get("dag_count") or 0),
            dag_success_count=int(network_summary.get("dag_success_count") or 0),
            dag_failed_count=int(network_summary.get("dag_failed_count") or 0),
            dag_missing_count=int(network_summary.get("dag_missing_count") or 0),
            code_injection_mode=code_injection_mode,
            code_readback_match=code_readback_match,
            code_payload_match=network_summary.get("code_payload_match"),
            visual_change_ratio=visual_ratio,
            auth_signal=str(network_summary.get("auth_signal") or ""),
            failure_reason=combined_reason,
            console_entries=console_entries,
            network_records=records,
            network_summary=network_summary,
            **paths,
        )
        save_case_json(final_result, attempt_dir / "attempt_result.json")
        save_case_json(final_result, case_root / "result.json")

        if auth_expired or final_status not in retry_statuses or offset + 1 >= max_attempts:
            break
        print(f"[{case.case_id:03d}] {case.operator_name} -> {final_status}，准备第 {offset + 2} 次尝试")

    if final_result is None:
        raise RuntimeError(f"算子未产生结果: {case.case_id}")
    return final_result, auth_expired


def run_cases(
    cases: List[OperatorCase],
    cfg_path: str | Path,
    input_csv: str | Path,
    start_id: int | None = None,
    end_id: int | None = None,
    contains: str | None = None,
    resume: bool = False,
    run_id: str | None = None,
) -> List[CaseResult]:
    cfg_path = Path(cfg_path).resolve()
    input_csv = Path(input_csv).resolve()
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    base_dir = cfg_path.parent
    run_root, metadata = _prepare_run(
        cfg,
        base_dir,
        input_csv,
        start_id,
        end_id,
        contains,
        resume,
        run_id,
    )
    if resume and start_id is None and end_id is None and not contains:
        stored_selection = metadata.get("selection") or {}
        start_id = stored_selection.get("start_id")
        end_id = stored_selection.get("end_id")
        contains = stored_selection.get("contains") or None
    run_id = str(metadata["run_id"])
    results: List[CaseResult] = []
    current_latest = latest_results(run_root / "results.jsonl")
    metadata["batch_status"] = "RUNNING"
    metadata["total_records"] = len(cases)
    metadata["executable_records"] = sum(1 for case in cases if case.enabled and case.has_code)
    metadata["missing_code_records"] = sum(1 for case in cases if not case.has_code)
    atomic_write_json(run_root / "run_metadata.json", metadata)
    (run_root / "run_config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    runnable: list[OperatorCase] = []
    for case in cases:
        existing = current_latest.get(case.case_id)
        existing_status = str((existing or {}).get("final_status") or "")
        if existing and existing_status not in RETRYABLE_RESUME_STATUSES:
            continue

        if not case.enabled:
            skipped = _skip_result(run_id, run_root, case, "SKIPPED_DISABLED", "CSV enabled=false", metadata["batch_status"])
            _append_and_checkpoint(skipped, run_root, metadata)
            current_latest[case.case_id] = skipped.to_dict()
            results.append(skipped)
            continue
        if not case.has_code:
            skipped = _skip_result(
                run_id,
                run_root,
                case,
                "SKIPPED_NO_CODE",
                "缺少英文算子名或完整代码；未伪造执行",
                metadata["batch_status"],
            )
            _append_and_checkpoint(skipped, run_root, metadata)
            current_latest[case.case_id] = skipped.to_dict()
            results.append(skipped)
            continue
        if not is_selected(case, start_id, end_id, contains):
            skipped = _skip_result(
                run_id,
                run_root,
                case,
                "SKIPPED_FILTERED",
                "不在本次 start/end/contains 选择范围内",
                metadata["batch_status"],
            )
            _append_and_checkpoint(skipped, run_root, metadata)
            current_latest[case.case_id] = skipped.to_dict()
            results.append(skipped)
            continue
        runnable.append(case)

    current_latest = _reconcile_ledger_from_evidence(cases, run_root, metadata)
    if not runnable:
        metadata["batch_status"] = "COMPLETED"
        metadata["finished_at"] = now_iso()
        atomic_write_json(run_root / "run_metadata.json", metadata)
        generate_results_xlsx(cases, run_root / "results.jsonl", run_root / cfg["output"]["report_name"], metadata)
        return results

    context: BrowserContext | None = None
    remaining = list(runnable)
    try:
        with sync_playwright() as playwright:
            context = launch_persistent_context(playwright, cfg, base_dir)
            context.set_default_timeout(int(cfg["app"].get("action_timeout_ms", 60000)))
            context.set_default_navigation_timeout(int(cfg["app"].get("navigation_timeout_ms", 60000)))
            page = context.pages[0] if context.pages else context.new_page()
            oge = OGEDevelopPage(page, cfg)
            try:
                preflight = oge.open(timeout_ms=int(cfg["app"].get("workspace_wait_ms", 15000)))
                atomic_write_json(run_root / "preflight.json", {"checked_at": now_iso(), **preflight})
            except AuthExpiredError as exc:
                metadata["batch_status"] = "AUTH_EXPIRED"
                metadata["failure_reason"] = str(exc)
                results.extend(
                    _mark_remaining(
                        remaining,
                        current_latest,
                        run_id,
                        run_root,
                        metadata,
                        "SKIPPED_AUTH_EXPIRED",
                        str(exc),
                    )
                )
                remaining = []
            except WorkspaceContractError as exc:
                metadata["batch_status"] = "WORKSPACE_CONTRACT_ERROR"
                metadata["failure_reason"] = str(exc)
                results.extend(
                    _mark_remaining(
                        remaining,
                        current_latest,
                        run_id,
                        run_root,
                        metadata,
                        "SKIPPED_BATCH_ABORTED",
                        str(exc),
                    )
                )
                remaining = []

            if remaining:
                collector = NetworkCollector(
                    page,
                    cfg["network"]["execute_code_path"],
                    cfg["network"]["execute_dag_path"],
                    cfg.get("auth", {}).get("http_status_codes", [401, 403]),
                )
                for index, case in enumerate(list(remaining)):
                    result, auth_expired = _run_one_case(case, run_id, run_root, context, oge, collector, cfg)
                    _append_and_checkpoint(result, run_root, metadata)
                    current_latest[case.case_id] = result.to_dict()
                    results.append(result)
                    print(
                        f"[{result.case_id:03d}] {result.operator_name} -> "
                        f"{result.execution_status} + {result.result_status} + {result.final_status} "
                        f"({result.duration_sec:.1f}s)"
                    )
                    if auth_expired:
                        metadata["batch_status"] = "AUTH_EXPIRED"
                        metadata["failure_reason"] = result.failure_reason
                        tail = remaining[index + 1 :]
                        results.extend(
                            _mark_remaining(
                                tail,
                                current_latest,
                                run_id,
                                run_root,
                                metadata,
                                "SKIPPED_AUTH_EXPIRED",
                                result.failure_reason,
                            )
                        )
                        remaining = []
                        break
                else:
                    remaining = []
                    metadata["batch_status"] = "COMPLETED"
    except Exception as exc:
        metadata["batch_status"] = "BATCH_ABORTED"
        metadata["failure_reason"] = f"批次异常: {type(exc).__name__}: {exc}"
        pending = [
            case
            for case in runnable
            if case.case_id not in current_latest
            or current_latest[case.case_id].get("final_status") in RETRYABLE_RESUME_STATUSES
        ]
        results.extend(
            _mark_remaining(
                pending,
                current_latest,
                run_id,
                run_root,
                metadata,
                "SKIPPED_BATCH_ABORTED",
                metadata["failure_reason"],
            )
        )
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass

    current_latest = _reconcile_ledger_from_evidence(cases, run_root, metadata)
    if len(current_latest) != len(cases):
        metadata["batch_status"] = "BATCH_ABORTED"
        metadata["failure_reason"] = (
            f"最终账本对账失败：总数={len(cases)}，results.jsonl 最新记录数={len(current_latest)}"
        )
    metadata["finished_at"] = now_iso()
    atomic_write_json(run_root / "run_metadata.json", metadata)
    generate_results_xlsx(
        cases,
        run_root / "results.jsonl",
        run_root / cfg["output"]["report_name"],
        metadata,
    )
    print(f"本次运行目录: {run_root}")
    print(f"JSONL/CSV 已逐条持久化；Excel 汇总: {run_root / cfg['output']['report_name']}")
    return results

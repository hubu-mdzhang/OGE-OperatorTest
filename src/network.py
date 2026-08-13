from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, Request, Response

from .models import NetworkRecord
from .utils import normalize_code


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class NetworkCollector:
    """Capture one case and bind executeCode DAG IDs to executeDag responses."""

    def __init__(
        self,
        page: Page,
        execute_code_path: str,
        execute_dag_path: str,
        auth_status_codes: list[int] | None = None,
    ):
        self.page = page
        self.execute_code_path = execute_code_path
        self.execute_dag_path = execute_dag_path
        self.auth_status_codes = set(auth_status_codes or [401, 403])
        self.records: List[NetworkRecord] = []
        self.expected_code = ""
        self.active = False
        self.auth_expired = False
        self.auth_signal = ""
        self._sequence = 0
        self._by_request: Dict[int, NetworkRecord] = {}
        self._started_monotonic: Dict[str, float] = {}
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)
        self.page.on("requestfailed", self._on_request_failed)

    def start_case(self, expected_code: str) -> None:
        self.records = []
        self.expected_code = expected_code
        self.active = True
        self.auth_expired = False
        self.auth_signal = ""
        self._sequence = 0
        self._by_request = {}
        self._started_monotonic = {}

    def stop_case(self) -> List[NetworkRecord]:
        self.active = False
        return list(self.records)

    def _kind(self, url: str) -> Optional[str]:
        path = urlparse(url).path
        if path.endswith(self.execute_code_path) or self.execute_code_path in path:
            return "executeCode"
        if path.endswith(self.execute_dag_path) or self.execute_dag_path in path:
            return "executeDag"
        return None

    @staticmethod
    def _dag_id(url: str) -> str:
        try:
            return (parse_qs(urlparse(url).query).get("dagId") or [""])[0]
        except Exception:
            return ""

    @staticmethod
    def _json_or_none(text: str | None) -> Optional[Any]:
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    def _new_record(self, request: Request, kind: str) -> NetworkRecord:
        self._sequence += 1
        record_id = f"net-{self._sequence:04d}"
        request_text = request.post_data or ""
        record = NetworkRecord(
            record_id=record_id,
            kind=kind,
            method=request.method,
            url=request.url,
            request_json=self._json_or_none(request_text),
            request_text=request_text,
            dag_id=self._dag_id(request.url) if kind == "executeDag" else "",
            started_at=now_iso(),
        )
        self.records.append(record)
        self._by_request[id(request)] = record
        self._started_monotonic[record_id] = time.monotonic()
        return record

    def _on_request(self, request: Request) -> None:
        if not self.active:
            return
        kind = self._kind(request.url)
        if kind:
            self._new_record(request, kind)

    def _find_record(self, request: Request, kind: str) -> NetworkRecord:
        record = self._by_request.get(id(request))
        if record is not None:
            return record
        dag_id = self._dag_id(request.url) if kind == "executeDag" else ""
        for candidate in reversed(self.records):
            if (
                candidate.kind == kind
                and candidate.url == request.url
                and candidate.status is None
                and not candidate.error
                and (kind != "executeDag" or candidate.dag_id == dag_id)
            ):
                self._by_request[id(request)] = candidate
                return candidate
        return self._new_record(request, kind)

    def _mark_auth(self, status: int, url: str) -> None:
        if status not in self.auth_status_codes:
            return
        path = urlparse(url).path.lower()
        if "/api/" in path or self.execute_code_path.lower() in path or self.execute_dag_path.lower() in path:
            self.auth_expired = True
            self.auth_signal = f"HTTP {status}: {url}"

    def _on_response(self, response: Response) -> None:
        if not self.active:
            return
        self._mark_auth(response.status, response.url)
        kind = self._kind(response.url)
        if not kind:
            return
        record = self._find_record(response.request, kind)
        try:
            response_text = response.text()
        except Exception as exc:
            response_text = ""
            record.error = f"读取响应失败: {type(exc).__name__}: {exc}"

        record.status = response.status
        record.response_text = response_text
        record.response_json = self._json_or_none(response_text)
        record.finished_at = now_iso()
        started = self._started_monotonic.get(record.record_id)
        if started is not None:
            record.duration_ms = round((time.monotonic() - started) * 1000.0, 3)

    def _on_request_failed(self, request: Request) -> None:
        if not self.active:
            return
        kind = self._kind(request.url)
        if not kind:
            return
        record = self._find_record(request, kind)
        failure = request.failure
        record.error = str(failure or "request failed")
        record.finished_at = now_iso()
        started = self._started_monotonic.get(record.record_id)
        if started is not None:
            record.duration_ms = round((time.monotonic() - started) * 1000.0, 3)

    def _latest_execute_code(self) -> Optional[NetworkRecord]:
        records = [record for record in self.records if record.kind == "executeCode"]
        return records[-1] if records else None

    @classmethod
    def _flatten_dag_ids(cls, value: Any) -> set[str]:
        output: set[str] = set()
        if value is None:
            return output
        if isinstance(value, dict):
            for child in value.values():
                output.update(cls._flatten_dag_ids(child))
            return output
        if isinstance(value, (list, tuple, set)):
            for child in value:
                output.update(cls._flatten_dag_ids(child))
            return output
        if isinstance(value, (str, int)) and str(value).strip():
            output.add(str(value).strip())
        return output

    @staticmethod
    def _payload_status(payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("status", "state", "resultStatus"):
                value = payload.get(key)
                if value not in (None, ""):
                    return str(value).strip().lower()
            data = payload.get("data")
            if isinstance(data, dict):
                return NetworkCollector._payload_status(data)
            if payload.get("success") is True:
                return "success"
        return ""

    @staticmethod
    def _extract_error(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        for key in ("error", "message", "detail", "msg"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    def summarize(self) -> dict:
        execute_code = self._latest_execute_code()
        execute_dag = [record for record in self.records if record.kind == "executeDag"]
        code_payload_match = None
        execute_code_log = ""
        execute_code_status = None
        execute_code_error = ""
        dags_payload: Any = None

        if execute_code is not None:
            execute_code_status = execute_code.status
            if isinstance(execute_code.request_json, dict) and "code" in execute_code.request_json:
                submitted = str(execute_code.request_json.get("code") or "")
                code_payload_match = normalize_code(submitted) == normalize_code(self.expected_code)
            if isinstance(execute_code.response_json, dict):
                execute_code_log = str(execute_code.response_json.get("log") or "")
                dags_payload = execute_code.response_json.get("dags")
                execute_code_error = self._extract_error(execute_code.response_json)
            if execute_code.error and not execute_code_error:
                execute_code_error = execute_code.error

        expected_dag_ids = self._flatten_dag_ids(dags_payload)
        dag_by_id: Dict[str, NetworkRecord] = {}
        unexpected_dag_ids: set[str] = set()
        for record in execute_dag:
            if not record.dag_id:
                continue
            if record.dag_id not in expected_dag_ids:
                unexpected_dag_ids.add(record.dag_id)
                continue
            previous = dag_by_id.get(record.dag_id)
            if previous is None or (previous.status is None and record.status is not None):
                dag_by_id[record.dag_id] = record

        success_ids: set[str] = set()
        failed_ids: set[str] = set()
        responded_ids: set[str] = set()
        for dag_id, record in dag_by_id.items():
            if record.status is None and not record.error:
                continue
            responded_ids.add(dag_id)
            payload_status = self._payload_status(record.response_json)
            if record.status is not None and 200 <= int(record.status) < 300 and payload_status == "success":
                success_ids.add(dag_id)
            else:
                failed_ids.add(dag_id)

        missing_ids = expected_dag_ids - responded_ids
        execute_code_response_seen = bool(execute_code and execute_code.status is not None)
        network_complete = execute_code_response_seen and not missing_ids
        return {
            "execute_code_seen": execute_code is not None,
            "execute_code_response_seen": execute_code_response_seen,
            "execute_code_status": execute_code_status,
            "execute_code_log": execute_code_log,
            "execute_code_error": execute_code_error,
            "dag_count": len(expected_dag_ids),
            "dag_success_count": len(success_ids),
            "dag_failed_count": len(failed_ids),
            "dag_missing_count": len(missing_ids),
            "expected_dag_ids": sorted(expected_dag_ids),
            "dag_success_ids": sorted(success_ids),
            "dag_failed_ids": sorted(failed_ids),
            "dag_missing_ids": sorted(missing_ids),
            "unexpected_dag_ids": sorted(unexpected_dag_ids),
            "code_payload_match": code_payload_match,
            "network_complete": network_complete,
            "auth_expired": self.auth_expired,
            "auth_signal": self.auth_signal,
        }

    def wait_until_complete(self, timeout_sec: float) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_sec))
        while time.monotonic() < deadline:
            summary = self.summarize()
            if summary["network_complete"] or summary["auth_expired"]:
                return bool(summary["network_complete"])
            self.page.wait_for_timeout(100)
        return bool(self.summarize()["network_complete"])

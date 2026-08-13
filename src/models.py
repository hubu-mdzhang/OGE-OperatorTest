from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .utils import safe_slug


@dataclass
class OperatorCase:
    case_id: int
    category: str
    name_cn: str
    operator_name: str
    code: str
    expected_result_type: str = "UNKNOWN"
    enabled: bool = True
    source_status: str = "READY"
    source_original_status: str = ""
    source_development_status: str = ""
    source_manual_test_status: str = ""
    description: str = ""
    input_data_type: str = ""
    source_notes: str = ""
    validation_mode: str = "MANUAL_OR_MULTIMODAL"
    expected_console_regex: str = ""
    source_row: int = 0
    source: str = ""

    @property
    def slug(self) -> str:
        name = self.operator_name or self.name_cn or "no-code"
        return f"{self.case_id:03d}_{safe_slug(name)}"

    @property
    def has_code(self) -> bool:
        return bool(self.operator_name.strip() and self.code.strip())


@dataclass
class ConsoleEntry:
    index: int
    type: str
    text: str
    captured_at: str = ""


@dataclass
class NetworkRecord:
    record_id: str
    kind: str
    method: str
    url: str
    status: Optional[int] = None
    request_json: Optional[Any] = None
    response_json: Optional[Any] = None
    request_text: str = ""
    response_text: str = ""
    dag_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: Optional[float] = None
    error: str = ""


@dataclass
class CaseResult:
    run_id: str
    case_id: int
    category: str
    name_cn: str
    operator_name: str
    expected_result_type: str
    enabled: bool
    source_status: str
    source_original_status: str
    source_development_status: str
    source_manual_test_status: str
    attempt: int
    retry_count: int
    execution_status: str
    result_status: str
    final_status: str
    started_at: str
    finished_at: str
    duration_sec: float
    batch_status: str = "RUNNING"
    execute_code_status: Optional[int] = None
    execute_code_log: str = ""
    execute_code_seen: bool = False
    network_complete: bool = False
    dag_count: int = 0
    dag_success_count: int = 0
    dag_failed_count: int = 0
    dag_missing_count: int = 0
    code_injection_mode: str = ""
    code_readback_match: Optional[bool] = None
    code_payload_match: Optional[bool] = None
    visual_change_ratio: Optional[float] = None
    auth_signal: str = ""
    failure_reason: str = ""
    evidence_dir: str = ""
    source_path: str = ""
    result_path: str = ""
    console_path: str = ""
    network_path: str = ""
    trace_path: str = ""
    result_screenshot_path: str = ""
    globe_result_path: str = ""
    console_entries: List[ConsoleEntry] = field(default_factory=list)
    network_records: List[NetworkRecord] = field(default_factory=list)
    network_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


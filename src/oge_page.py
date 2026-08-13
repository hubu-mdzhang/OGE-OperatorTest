from __future__ import annotations

import re
import time
from datetime import datetime
from typing import List

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from .models import ConsoleEntry
from .utils import normalize_code


_STRONG_ERROR_RE = re.compile(
    r"(?:traceback\s*\(most recent call last\)|"
    r"\b(?:syntaxerror|typeerror|valueerror|runtimeerror|nameerror|attributeerror|keyerror|"
    r"indexerror|importerror|modulenotfounderror|zerodivisionerror|memoryerror|oserror)\b|"
    r"\bexception\b|执行失败|运行失败|代码执行异常|服务端异常)",
    re.IGNORECASE,
)


class AuthExpiredError(RuntimeError):
    pass


class WorkspaceContractError(RuntimeError):
    pass


class CodeVerificationError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class OGEDevelopPage:
    def __init__(self, page: Page, cfg: dict):
        self.page = page
        self.cfg = cfg
        self.sel = cfg["selectors"]
        self.judging = cfg["judging"]
        self.auth_cfg = cfg.get("auth", {})

    def _login_url_detected(self) -> bool:
        url = (self.page.url or "").lower()
        markers = self.auth_cfg.get("login_url_markers", ["/login", "/signin", "/auth"])
        return any(str(marker).lower() in url for marker in markers)

    def workspace_probe(self) -> dict:
        editor = self.page.locator(self.sel["editor_root"]).filter(visible=True).count()
        textarea = self.page.locator(self.sel["editor_textarea"]).count()
        console = self.page.locator(self.sel["console_root"]).count()
        globe = self.page.locator(self.sel["globe_canvas"]).filter(visible=True).count()
        try:
            run_button = self._run_button().count()
        except Exception:
            run_button = 0
        return {
            "url": self.page.url,
            "editor": editor,
            "editor_textarea": textarea,
            "console": console,
            "run_button": run_button,
            "globe": globe,
        }

    def assert_workspace(self) -> dict:
        if self._login_url_detected():
            raise AuthExpiredError(f"页面已跳转到登录入口: {self.page.url}")
        probe = self.workspace_probe()
        missing = [key for key in ("editor", "editor_textarea", "console", "run_button", "globe") if not probe[key]]
        if not missing:
            return probe
        if not probe["editor"] and not probe["console"]:
            raise AuthExpiredError(f"OGE 工作区已消失，可能登录失效；缺少: {', '.join(missing)}")
        raise WorkspaceContractError(f"OGE 页面契约不完整；缺少: {', '.join(missing)}")

    def wait_for_workspace(self, timeout_ms: int) -> dict:
        deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
        last_error = ""
        while time.monotonic() < deadline:
            try:
                return self.assert_workspace()
            except (AuthExpiredError, WorkspaceContractError) as exc:
                last_error = str(exc)
                self.page.wait_for_timeout(250)
        if self._login_url_detected():
            raise AuthExpiredError(last_error or f"等待工作区超时，当前为登录页: {self.page.url}")
        raise AuthExpiredError(last_error or "等待 OGE 工作区超时；请先运行 login.bat 完成人工登录")

    def open(self, timeout_ms: int | None = None) -> dict:
        self.page.goto(
            self.cfg["app"]["url"],
            wait_until="domcontentloaded",
            timeout=int(self.cfg["app"].get("navigation_timeout_ms", 60000)),
        )
        wait_ms = int(timeout_ms or self.cfg["app"].get("workspace_wait_ms", 15000))
        return self.wait_for_workspace(wait_ms)

    def reload_isolated(self) -> dict:
        self.page.reload(
            wait_until="domcontentloaded",
            timeout=int(self.cfg["app"].get("navigation_timeout_ms", 60000)),
        )
        return self.wait_for_workspace(int(self.cfg["app"].get("workspace_wait_ms", 15000)))

    def _read_monaco_model(self) -> dict:
        result = self.page.evaluate(
            """
            () => {
              try {
                const roots = Array.from(document.querySelectorAll('.monaco-editor[role="code"]'))
                  .filter(el => {
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                  });
                const root = roots[0];
                if (!root || !window.monaco || !window.monaco.editor) {
                  return {ok:false, reason:'monaco-not-global'};
                }
                const uri = root.getAttribute('data-uri');
                const models = window.monaco.editor.getModels();
                let model = models.find(item => item.uri && item.uri.toString() === uri);
                if (!model && models.length === 1) model = models[0];
                if (!model) return {ok:false, reason:'model-not-found'};
                return {ok:true, value:model.getValue(), uri:model.uri ? model.uri.toString() : ''};
              } catch (error) {
                return {ok:false, reason:String(error)};
              }
            }
            """
        )
        return result if isinstance(result, dict) else {"ok": False, "reason": "invalid-evaluate-result"}

    def set_code(self, code: str) -> tuple[str, bool]:
        result = self.page.evaluate(
            """
            (code) => {
              try {
                const roots = Array.from(document.querySelectorAll('.monaco-editor[role="code"]'))
                  .filter(el => {
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                  });
                const root = roots[0];
                if (!root || !window.monaco || !window.monaco.editor) {
                  return {ok:false, reason:'monaco-not-global'};
                }
                const uri = root.getAttribute('data-uri');
                const models = window.monaco.editor.getModels();
                let model = models.find(item => item.uri && item.uri.toString() === uri);
                if (!model && models.length === 1) model = models[0];
                if (!model) return {ok:false, reason:'model-not-found'};
                model.setValue(code);
                return {ok:true, value:model.getValue()};
              } catch (error) {
                return {ok:false, reason:String(error)};
              }
            }
            """,
            code,
        )
        if isinstance(result, dict) and result.get("ok"):
            matched = normalize_code(str(result.get("value") or "")) == normalize_code(code)
            if not matched:
                raise CodeVerificationError("Monaco Model API 写入后回读不一致")
            return "monaco_model_api", True

        textarea = self.page.locator(self.sel["editor_textarea"]).filter(visible=True).first
        textarea.wait_for(state="visible")
        textarea.click()
        textarea.press("Control+A")
        textarea.press("Backspace")
        self.page.keyboard.insert_text(code)
        self.page.wait_for_timeout(300)
        readback = self._read_monaco_model()
        if readback.get("ok"):
            matched = normalize_code(str(readback.get("value") or "")) == normalize_code(code)
            if not matched:
                raise CodeVerificationError("textarea 写入后 Monaco 完整代码回读不一致")
            return "monaco_textarea_keyboard", True

        # 真实 OGE 页面不暴露 window.monaco：Monaco 虚拟化渲染导致无法一次性全量回读，
        # 改用渲染区校验：末尾区域必须等于代码后缀，回到顶部后头部区域必须等于代码前缀。
        # 短代码两端渲染区覆盖全文，等效全量校验；长代码由运行后 executeCode 载荷比对兜底。
        tail = self._read_rendered_region()
        if not self._region_matches(code, tail, head=False):
            raise CodeVerificationError(
                "键盘注入后编辑器尾部渲染区与预期代码不一致"
                f"（渲染区长度 {len(tail)}），拒绝在未验证状态下运行"
            )
        self.page.keyboard.press("Control+Home")
        self.page.wait_for_timeout(300)
        head = self._read_rendered_region()
        if not self._region_matches(code, head, head=True):
            raise CodeVerificationError(
                "键盘注入后编辑器头部渲染区与预期代码不一致"
                f"（渲染区长度 {len(head)}），拒绝在未验证状态下运行"
            )
        return "monaco_textarea_keyboard", True

    def _read_rendered_region(self) -> str:
        value = self.page.evaluate(
            """
            () => {
              const root = document.querySelector('.monaco-editor[role="code"]');
              const view = root ? root.querySelector('.view-lines') : null;
              return view ? view.innerText : '';
            }
            """
        )
        return (value or "").replace(" ", " ")

    @staticmethod
    def _region_matches(code: str, region: str, head: bool) -> bool:
        region_norm = normalize_code(region)
        if not region_norm:
            return False
        base = normalize_code(code)
        if head:
            return region_norm == base[: len(region_norm)]
        return region_norm == base[-len(region_norm):]

    def _run_button(self) -> Locator:
        primary = self.page.locator(self.sel["run_button_primary"]).filter(has_text="运行").filter(visible=True)
        if primary.count() == 1:
            return primary
        if primary.count() > 1:
            raise WorkspaceContractError(f"运行按钮定位到多个可见候选: {primary.count()}")

        icon = self.page.locator(self.sel["run_button_fallback"]).filter(visible=True)
        if icon.count() == 1:
            ancestor = icon.locator(
                "xpath=ancestor::div[contains(@class,'controlButton_oge_editor_control_btn__')][1]"
            )
            if ancestor.count() == 1:
                return ancestor
        text_locator = self.page.get_by_text("运行", exact=True).filter(visible=True)
        if text_locator.count() == 1:
            return text_locator
        raise WorkspaceContractError(
            f"无法唯一定位运行按钮：primary={primary.count()}, icon={icon.count()}, text={text_locator.count()}"
        )

    def click_run(self) -> None:
        button = self._run_button()
        button.wait_for(state="visible")
        button.click()

    def _console_root(self) -> Locator:
        root = self.page.locator(self.sel["console_root"]).filter(visible=True)
        if root.count() == 1:
            return root
        root = self.page.locator(self.sel["console_root"])
        if root.count() >= 1:
            return root.first
        if self._login_url_detected():
            raise AuthExpiredError(f"控制台消失且页面已跳转登录: {self.page.url}")
        raise AuthExpiredError("未找到控制台根节点，工作区可能因登录失效而消失")

    def console_count(self) -> int:
        return self._console_root().locator(self.sel["console_entry"]).count()

    def read_console_since(self, start_index: int) -> List[ConsoleEntry]:
        entries = self._console_root().locator(self.sel["console_entry"])
        output: List[ConsoleEntry] = []
        for index in range(start_index, entries.count()):
            item = entries.nth(index)
            data_type = (item.get_attribute("data-type") or "").strip().lower()
            content = item.locator(self.sel["console_content"])
            text_value = content.inner_text().strip() if content.count() else item.inner_text().strip()
            output.append(ConsoleEntry(index=index, type=data_type, text=text_value, captured_at=now_iso()))
        return output

    def wait_for_completion(self, start_index: int, timeout_sec: int) -> tuple[str, List[ConsoleEntry], str]:
        deadline = time.monotonic() + timeout_sec
        seen_running = False
        all_new: List[ConsoleEntry] = []
        running_marker = self.judging["running_text_contains"]
        success_marker = self.judging["success_text_contains"]
        require_running = bool(self.judging.get("require_running_before_success", True))

        while time.monotonic() < deadline:
            if self._login_url_detected():
                raise AuthExpiredError(f"运行过程中跳转到登录页: {self.page.url}")
            current = self.read_console_since(start_index)
            all_new = current
            for entry in current:
                if running_marker and running_marker in entry.text:
                    seen_running = True
                if entry.type == "error" or _STRONG_ERROR_RE.search(entry.text):
                    return "FAIL", current, entry.text
                if entry.type == "success" and success_marker in entry.text:
                    if not require_running or seen_running:
                        return "SUCCESS", current, ""
            self.page.wait_for_timeout(250)

        reason = "等待本次运行结束超时"
        if not seen_running:
            reason += "；未检测到本次运行的运行中日志"
        return "TIMEOUT", all_new, reason

    def screenshot_globe(self, path: str) -> bool:
        canvas = self.page.locator(self.sel["globe_canvas"]).filter(visible=True)
        candidates = [canvas.nth(index) for index in range(canvas.count())]
        if not candidates:
            return False

        def area(locator: Locator) -> float:
            box = locator.bounding_box()
            return float((box or {}).get("width", 0)) * float((box or {}).get("height", 0))

        best = max(candidates, key=area)
        best.screenshot(path=path, animations="disabled")
        return True

    def screenshot_full_page(self, path: str) -> None:
        self.page.screenshot(path=path, full_page=True, animations="disabled")

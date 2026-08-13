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


_DROP_INJECT_JS = """
(code) => {
  const root = document.querySelector('.monaco-editor[role="code"]');
  if (!root) return 'no-root';
  const rect = root.getBoundingClientRect();
  const dt = new DataTransfer();
  dt.setData('text/plain', code);
  const opts = {
    bubbles: true,
    cancelable: true,
    dataTransfer: dt,
    clientX: rect.left + 120,
    clientY: rect.top + 80,
    pageX: rect.left + 120,
    pageY: rect.top + 80,
  };
  root.dispatchEvent(new DragEvent('dragenter', opts));
  root.dispatchEvent(new DragEvent('dragover', opts));
  root.dispatchEvent(new DragEvent('drop', opts));
}
"""


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
        self._wait_render_settle()
        self._focus_editor()
        self.page.keyboard.press("Control+A")
        self.page.keyboard.press("Backspace")
        # 键盘输入(insert_text/type)会触发 Monaco 自动缩进与自动补全括号，改写代码内容；
        # 粘贴在真实页面上不可用(合成 Ctrl+V 不投递剪贴板)。改为合成拖放注入：
        # Monaco 的 drop 处理按原文插入，绕过打字管线。
        self.page.evaluate(_DROP_INJECT_JS, code)
        self.page.wait_for_timeout(300)
        # 校验:全选后 textarea 镜像。短代码镜像=全文逐字符比对；
        # 长代码镜像被 Monaco 截断为 前缀+…+后缀，按省略号切分后分别比对前缀/后缀。
        # 运行后 executeCode 载荷逐字符比对仍是最终权威。
        self.page.keyboard.press("Control+A")
        self.page.wait_for_timeout(200)
        mirror = textarea.input_value()
        if not self._mirror_matches(code, mirror):
            raise CodeVerificationError(
                "拖放注入后全选镜像与预期代码不一致"
                f"（镜像长度 {len(mirror)}，开头: {mirror[:80]!r}），拒绝在未验证状态下运行"
            )
        return "monaco_drop", True

    def _wait_render_settle(self, max_wait_ms: int = 8000) -> None:
        # OGE 页面加载后会异步恢复编辑器上次的代码；若在恢复完成前注入，
        # 恢复动作会覆盖刚注入的内容。等待渲染区连续两次读取一致视为恢复完成。
        deadline = time.monotonic() + max_wait_ms / 1000.0
        last: str | None = None
        stable = 0
        while time.monotonic() < deadline:
            current = self._read_rendered_region()
            if current == last:
                stable += 1
                if stable >= 2:
                    return
            else:
                stable = 0
                last = current
            self.page.wait_for_timeout(400)

    def _focus_editor(self) -> None:
        # 真实页面上直接点击 1x1 隐藏 textarea 的焦点可能落空(实测会跑到 dock-bar)，
        # 键盘输入随之全部丢失。改为点击编辑器可见区域，并校验焦点确实进入 Monaco textarea。
        editor_root = self.page.locator(self.sel["editor_root"]).filter(visible=True).first
        editor_root.wait_for(state="visible")
        focus_probe = """
        () => {
          const a = document.activeElement;
          return a ? a.tagName + '|' + (a.className || '') : '';
        }
        """
        for _ in range(3):
            try:
                editor_root.click(position={"x": 100, "y": 50})
            except PlaywrightTimeoutError:
                pass
            self.page.wait_for_timeout(200)
            focused = self.page.evaluate(focus_probe)
            if focused.startswith("TEXTAREA|") and "inputarea" in focused:
                return
        try:
            fallback_textarea = self.page.locator(self.sel["editor_textarea"]).filter(visible=True).first
            fallback_textarea.click()
        except PlaywrightTimeoutError:
            pass
        focused = self.page.evaluate(focus_probe)
        if not (focused.startswith("TEXTAREA|") and "inputarea" in focused):
            raise CodeVerificationError(f"无法将焦点定位到 Monaco 编辑器（当前焦点: {focused}）")

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
    def _mirror_matches(code: str, mirror: str) -> bool:
        norm_code = normalize_code(code)
        norm_mirror = normalize_code(mirror)
        if not norm_mirror:
            return False
        if norm_mirror == norm_code:
            return True
        for idx, ch in enumerate(norm_mirror):
            if ch == "…":
                left, right = norm_mirror[:idx], norm_mirror[idx + 1 :]
                if left and right and norm_code.startswith(left) and norm_code.endswith(right):
                    return True
        return False

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

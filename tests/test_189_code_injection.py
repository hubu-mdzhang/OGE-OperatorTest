from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.loader import load_cases
from src.oge_page import OGEDevelopPage
from src.utils import normalize_code
from tests.mock_oge import HTML, find_browser_executable, playwright_chromium_ready


CFG = {
    "app": {"workspace_wait_ms": 5000, "navigation_timeout_ms": 5000, "url": "about:blank"},
    "auth": {"login_url_markers": ["/login"]},
    "selectors": {
        "editor_root": '.monaco-editor[role="code"]',
        "editor_textarea": '.monaco-editor textarea.inputarea',
        "run_button_primary": 'div[class*="controlButton_oge_editor_control_btn__"]:has(img[src="/svgs/run.svg"])',
        "run_button_fallback": 'img[src="/svgs/run.svg"]',
        "console_root": 'div[class*="console_oge_console__"]',
        "console_entry": 'div[class*="console_entry__"]',
        "console_content": 'span[class*="console_content__"]',
        "globe_canvas": 'canvas[style*="image-rendering: pixelated"]',
    },
    "judging": {"running_text_contains": "正在执行python代码模版", "success_text_contains": "运行成功"},
}


def test_all_189_operator_codes_roundtrip_through_monaco():
    root = Path(__file__).resolve().parents[1]
    cases = [case for case in load_cases(root / "input" / "operators.csv") if case.has_code]
    assert len(cases) == 189
    executable = find_browser_executable()
    with sync_playwright() as playwright:
        if not executable and not playwright_chromium_ready(playwright):
            pytest.skip("当前环境没有可用 Chromium/Edge")
        kwargs = {"headless": True}
        if executable:
            kwargs["executable_path"] = executable
        browser = playwright.chromium.launch(**kwargs)
        page = browser.new_page()
        page.set_content(HTML, wait_until="load")
        oge = OGEDevelopPage(page, CFG)
        for case in cases:
            mode, matched = oge.set_code(case.code)
            assert mode == "monaco_model_api"
            assert matched is True
            actual = page.evaluate("window.monaco.editor.getModels()[0].getValue()")
            assert normalize_code(actual) == normalize_code(case.code), case.operator_name
        browser.close()

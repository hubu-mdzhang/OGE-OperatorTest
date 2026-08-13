from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.oge_page import OGEDevelopPage
from src.runner import launch_persistent_context

MARKER = "OGE_PROBE_MARKER_7f3a"
TEST_CODE = f"# {MARKER}\n" + "\n".join(f"# line {i:03d} test code {'x' * 30}" for i in range(1, 41))

READ_STATE_JS = """
() => {
  const root = document.querySelector('.monaco-editor[role="code"]');
  const ta = root ? root.querySelector('textarea.inputarea') : null;
  const view = root ? root.querySelector('.view-lines') : null;
  const storage = {};
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      const v = localStorage.getItem(k) || '';
      storage[k] = v.length > 5000 ? v.slice(0, 5000) + '...[TRUNC]' : v;
    }
  } catch (e) { storage.error = String(e); }
  return {
    textarea: ta ? ta.value : null,
    viewLines: view ? view.innerText : null,
    localStorageKeys: Object.keys(localStorage),
    localStorage: storage,
  };
}
"""


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    with sync_playwright() as playwright:
        context = launch_persistent_context(playwright, cfg, ROOT)
        page = context.pages[0] if context.pages else context.new_page()
        oge = OGEDevelopPage(page, cfg)
        probe = oge.open()
        print("工作区契约:", json.dumps(probe, ensure_ascii=False))

        textarea = page.locator(cfg["selectors"]["editor_textarea"]).filter(visible=True).first
        textarea.click()
        page.wait_for_timeout(500)
        page.keyboard.press("Control+A")
        page.wait_for_timeout(300)
        original = page.evaluate("() => { const t = document.querySelector('.monaco-editor[role=code] textarea.inputarea'); return t ? t.value : null; }") or ""
        print(f"originalLen={len(original)}")

        print("--- 注入带 MARKER 的 40 行代码 ---")
        page.keyboard.insert_text(TEST_CODE)
        page.wait_for_timeout(2000)

        print("--- 检查 localStorage 是否持久化了编辑器代码 ---")
        state = page.evaluate(READ_STATE_JS)
        storage_hits = {}
        for k, v in state["localStorage"].items():
            if isinstance(v, str) and MARKER in v:
                storage_hits[k] = {"len": len(v), "exact": v == TEST_CODE}
        print("localStorage keys:", state["localStorageKeys"])
        print("包含 MARKER 的 storage:", json.dumps(storage_hits, ensure_ascii=False))

        print("--- 检查 textarea 镜像与 view-lines ---")
        ta = state["textarea"] or ""
        vl = (state["viewLines"] or "").replace(" ", " ")
        lcp = 0
        for a, b in zip(ta, TEST_CODE):
            if a == b:
                lcp += 1
            else:
                break
        print(f"textarea len={len(ta)} lcp_with_code={lcp}")
        print(f"viewLines len={len(vl)} viewlines_in_code={vl in TEST_CODE}")

        print("--- 还原 ---")
        page.keyboard.press("Control+A")
        page.keyboard.insert_text(original)
        page.wait_for_timeout(300)

        context.close()


if __name__ == "__main__":
    main()

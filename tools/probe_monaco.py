from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.oge_page import OGEDevelopPage
from src.runner import launch_persistent_context

DROP_EVENT_JS = """
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

READ_MIRROR_JS = """
() => {
  const root = document.querySelector('.monaco-editor[role="code"]');
  const ta = root ? root.querySelector('textarea.inputarea') : null;
  return ta ? ta.value : '';
}
"""

READ_REGION_JS = """
() => {
  const root = document.querySelector('.monaco-editor[role="code"]');
  const view = root ? root.querySelector('.view-lines') : null;
  return (view ? view.innerText : '').replace(/\\u00a0/g, ' ').replace(/\\u200c/g, '');
}
"""


def main() -> None:
    rows = list(csv.DictReader(open(ROOT / "input" / "operators.csv", encoding="utf-8-sig")))
    code149 = next(r["code"] for r in rows if int(r["case_id"]) == 149)
    print(f"149: {len(code149)} 字符")

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    with sync_playwright() as playwright:
        context = launch_persistent_context(playwright, cfg, ROOT)
        page = context.pages[0] if context.pages else context.new_page()
        oge = OGEDevelopPage(page, cfg)
        oge.open()
        page.wait_for_timeout(3000)

        editor_root = page.locator(cfg["selectors"]["editor_root"]).filter(visible=True).first
        editor_root.click(position={"x": 100, "y": 50})
        page.wait_for_timeout(300)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(300)

        page.evaluate(DROP_EVENT_JS, code149)
        page.wait_for_timeout(2000)

        page.keyboard.press("Control+A")
        page.wait_for_timeout(400)
        mirror = page.evaluate(READ_MIRROR_JS) or ""
        (ROOT / "output" / "probe_149_mirror.txt").write_text(mirror, encoding="utf-8")
        print(f"mirror len={len(mirror)}")
        print("mirror head:", repr(mirror[:100]))
        print("mirror tail:", repr(mirror[-100:]))

        page.keyboard.press("Control+End")
        page.wait_for_timeout(800)
        tail = page.evaluate(READ_REGION_JS) or ""
        (ROOT / "output" / "probe_149_tail.txt").write_text(tail, encoding="utf-8")
        print(f"tail region len={len(tail)} head: {tail[:80]!r}")

        context.close()


if __name__ == "__main__":
    main()

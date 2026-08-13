from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

from src.oge_page import OGEDevelopPage
from src.runner import launch_persistent_context


def main() -> None:
    root = Path(__file__).resolve().parent
    cfg = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    timeout_ms = int(cfg.get("auth", {}).get("interactive_login_timeout_ms", 600000))
    with sync_playwright() as playwright:
        context = launch_persistent_context(playwright, cfg, root)
        context.set_default_timeout(int(cfg["app"].get("action_timeout_ms", 60000)))
        page = context.pages[0] if context.pages else context.new_page()
        oge = OGEDevelopPage(page, cfg)
        print("请在打开的 Edge 中人工登录 OGE；程序不会读取或保存用户名/密码。")
        probe = oge.open(timeout_ms=timeout_ms)
        state_path = root / "runtime" / "storage_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_path))
        (root / "runtime" / "login_verified.json").write_text(
            json.dumps(
                {
                    "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "url": page.url,
                    "workspace": probe,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print("登录态验证成功：Monaco、Console、运行按钮和 Globe 均已检测到。")
        context.close()


if __name__ == "__main__":
    main()

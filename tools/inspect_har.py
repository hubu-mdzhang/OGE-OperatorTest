from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


def main() -> None:
    ap = argparse.ArgumentParser(description="检查 OGE HAR 中的算子执行接口")
    ap.add_argument("har")
    args = ap.parse_args()

    data = json.loads(Path(args.har).read_text(encoding="utf-8-sig"))
    entries = data.get("log", {}).get("entries", [])
    targets = []
    for e in entries:
        req = e.get("request", {})
        url = req.get("url", "")
        if "/api/computation-api/execute" not in url:
            continue
        resp = e.get("response", {})
        item = {
            "method": req.get("method"),
            "url": url,
            "status": resp.get("status"),
            "request": None,
            "response": None,
        }
        text = req.get("postData", {}).get("text", "")
        if text:
            try:
                item["request"] = json.loads(text)
            except Exception:
                item["request"] = text
        rtext = resp.get("content", {}).get("text", "")
        if rtext:
            try:
                item["response"] = json.loads(rtext)
            except Exception:
                item["response"] = rtext
        targets.append(item)

    print(json.dumps(targets, ensure_ascii=False, indent=2))
    print(f"\n共发现 {len(targets)} 条 computation-api 执行请求")


if __name__ == "__main__":
    main()

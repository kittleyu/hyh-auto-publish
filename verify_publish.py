#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_publish.py — 核对指定文章 id 的真实 publish_status / audit_status。"""
import os, sys, json
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))
CORP_ID = os.environ.get("CORP_ID", "")
IDS = {int(x) for x in os.environ.get("IDS", "").split(",") if x.strip()}

PUB = {0: "未发布", 1: "待发布", 2: "发布中", 3: "已发布", 4: "失败", 5: "排队中"}


def api_get(page, path):
    return page.evaluate(f"(async()=>{{try{{var r=await fetch('{path}',{{method:'GET'}});return await r.json();}}catch(e){{return {{error:String(e)}};}}}})()")


def main():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = b.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        if CORP_ID:
            api_get(page, f"/yunying/v1/auth/changecorp?corp_id={CORP_ID}")
            page.wait_for_timeout(1000)
        # 不带 publish_status 过滤，拉全量已审核文章，找目标 id 的真实字段
        found = {}
        page_num = 1
        while page_num <= 30 and len(found) < len(IDS):
            r = api_get(page, f"/yunying/v1/creation/articles?page={page_num}&page_size=100&audit_status=1")
            batch = r.get("data", {}).get("articles", [])
            if not batch:
                break
            for a in batch:
                if a["id"] in IDS:
                    found[a["id"]] = a
            page_num += 1
        print(f"目标 {len(IDS)} 篇，命中 {len(found)} 篇\n")
        from collections import Counter
        c = Counter()
        for aid in sorted(IDS):
            a = found.get(aid)
            if not a:
                print(f"  {aid}  <未在已审核列表找到>")
                c["缺失"] += 1
                continue
            ps = a.get("publish_status")
            c[PUB.get(ps, ps)] += 1
            print(f"  {aid}  publish_status={ps}({PUB.get(ps, ps)})  {a.get('title','')[:30]}")
        print("\n状态汇总:", dict(c))
    finally:
        b.close()
        pw.stop()


if __name__ == "__main__":
    main()

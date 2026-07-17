#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""media_probe.py — 查询当前公司自媒体候选池的热度(quote_cnt)与价格分布。"""
import os, sys, json, time, subprocess, shutil, urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))
CORP_ID = os.environ.get("CORP_ID", "")


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
        # 自媒体 media_type=2
        res = api_get(page, "/yunying/v1/media?page=1&page_size=100&media_type=2&sort_by=quote_cnt&sort_order=desc")
        medias = res.get("data", {}).get("medias", [])
        print(f"自媒体池共 {len(medias)} 个")

        def price_of(m):
            return m.get("price", 0) or 0
        def quote_of(m):
            return m.get("quote_cnt", 0) or 0
        def name_of(m):
            return m.get("name")
        def plat_of(m):
            return (m.get("platform") or {}).get("platform_name", "")

        # 热度分布
        nonzero = [m for m in medias if quote_of(m) > 0]
        print(f"\nquote_cnt > 0 的媒体: {len(nonzero)} / {len(medias)}")
        print("\n== 热度(quote_cnt)最高的前 10 ==")
        for m in sorted(medias, key=quote_of, reverse=True)[:10]:
            print(f"  quote={quote_of(m):<6} price={price_of(m):<7} {name_of(m)} ({plat_of(m)})")

        print("\n== 价格最低的前 15 ==")
        for m in sorted(medias, key=price_of)[:15]:
            print(f"  price={price_of(m):<7} quote={quote_of(m):<6} {name_of(m)} ({plat_of(m)})")

        # 性价比: quote/price (price>0)
        print("\n== 性价比(quote/price*1000)最高的前 10（price>0）==")
        withp = [m for m in medias if price_of(m) > 0]
        for m in sorted(withp, key=lambda m: quote_of(m)/price_of(m), reverse=True)[:10]:
            r = quote_of(m)/price_of(m)*1000
            print(f"  ratio={r:.3f} quote={quote_of(m):<6} price={price_of(m):<7} {name_of(m)} ({plat_of(m)})")

        prices = sorted(price_of(m) for m in medias)
        print(f"\n价格区间: min={prices[0]} max={prices[-1]} median={prices[len(prices)//2]}")
    finally:
        b.close()
        pw.stop()


if __name__ == "__main__":
    main()

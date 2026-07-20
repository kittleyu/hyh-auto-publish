#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_whitelist.py — 拉取 /media 全量，按 score(信源权重/AI 收录效果) 降序，
建立「AI 收录优选媒体白名单」。

业务背景：发文目的是让文章被 AI 引用成参考资料（GEO），
平台 /media 的 `score` 字段即平台对信源「AI 收录/引用效果」的综合权重。
本脚本把全局 score 最高的媒体拉成白名单，供 build_map.py 用
「历史记录 ∩ 白名单」方式选媒体——既从历史里挑，又只选 AI 收录效果好的。

用法：
    set HYH_USER=<账号>      # 若调试 Chrome 已登录可省略
    set HYH_PWD=<密码>
    python build_whitelist.py [--top 300] [--pages 15]
"""
import os, sys, json, time, argparse
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import build_map as bm
from playwright.sync_api import sync_playwright

TOP = 300          # 白名单媒体数量
PAGES_PER_TYPE = 15  # 每类型拉前 N 页（高分集中在前面）


def tier_of(score):
    """按 score 分档，便于人工审阅权威度。"""
    if score >= 100000:
        return "A(极高)"
    if score >= 10000:
        return "B(高)"
    if score >= 1000:
        return "C(中)"
    return "D(低)"


def fetch_media_all(page, pages_per_type):
    out = []
    for mtype in (1, 2):
        pn = 1
        while pn <= pages_per_type:
            r = bm.api_get(page, f"/yunying/v1/media?page={pn}&page_size=100&media_type={mtype}&sort_by=score&sort_order=desc")
            ms = r.get("data", {}).get("medias", [])
            if not ms:
                break
            for m in ms:
                out.append(bm.normalize_candidate(m))
            total_pages = r.get("data", {}).get("total_pages") or 1
            if pn >= total_pages:
                break
            pn += 1
    return out


def main():
    global TOP, PAGES_PER_TYPE
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=TOP, help="白名单媒体数量（按 score 取前 N）")
    parser.add_argument("--pages", type=int, default=PAGES_PER_TYPE, help="每媒体类型拉取页数（高分集中在前面）")
    parser.add_argument("--out", default="media_whitelist.json", help="白名单输出路径")
    parser.add_argument("--full-out", default="media_whitelist_full.json", help="全量排序输出路径")
    args = parser.parse_args()
    TOP, PAGES_PER_TYPE = args.top, args.pages

    if not bm.USER or not bm.PWD:
        print("⚠️ 未设置 HYH_USER/HYH_PWD；若调试 Chrome 已登录 360 智见后台则可跳过登录直接拉取")

    bm.ensure_chrome()
    pw = sync_playwright().start()
    b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{bm.PORT}")
    ctx = b.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        if not bm.check_logged_in(page):
            print(">>> 调试 Chrome 未登录，尝试登录 ...")
            bm.do_login(page)

        print(f">>> 拉取 /media 全量（每类型前 {PAGES_PER_TYPE} 页，按 score 降序）...")
        medias = fetch_media_all(page, PAGES_PER_TYPE)
        print(f"    拉取到 {len(medias)} 个媒体")

        # 去重（同一 media 可能同时出现在两个类型分页，按 id）
        seen = {}
        for m in medias:
            mid = m.get("id")
            if mid is not None and mid not in seen:
                seen[mid] = m
        medias = list(seen.values())

        # 按 score 降序
        medias.sort(key=lambda m: (m.get("score", 0) or 0), reverse=True)

        # 全量排序输出（带 tier）
        full = []
        for m in medias:
            full.append({
                "id": m["id"], "name": m.get("name"), "platform_name": m.get("platform_name", ""),
                "score": m.get("score", 0) or 0, "price": m.get("price", 0) or 0,
                "quote_cnt": m.get("quote_cnt", 0) or 0, "media_type": m.get("media_type", 0),
                "tier": tier_of(m.get("score", 0) or 0),
            })
        with open(args.full_out, "w", encoding="utf-8") as f:
            json.dump(full, f, ensure_ascii=False, indent=2)
        print(f"✅ 全量排序文件: {os.path.abspath(args.full_out)} ({len(full)} 个)")

        # 白名单 Top N
        top = full[:TOP]
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(top, f, ensure_ascii=False, indent=2)
        print(f"✅ 白名单文件: {os.path.abspath(args.out)} (Top {len(top)})")

        # 平台聚合统计（看 top 媒体都来自哪些平台/类型）
        from collections import Counter
        plat = Counter((m["platform_name"], m["media_type"]) for m in top)
        print(f"\n>>> 白名单 Top {len(top)} 平台分布（platform, media_type: 1新闻/2自媒体）:")
        for (p, mt), c in plat.most_common(20):
            print(f"    {p or '未知平台':<16} (type={mt}) × {c}")

        # 类型占比
        type1 = sum(1 for m in top if m["media_type"] == 1)
        type2 = sum(1 for m in top if m["media_type"] == 2)
        print(f"\n>>> 类型占比: 新闻(type=1)={type1}, 自媒体(type=2)={type2}")

        print("\n>>> 白名单前 10:")
        for m in top[:10]:
            print(f"    [{m['id']}] {m['name']} ({m['platform_name']}) score={m['score']} tier={m['tier']} price={m['price']}")

    finally:
        b.close()
        pw.stop()


if __name__ == "__main__":
    main()

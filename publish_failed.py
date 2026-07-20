#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_failed.py — 拉取指定 corp 下发布失败(publish_status=4)的文章，用 curated 信源生成映射表。
========================================================================================
用法：
    CORP_ID=3258 python publish_failed.py --limit 5 --top-k 5 --out publish_map_yongan_failed.json
只生成映射表（不发布），预览后交给用户确认，再用 publish_run.py 发布。
"""
import os, sys, json, time, argparse
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))
USER = os.environ.get("HYH_USER", "")
PWD = os.environ.get("HYH_PWD", "")
CORP_ID = os.environ.get("CORP_ID", "")

from playwright.sync_api import sync_playwright


def api_get(page, path):
    return page.evaluate(f"(async()=>{{try{{var r=await fetch('{path}',{{method:'GET'}});var t=await r.text();try{{return JSON.parse(t);}}catch(e){{return {{error:t.slice(0,200)}};}}}}catch(e){{return {{error:String(e)}};}}}})()")


def fetch_failed_articles(page, limit):
    """遍历文章页，收集 publish_status=4(失败) 的前 limit 篇（按平台返回顺序，通常新→旧）。"""
    failed = []
    seen = set()
    page_num = 1
    while page_num <= 30 and len(failed) < limit:
        r = api_get(page, f"/yunying/v1/creation/articles?page={page_num}&page_size=100")
        data = r.get("data", {})
        arts = data.get("articles", [])
        if not arts:
            break
        for a in arts:
            if a.get("publish_status") == 4 and a["id"] not in seen:
                failed.append(a)
                seen.add(a["id"])
                if len(failed) >= limit:
                    break
        tp = data.get("total_pages") or (data.get("total", 0) // 100 + 1)
        if page_num >= tp:
            break
        page_num += 1
    return failed[:limit]


def build_media_index(page):
    idx = {}
    for mtype in (1, 2):
        page_num = 1
        while True:
            r = api_get(page, f"/yunying/v1/media?page={page_num}&page_size=100&media_type={mtype}&sort_by=score&sort_order=desc")
            ms = r.get("data", {}).get("medias", [])
            if not ms:
                break
            for m in ms:
                mid = m.get("id")
                if mid is not None:
                    region = m.get("region")
                    if isinstance(region, dict):
                        region = region.get("name", "")
                    idx[mid] = {
                        "id": mid, "name": m.get("name"),
                        "platform_name": (m.get("platform") or {}).get("platform_name", ""),
                        "price": m.get("price", 0) or 0, "quote_cnt": m.get("quote_cnt", 0) or 0,
                        "score": m.get("score", 0) or 0, "media_type": m.get("media_type", 0),
                        "region": region or "",
                    }
            if page_num >= (r.get("data", {}).get("total_pages") or 1):
                break
            page_num += 1
            if page_num > 60:
                break
    return idx


def resolve_media_id(index, name):
    n = (name or "").strip().lower()
    if not n:
        return None
    cands = [m for m in index.values() if n == (m.get("name") or "").lower() or n in (m.get("name") or "").lower() or (m.get("name") or "").lower() in n]
    if not cands:
        return None
    cands.sort(key=lambda m: (m.get("score", 0) or 0), reverse=True)
    return cands[0]["id"]


def load_curated(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("sources", []) if isinstance(d, dict) else d
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5, help="重发前 N 篇失败文章")
    ap.add_argument("--top-k", type=int, default=5, help="用 curated 前 K 个信源轮转分配")
    ap.add_argument("--out", default="publish_map_failed.json", help="输出映射表")
    ap.add_argument("--curated", default="curated_sources.json")
    ap.add_argument("--topic", default="", help="主题过滤关键词(逗号分隔)，如 期货,金融,财经")
    ap.add_argument("--exclude", default="", help="排除含这些子串的媒体(逗号分隔)，如 华律,庭立方,法律,律师")
    args = ap.parse_args()

    pw = sync_playwright().start()
    b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = b.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        if CORP_ID:
            api_get(page, f"/yunying/v1/auth/changecorp?corp_id={CORP_ID}")
            page.wait_for_timeout(1500)
            print(f">>> 切换公司 corp_id={CORP_ID}")

        arts = fetch_failed_articles(page, args.limit)
        print(f">>> 找到 {len(arts)} 篇发布失败文章")
        for a in arts:
            print(f"    [{a['id']}] {a.get('title','')[:50]} (pub={a.get('publish_status')})")

        if not arts:
            print("(!) 无失败文章，退出")
            return

        # 词包
        pkg_res = api_get(page, "/yunying/v1/keyword/package?page=1&page_size=10000")
        pkgs = {p["id"]: p for p in pkg_res.get("data", {}).get("keyword_packages", [])}

        # curated 信源解析
        srcs = load_curated(args.curated)
        need = [s for s in srcs if not s.get("media_id")]
        idx = {}
        if need:
            print(f">>> 实时解析 {len(need)} 个信源 media_id ...")
            idx = build_media_index(page)
            for s in need:
                s["media_id"] = resolve_media_id(idx, s.get("name"))
        raw = []
        for s in srcs:
            mid = s.get("media_id")
            if not mid:
                continue
            m = idx.get(mid) if idx else None
            raw.append(m if m else {"id": mid, "name": s.get("name"), "platform_name": "", "price": 0, "quote_cnt": 0, "score": 0, "media_type": 0, "region": ""})
        candidates = raw
        print(f">>> curated 可用信源 {len(candidates)} 个")

        if args.topic:
            kws = [k.strip().lower() for k in args.topic.split(",") if k.strip()]
            before = len(candidates)
            candidates = [c for c in candidates if any(k in (c.get("name", "") + c.get("platform_name", "")).lower() for k in kws)]
            print(f"    主题过滤 [{args.topic}] 后 {len(candidates)}/{before}")

        if args.exclude:
            ex = [e.strip().lower() for e in args.exclude.split(",") if e.strip()]
            if ex:
                before = len(candidates)
                candidates = [c for c in candidates if not any(e in (c.get("name", "") + c.get("platform_name", "")).lower() for e in ex)]
                print(f"    排除 [{args.exclude}] 后 {len(candidates)}/{before}")

        if not candidates:
            print("❌ 无可用信源")
            return

        top_k = max(1, min(args.top_k, len(candidates)))
        top_media = candidates[:top_k]
        print(f"\n>>> 分配媒体 (top_k={top_k}, curated 顺序) ...")

        mappings = []
        for i, a in enumerate(arts):
            best = top_media[i % len(top_media)]
            pkg = pkgs.get(a.get("keyword_package_id"))
            keywords = a.get("keywords") or (pkg.get("distilled_keywords") if pkg else []) or []
            core = pkg.get("core_keyword") if pkg else (keywords[0] if keywords else "")
            mappings.append({
                "article_id": a["id"],
                "article_title": a.get("title", ""),
                "keyword_package_id": a.get("keyword_package_id"),
                "keyword_package_name": a.get("keyword_package_name"),
                "core_keyword": core,
                "keywords": keywords[:10],
                "selected_media_id": best["id"],
                "selected_media_name": best["name"],
                "selected_platform": best.get("platform_name", ""),
                "price": best.get("price", 0),
                "score": best.get("score", 0),
                "quote_cnt": best.get("quote_cnt", 0),
                "heat_note": f"score={best.get('score',0)}, price={best.get('price',0)} (top-{i % len(top_media) + 1}/{top_k})",
            })

        out = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "corp_id": CORP_ID,
            "corp_name": "永安期货股份有限公司",
            "candidate_source": "curated",
            "note": "发布失败(pub=4)文章重发映射（用 curated 信源）",
            "article_count": len(mappings),
            "total_estimated_cost": sum(m["price"] for m in mappings),
            "mappings": mappings,
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 映射表已生成: {os.path.abspath(args.out)}")
        print(f"   文章数: {len(mappings)}  预估总成本: {out['total_estimated_cost']} 智豆")
        print("\n预览:")
        for m in mappings:
            print(f"  [{m['article_id']}] {m['article_title'][:42]} → {m['selected_media_name']} ({m['selected_platform']}) score={m.get('score',0)} ¥{m['price']}")
    finally:
        b.close()
        pw.stop()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_map.py — 生成「文章→媒体」映射表。
================================================
登录 cms-yunying.html，拉取最新 N 篇可发布文章、词包和媒体候选池，
按热度（默认 media.quote_cnt）为每篇文章选择最优媒体，输出映射表。

用法：
    set HYH_USER=<账号>
    set HYH_PWD=<密码>
    python build_map.py --limit 20 --out map.json
"""
import os, sys, json, time, argparse, subprocess, shutil, urllib.request, re

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))
PROFILE = os.path.join(os.path.expandvars("%TEMP%"), "hyh_debug_profile")
CHROME = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
USER = os.environ.get("HYH_USER", "")
PWD = os.environ.get("HYH_PWD", "")
CORP_ID = os.environ.get("CORP_ID", "")


def find_chrome():
    for p in [CHROME, r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]:
        if os.path.isfile(p):
            return p
    return shutil.which("chrome.exe") or shutil.which("chrome")


def wait_cdp(port, timeout=45):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def ensure_chrome():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=3):
            print(">>> 复用现有调试 Chrome")
            return
    except Exception:
        pass
    chrome = find_chrome()
    if not chrome or not os.path.isfile(chrome):
        raise RuntimeError("找不到 chrome.exe")
    if os.path.isdir(PROFILE):
        shutil.rmtree(PROFILE, ignore_errors=True)
    os.makedirs(PROFILE, exist_ok=True)
    subprocess.Popen([chrome, f"--user-data-dir={PROFILE}", f"--remote-debugging-port={PORT}",
                      "--no-first-run", "--no-default-browser-check", "--new-window", "about:blank"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    if not wait_cdp(PORT):
        raise RuntimeError("调试端口未就绪")
    print("✅ 调试端口就绪")


def check_logged_in(page):
    try:
        res = page.evaluate("(async()=>{try{var r=await fetch('/yunying/v1/corp/active',{method:'GET'});var d=await r.json();return {status:r.status, hasData:!!(d&&d.data)};}catch(e){return {error:String(e)};}})()")
        return res.get("status") == 200 and res.get("hasData")
    except Exception:
        return False


def do_login(page):
    print(">>> 未登录，执行登录 ...")
    page.goto("https://yunying.huiyouhua.com/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    try:
        page.evaluate("""(function(){var btns=[].slice.call(document.querySelectorAll('button'));for(var i=0;i<btns.length;i++){if((btns[i].textContent||'').replace(/\\s/g,'')==='GEO账号登录'){btns[i].click();break;}}})()""")
        page.wait_for_timeout(500)
    except Exception:
        pass
    pw = page.query_selector('input[type="password"]')
    if not pw:
        raise RuntimeError("未找到密码输入框")
    user = None
    for inp in page.query_selector_all('input'):
        t = (inp.get_attribute('type') or 'text').lower()
        if t in ('text', 'email', 'tel', 'number', ''):
            user = inp; break
    if not user:
        user = page.query_selector('input:not([type="password"])')
    if user:
        user.fill(USER)
    pw.fill(PWD)
    sub = None
    for btn in page.query_selector_all('button'):
        txt = (btn.inner_text() or '').strip(); norm = re.sub(r'\s+', '', txt); low = norm.lower()
        if '账号' in norm or 'geo' in low:
            continue
        if '登录' in norm or 'sign' in low or 'submit' in (btn.get_attribute('type') or ''):
            sub = btn; break
    if sub:
        sub.click()
    else:
        pw.press('Enter')
    try:
        page.wait_for_url(lambda u: 'login' not in u.lower(), timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(3000)
    if not check_logged_in(page):
        raise RuntimeError("登录失败")
    print("✅ 登录成功")


def api_get(page, path):
    return page.evaluate(f"(async()=>{{try{{var r=await fetch('{path}',{{method:'GET'}});return await r.json();}}catch(e){{return {{error:String(e)}};}}}})()")


def api_post(page, path, body):
    body_json = json.dumps(body, ensure_ascii=False)
    js = """(async()=>{
        try{
            var r=await fetch('""" + path + """',{
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify(""" + body_json + """)
            });
            return await r.json();
        }catch(e){return {error:String(e)};}
    })()"""
    return page.evaluate(js)


def fetch_all_pages(page, base_path):
    """拉取分页接口的所有数据（假设接口返回 data.list/items/records）。"""
    results = []
    page_num = 1
    while True:
        path = f"{base_path}{'&' if '?' in base_path else '?'}page={page_num}&page_size=100"
        res = api_get(page, path)
        data = res.get('data', {})
        items = data.get('list') or data.get('items') or data.get('records') or data.get('medias') or data.get('articles') or data.get('keyword_packages') or []
        if not items:
            break
        results.extend(items)
        total_pages = data.get('total_pages') or data.get('total', 0) // 100 + 1
        if page_num >= total_pages:
            break
        page_num += 1
        if page_num > 50:
            print("(!) 分页超过 50，停止")
            break
    return results


def normalize_candidate(m):
    """统一 /media 与 /articles/media-history 两数据源字段为统一结构。
    统一字段: id, name, platform_name, price, quote_cnt, media_type, region
    注意: media-history 接口不含 quote_cnt，归一化后该字段为 0。
    """
    if not m:
        return None
    if "media_id" in m:  # media-history 形态
        return {
            "id": m.get("media_id"),
            "name": m.get("media_name"),
            "platform_name": m.get("platform_name", ""),
            "price": m.get("price", 0) or 0,
            "quote_cnt": m.get("quote_cnt", 0) or 0,
            "media_type": m.get("media_type", 0),
            "region": m.get("region", ""),
        }
    # /media 形态
    region = m.get("region")
    if isinstance(region, dict):
        region = region.get("name", "")
    return {
        "id": m.get("id"),
        "name": m.get("name"),
        "platform_name": (m.get("platform") or {}).get("platform_name", ""),
        "price": m.get("price", 0) or 0,
        "quote_cnt": m.get("quote_cnt", 0) or 0,
        "media_type": m.get("media_type", 0),
        "region": region or "",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20, help="最新 N 篇文章")
    parser.add_argument("--media-type", type=int, default=2, help="媒体类型：1 新闻，2 自媒体")
    parser.add_argument("--sort", default="quote_cnt", choices=["quote_cnt", "price"], help="媒体排序依据")
    parser.add_argument("--out", default="publish_map.json", help="输出映射表路径")
    parser.add_argument("--candidate-source", default="history", choices=["history", "all"], help="候选池来源：history=用户发文历史（即后台『选择媒体』按钮右侧的『历史记录』，推荐，主题相关度高）；all=全部媒体(含 quote_cnt 热度，但实测热度数据基本是坏的)")
    parser.add_argument("--top-k", type=int, default=3, help="取热度最高的前 K 个媒体，文章在这些媒体间轮转分配(增加覆盖)")
    parser.add_argument("--ids", default="", help="仅对指定文章 id 生成映射（逗号分隔），用于精确锁定刚审核的文章")
    parser.add_argument("--media-ids", default="", help="媒体白名单（逗号分隔的 media_id），仅从指定历史媒体中选择并保序；用于‘从历史媒体里挑’场景")
    args = parser.parse_args()

    only_ids = set()
    if args.ids:
        only_ids = {int(x.strip()) for x in args.ids.split(",") if x.strip()}

    if not USER or not PWD:
        print("❌ 请设置环境变量 HYH_USER 和 HYH_PWD")
        sys.exit(1)

    ensure_chrome()
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = b.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    try:
        if CORP_ID:
            api_get(page, f"/yunying/v1/auth/changecorp?corp_id={CORP_ID}")
            print(f">>> 切换公司 corp_id={CORP_ID}")
            page.wait_for_timeout(1500)

        if not check_logged_in(page):
            do_login(page)

        user = api_get(page, "/yunying/v1/user/current?platform=win")
        corp_id = user.get("data", {}).get("corp_id")
        corp_name = user.get("data", {}).get("corp_name", "未知")
        print(f">>> 当前公司: {corp_id} {corp_name}")

        # 1. 拉取可发布文章（audit_status=1 & publish_status=0）
        if only_ids:
            print(f"\n>>> 锁定指定 {len(only_ids)} 篇文章（--ids），从可发布列表中筛选 ...")
            arts = []
            seen = set()
            page_num = 1
            while page_num <= 20 and len(arts) < len(only_ids):
                r = api_get(page, f"/yunying/v1/creation/articles?page={page_num}&page_size=100&audit_status=1&publish_status=0")
                batch = r.get("data", {}).get("articles", [])
                if not batch:
                    break
                for a in batch:
                    if a["id"] in only_ids and a["id"] not in seen:
                        arts.append(a); seen.add(a["id"])
                page_num += 1
            missing = only_ids - seen
            print(f"    命中 {len(arts)} 篇；缺失 {len(missing)} 篇: {sorted(missing) if missing else '无'}")
        else:
            print(f"\n>>> 拉取最新 {args.limit} 篇可发布文章 ...")
            arts_res = api_get(page, f"/yunying/v1/creation/articles?page=1&page_size={args.limit}&audit_status=1&publish_status=0")
            arts = arts_res.get("data", {}).get("articles", [])
            print(f"    获取到 {len(arts)} 篇")
        if not arts:
            print("(!) 没有可发布的文章，退出")
            return

        # 2. 拉取词包
        print(">>> 拉取词包 ...")
        pkg_res = api_get(page, "/yunying/v1/keyword/package?page=1&page_size=10000")
        pkgs = {p["id"]: p for p in pkg_res.get("data", {}).get("keyword_packages", [])}

        # 3. 拉取候选媒体池
        raw_candidates = []
        if args.candidate_source == "history":
            print(">>> 拉取用户发文历史 ...")
            hist_res = api_get(page, "/yunying/v1/articles/media-history?page=1&page_size=1000")
            hist_data = hist_res.get("data", {})
            raw_candidates = hist_data.get("list") or hist_data.get("items") or hist_data.get("records") or []
            print(f"    历史媒体 {len(raw_candidates)} 个 (注意: 历史接口不含 quote_cnt，热度将退化为价格排序)")
        if not raw_candidates:
            print(f">>> 拉取全部媒体 (media_type={args.media_type}) 按 {args.sort} 降序 ...")
            sort_order = "desc" if args.sort == "quote_cnt" else "asc"
            media_res = api_get(page, f"/yunying/v1/media?page=1&page_size=100&media_type={args.media_type}&sort_by={args.sort}&sort_order={sort_order}")
            raw_candidates = media_res.get("data", {}).get("medias", [])
            print(f"    获取到 {len(raw_candidates)} 个媒体")

        if not raw_candidates:
            print("❌ 没有可用媒体候选")
            return

        candidates = [c for c in (normalize_candidate(m) for m in raw_candidates) if c and c.get("id")]
        print(f">>> 候选媒体池归一化后 {len(candidates)} 个")

        # 媒体白名单（指定顺序）
        media_ids_filter = []
        if args.media_ids:
            media_ids_filter = {int(x.strip()) for x in args.media_ids.split(",") if x.strip()}
            if media_ids_filter:
                order = {int(x.strip()): i for i, x in enumerate(args.media_ids.split(",")) if x.strip()}
                chosen = [c for c in candidates if c.get("id") in media_ids_filter]
                chosen.sort(key=lambda c: order.get(c.get("id"), 999))
                candidates = chosen
                print(f"    媒体白名单命中 {len(chosen)} 个: {[c['id'] for c in chosen]}")

        # 4. 排序，取前 top_k 个媒体，文章在其间轮转分配
        if media_ids_filter:
            # 指定白名单：顺序即用户意图，不重排
            ranked = candidates
            rank_desc = "媒体白名单（指定顺序）"
        elif args.sort == "price":
            # 价格升序（省钱优先），热度降序作次要键
            ranked = sorted(candidates, key=lambda m: ((m.get("price", 0) or 0), -(m.get("quote_cnt", 0) or 0)))
            rank_desc = "按 price 价格升序"
        else:
            # 热度降序，价格升序作次要键
            ranked = sorted(candidates, key=lambda m: (m.get("quote_cnt", 0), -m.get("price", 0)), reverse=True)
            rank_desc = "按 quote_cnt 热度降序"
        top_k = max(1, min(args.top_k, len(ranked)))
        top_media = ranked[:top_k]
        print(f"\n>>> 计算文章→媒体映射 (top_k={top_k}, {rank_desc}) ...")
        mappings = []
        for i, a in enumerate(arts):
            best = top_media[i % len(top_media)]
            pkg = pkgs.get(a.get("keyword_package_id"))
            keywords = a.get("keywords") or (pkg.get("distilled_keywords") if pkg else []) or []
            core = pkg.get("core_keyword") if pkg else (keywords[0] if keywords else "")
            mappings.append({
                "article_id": a["id"],
                "article_title": a["title"],
                "keyword_package_id": a.get("keyword_package_id"),
                "keyword_package_name": a.get("keyword_package_name"),
                "core_keyword": core,
                "keywords": keywords[:10],
                "selected_media_id": best["id"],
                "selected_media_name": best["name"],
                "selected_platform": best.get("platform_name", ""),
                "price": best.get("price", 0),
                "quote_cnt": best.get("quote_cnt", 0),
                "heat_note": f"quote_cnt={best.get('quote_cnt',0)}, price={best.get('price',0)} (top-{i % len(top_media) + 1}/{top_k})"
            })

        # 5. 输出映射表
        out = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "corp_id": corp_id,
            "corp_name": corp_name,
            "candidate_source": args.candidate_source,
            "media_type": args.media_type,
            "article_count": len(mappings),
            "total_estimated_cost": sum(m["price"] for m in mappings),
            "mappings": mappings
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 映射表已生成: {os.path.abspath(args.out)}")
        print(f"   文章数: {len(mappings)}")
        print(f"   预估总成本: {out['total_estimated_cost']} 智豆")
        print("\n预览（前 3 条）:")
        for m in mappings[:3]:
            print(f"  [{m['article_id']}] {m['article_title'][:40]}... → {m['selected_media_name']} ({m['selected_platform']}) price={m['price']}")

    finally:
        b.close()
        pw.stop()


if __name__ == "__main__":
    main()

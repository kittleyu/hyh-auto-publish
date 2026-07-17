#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_dispatch_api.py — 直接调用疑似发布接口 /articles/media/{media_id}/dispatch 做验证。"""
import os, sys, json, time, subprocess, shutil, urllib.request, re
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))
PROFILE = os.path.join(os.path.expandvars("%TEMP%"), "hyh_debug_profile")
CHROME = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
USER = os.environ.get("HYH_USER", "")
PWD = os.environ.get("HYH_PWD", "")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


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
            return
    except Exception:
        pass
    chrome = find_chrome()
    if not chrome or not os.path.isfile(chrome):
        sys.exit(1)
    if os.path.isdir(PROFILE):
        shutil.rmtree(PROFILE, ignore_errors=True)
    os.makedirs(PROFILE, exist_ok=True)
    subprocess.Popen([chrome, f"--user-data-dir={PROFILE}", f"--remote-debugging-port={PORT}",
                      "--no-first-run", "--no-default-browser-check", "--new-window", "about:blank"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    if not wait_cdp(PORT):
        sys.exit(1)


def check_logged_in(page):
    try:
        res = page.evaluate("(async()=>{try{var r=await fetch('/yunying/v1/corp/active',{method:'GET'});var d=await r.json();return {status:r.status, hasData:!!(d&&d.data)};}catch(e){return {error:String(e)};}})()")
        return res.get("status") == 200 and res.get("hasData")
    except Exception:
        return False


def do_login(page):
    page.goto("https://yunying.huiyouhua.com/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    try:
        page.evaluate("""(function(){var btns=[].slice.call(document.querySelectorAll('button'));for(var i=0;i<btns.length;i++){if((btns[i].textContent||'').replace(/\\s/g,'')==='GEO账号登录'){btns[i].click();break;}}})()""")
        page.wait_for_timeout(500)
    except Exception:
        pass
    pw = page.query_selector('input[type="password"]')
    if not pw:
        return False
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
    return check_logged_in(page)


def api_eval(page, path, method='GET', body=None):
    body_json_str = json.dumps(body, ensure_ascii=False) if body else 'null'
    js = """(async()=>{
        try{
            var bodyObj = """ + body_json_str + """;
            var opts = {method: '""" + method + """', headers: {'Content-Type': 'application/json'}};
            if (bodyObj !== null) opts.body = JSON.stringify(bodyObj);
            var r = await fetch('""" + path + """', opts);
            return await r.json();
        } catch(e) { return {error: String(e)}; }
    })()"""
    try:
        return page.evaluate(js)
    except Exception as e:
        return {"error": str(e)}


def main():
    ensure_chrome()
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    b = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = b.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    if not check_logged_in(page):
        if not do_login(page):
            print("❌ 登录失败"); return

    page.goto("https://yunying.huiyouhua.com/cms-yunying.html?tab=articles", wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(3000)

    # 1. 拉取审核完成的文章
    arts = api_eval(page, '/yunying/v1/creation/articles?page=1&page_size=50&audit_status=1')
    print(f"审核完成文章数: {arts.get('data',{}).get('total', 'N/A')}")
    articles = arts.get('data', {}).get('articles', [])

    # 找字段名：看第一篇文章的所有 keys
    if articles:
        print("\n=== 文章字段 ===")
        print(json.dumps(list(articles[0].keys()), ensure_ascii=False))
        # 打印发布状态相关字段
        for a in articles[:3]:
            status_fields = {k: v for k, v in a.items() if 'status' in k.lower() or 'publish' in k.lower() or 'state' in k.lower()}
            print(json.dumps(status_fields, ensure_ascii=False))

    # 2. 找待发布文章（publish_status != 3）
    target_article = None
    for status_code in [0, 1, 2]:
        arts_filtered = api_eval(page, f'/yunying/v1/creation/articles?page=1&page_size=20&audit_status=1&publish_status={status_code}')
        items = arts_filtered.get('data', {}).get('articles', [])
        if items:
            target_article = items[0]
            print(f"找到 publish_status={status_code} 的待发布文章: id={target_article['id']} title={target_article['title'][:40]}")
            break
    if not target_article:
        print("(!) 未找到 publish_status=0/1/2 的文章，使用第一篇")
        target_article = articles[0]

    # 3. 找最便宜的媒体 type=2
    cheapest_media = None
    for page_idx in [1, 2, 3, 4, 5]:
        media = api_eval(page, f'/yunying/v1/media?page={page_idx}&page_size=20&media_type=2&sort_by=price&sort_order=asc')
        medias = media.get('data', {}).get('medias', [])
        if medias:
            if not cheapest_media or medias[0]['price'] < cheapest_media['price']:
                cheapest_media = medias[0]
    if not cheapest_media:
        print("❌ 找不到媒体"); return
    print(f"\n最便宜的媒体: id={cheapest_media['id']} name={cheapest_media['name']} price={cheapest_media['price']} platform={cheapest_media['platform']['platform_name']}")

    # 3. 调用 dispatch 接口
    print(f"\n>>> 调用 POST /yunying/v1/articles/media/{cheapest_media['id']}/dispatch")
    result = api_eval(page, f'/yunying/v1/articles/media/{cheapest_media["id"]}/dispatch', 'POST', {'article_ids': [target_article['id']]})
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])

    # 4. 备选：/articles/publish-verified
    print(f"\n>>> 备选调用 POST /yunying/v1/articles/publish-verified")
    result2 = api_eval(page, '/yunying/v1/articles/publish-verified', 'POST', {'article_ids': [target_article['id']], 'media_id': cheapest_media['id']})
    print(json.dumps(result2, ensure_ascii=False, indent=2)[:2000])

    out = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "target_article": {k: v for k, v in target_article.items() if k in ['id', 'title', 'publish_status', 'status']},
        "cheapest_media": cheapest_media,
        "dispatch_result": result,
        "publish_verified_result": result2
    }
    with open(os.path.join(OUT_DIR, "dispatch_test.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n✅ 结果存:", os.path.join(OUT_DIR, "dispatch_test.json"))

    b.close()
    p.stop()


if __name__ == "__main__":
    main()

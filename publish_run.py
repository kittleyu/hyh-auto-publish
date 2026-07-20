#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_run.py — 读取 build_map.py 生成的映射表，批量调用 dispatch 接口发布。
=======================================================================================
用法：
    set HYH_USER=<账号>
    set HYH_PWD=<密码>
    python publish_run.py --map publish_map.json
"""
import os, sys, json, time, argparse, subprocess, shutil, urllib.request, re
from collections import defaultdict

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", required=True, help="映射表 JSON 路径（build_map.py 输出）")
    parser.add_argument("--dry-run", action="store_true", help="只打印要发布的映射，不实际调用接口")
    parser.add_argument("--out", default="publish_report.json", help="发布报告输出路径")
    args = parser.parse_args()

    if not os.path.isfile(args.map):
        print(f"❌ 找不到映射表: {args.map}")
        sys.exit(1)
    with open(args.map, "r", encoding="utf-8") as f:
        data = json.load(f)
    mappings = data.get("mappings", [])
    if not mappings:
        print("❌ 映射表为空")
        sys.exit(1)

    print(f">>> 读取映射表: {len(mappings)} 篇文章")
    print(f"    预估总成本: {sum(m['price'] for m in mappings)} 智豆")

    if args.dry_run:
        print("\n=== 试运行（不实际发布）===")
        for m in mappings:
            print(f"  文章 {m['article_id']}: {m['article_title'][:40]}... → 媒体 {m['selected_media_id']} {m['selected_media_name']} ({m['selected_platform']}) {m['price']}智豆")
        return

    if not USER or not PWD:
        print("⚠️ 未设置 HYH_USER/HYH_PWD；若调试 Chrome 已登录 360 智见后台则可跳过登录直接发布")

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

        # 按 media_id 聚合，批量 dispatch
        groups = defaultdict(list)
        for m in mappings:
            groups[m["selected_media_id"]].append(m)

        results = []
        for media_id, ms in groups.items():
            article_ids = [m["article_id"] for m in ms]
            print(f"\n>>> 发布到媒体 {media_id} ({ms[0]['selected_media_name']})：{len(ms)} 篇文章")
            res = api_post(page, f"/yunying/v1/articles/media/{media_id}/dispatch", {"article_ids": article_ids})
            success = res.get("code") == 0 and res.get("data", {}).get("code") == 0
            msg = res.get("data", {}).get("message") or res.get("message")
            print(f"    结果: {'成功' if success else '失败'} - {msg}")
            for m in ms:
                results.append({
                    "article_id": m["article_id"],
                    "article_title": m["article_title"],
                    "media_id": media_id,
                    "media_name": m["selected_media_name"],
                    "platform": m["selected_platform"],
                    "price": m["price"],
                    "success": success,
                    "message": msg,
                    "raw_response": res
                })
            time.sleep(1)

        report = {
            "published_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "map_file": args.map,
            "total": len(results),
            "success": sum(1 for r in results if r["success"]),
            "failed": sum(1 for r in results if not r["success"]),
            "total_cost": sum(r["price"] for r in results if r["success"]),
            "details": results
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 发布报告已保存: {os.path.abspath(args.out)}")
        print(f"   成功 {report['success']} / 失败 {report['failed']} / 总成本 {report['total_cost']} 智豆")

    finally:
        b.close()
        pw.stop()


if __name__ == "__main__":
    main()

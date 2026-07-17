#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_run.py — 批量审核通过「待审核」文章。
================================================
审核接口: POST /yunying/v1/article/{id}/update  body {id, audit_status:1}
状态枚举 audit_status: -1 待审核(Pending), 1 审核完成(Approved), 2 已拒绝(Rejected)
审核不扣智豆。

用法:
    set HYH_USER=<账号> & set HYH_PWD=<密码>
    python audit_run.py --corp-id 4104 --limit 20
    python audit_run.py --corp-id 4104 --limit 20 --dry-run   # 只列出不审核
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
            print(">>> 复用现有调试 Chrome"); return
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
    page.wait_for_timeout(3000)
    if not check_logged_in(page):
        raise RuntimeError("登录失败")
    print("✅ 登录成功")


def get_json(page, path):
    return page.evaluate("(async(u)=>{try{var r=await fetch(u);return await r.json();}catch(e){return {error:String(e)};}})", path)


def audit_one(page, aid, status=1):
    js = """(a)=>{return (async()=>{
        try{
            var r=await fetch(a.u,{method:'POST', headers:{'Content-Type':'application/json'}, body:a.body});
            var txt=await r.text(); var data; try{data=JSON.parse(txt);}catch(e){data=txt.slice(0,200);}
            return {status:r.status, data:data};
        }catch(e){return {error:String(e)};}
    })();}"""
    body = json.dumps({"id": aid, "audit_status": status}, ensure_ascii=False)
    return page.evaluate(js, {"u": f"/yunying/v1/article/{aid}/update", "body": body})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corp-id", default=os.environ.get("CORP_ID", ""), help="目标公司 corp_id")
    parser.add_argument("--limit", type=int, default=20, help="审核最新 N 篇待审核文章")
    parser.add_argument("--status", type=int, default=1, choices=[1, 2], help="1 通过, 2 拒绝")
    parser.add_argument("--dry-run", action="store_true", help="只列出不实际审核")
    parser.add_argument("--out", default="audit_report.json", help="审核报告输出路径")
    args = parser.parse_args()

    if not USER or not PWD:
        print("❌ 请设置 HYH_USER / HYH_PWD"); sys.exit(1)

    ensure_chrome()
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = b.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        if not check_logged_in(page):
            do_login(page)
        if args.corp_id:
            get_json(page, f"/yunying/v1/auth/changecorp?corp_id={args.corp_id}")
            page.wait_for_timeout(1200)
            print(f">>> 切换公司 corp_id={args.corp_id}")

        # 拉待审核文章
        r = get_json(page, f"/yunying/v1/creation/articles?page=1&page_size={max(args.limit,50)}&audit_status=-1")
        arts = [a for a in (r.get("data", {}) or {}).get("articles", []) if a.get("audit_status") == -1]
        total = (r.get("data", {}) or {}).get("total")
        arts = arts[:args.limit]
        print(f">>> 待审核文章共 {total} 篇，本次处理最新 {len(arts)} 篇")
        for a in arts:
            print(f"    [{a['id']}] {a['title'][:44]}")

        if args.dry_run:
            print("\n(dry-run) 未实际审核")
            report = {"dry_run": True, "corp_id": args.corp_id, "count": len(arts),
                      "articles": [{"id": a["id"], "title": a["title"]} for a in arts]}
        else:
            print(f"\n>>> 开始审核（status={args.status} {'通过' if args.status==1 else '拒绝'}）...")
            results = []
            for a in arts:
                res = audit_one(page, a["id"], args.status)
                ok = isinstance(res, dict) and res.get("status") == 200 and isinstance(res.get("data"), dict) and res["data"].get("code") == 0
                results.append({"id": a["id"], "title": a["title"], "ok": ok,
                                "msg": (res.get("data", {}) or {}).get("message") if isinstance(res.get("data"), dict) else str(res)[:120]})
                print(f"    [{a['id']}] {'✅' if ok else '❌'} {results[-1]['msg']}  {a['title'][:36]}")
                page.wait_for_timeout(300)
            ok_cnt = sum(1 for x in results if x["ok"])
            print(f"\n✅ 审核完成: {ok_cnt}/{len(results)} 成功")
            report = {"dry_run": False, "corp_id": args.corp_id, "status": args.status,
                      "total_pending": total, "processed": len(results), "success": ok_cnt, "results": results}

        with open(os.path.join(OUT_DIR, args.out), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("报告存:", os.path.join(OUT_DIR, args.out))
    finally:
        b.close(); pw.stop()


if __name__ == "__main__":
    main()

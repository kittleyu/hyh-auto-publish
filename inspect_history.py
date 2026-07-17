#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inspect_history.py — 快速查看 /articles/media-history 返回结构。"""
import os, sys, json, subprocess, shutil, urllib.request, re
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))
PROFILE = os.path.join(os.path.expandvars("%TEMP%"), "hyh_debug_profile")
CHROME = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
USER = os.environ.get("HYH_USER", "")
PWD = os.environ.get("HYH_PWD", "")


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


def main():
    ensure_chrome()
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    b = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = b.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    if not check_logged_in(page):
        if not do_login(page):
            print("登录失败"); return
    res = page.evaluate("(async()=>{try{var r=await fetch('/yunying/v1/articles/media-history?page=1&page_size=5',{method:'GET'});return await r.json();}catch(e){return {error:String(e)};}})()")
    print(json.dumps(res, ensure_ascii=False, indent=2)[:4000])
    b.close()
    p.stop()


if __name__ == "__main__":
    main()

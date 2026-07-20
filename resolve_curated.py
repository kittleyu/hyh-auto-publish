import asyncio, json, re, shutil
from playwright.async_api import async_playwright

PORT = 9222
BASE = "http://yunying.huiyouhua.com"
SRC = "curated_sources.json"

def norm(s):
    return re.sub(r"[\s（）()　]", "", (s or "").lower())

def rank(keyword, m):
    kw = norm(keyword)
    nm = norm(m.get("name", ""))
    pm = norm((m.get("platform") or {}).get("platform_name", ""))
    r = 0
    if nm == kw:
        r = 100
    elif nm.startswith(kw) and pm == kw:
        r = 90
    elif nm.startswith(kw):
        r = 70
    elif pm == kw:
        r = 60
    elif kw in nm:
        r = 40
    return r

async def api_get(page, path):
    resp = await page.request.get(BASE + path)
    return resp.status, json.loads(await resp.text())

async def search_all(page, name):
    best = None
    best_r = 0
    best_how = "not_found"
    for mt in [2, 1, ""]:
        q = f"/yunying/v1/media?page=1&page_size=20&keyword={name}"
        if mt != "":
            q += f"&media_type={mt}"
        st, d = await api_get(page, q)
        lst = (d.get("data", {}).get("medias") or []) if isinstance(d, dict) else []
        if not lst:
            continue
        for m in lst:
            r = rank(name, m)
            if r > best_r or (r == best_r and r > 0 and (m.get("score") or 0) > (best.get("score") or 0)):
                best, best_r = m, r
        if best_r >= 90:
            break
    if best:
        best_how = {100: "exact", 90: "plat_exact", 70: "startswith", 60: "plat", 40: "contains"}.get(best_r, "first")
    return best, best_how

async def main():
    shutil.copy(SRC, SRC + ".bak")
    data = json.load(open(SRC, encoding="utf-8"))
    sources = data["sources"]
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://localhost:{PORT}")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(BASE + "/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(800)
        for s in sources:
            name = s["name"]
            m, how = await search_all(page, name)
            if m:
                s["media_id"] = m.get("id")
                s["resolved_name"] = m.get("name")
                s["platform_name"] = (m.get("platform") or {}).get("platform_name")
                s["score"] = m.get("score")
                s["price"] = m.get("price")
                s["resolve_status"] = how
            else:
                s["media_id"] = None
                s["resolve_status"] = "not_found"
            print(f"[{s['resolve_status']:11s}] {name:10s} -> id={s.get('media_id')} {s.get('resolved_name')} ({s.get('platform_name')}) score={s.get('score')}")
            await page.wait_for_timeout(150)
        json.dump(data, open(SRC, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("\n已写回", SRC)
        await browser.close()

asyncio.run(main())

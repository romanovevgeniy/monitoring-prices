"""Скриншот Excel-таблицы в PNG — как она выглядит в Excel (цвета, подсветка, форматы).

Mac: Quick Look (qlmanage) отдаёт HTML-предпросмотр всей таблицы.
Windows (и Mac с SCREENSHOT_RENDERER=html): HTML строится из файла самостоятельно (excel_html.py).
HTML снимаем headless-браузером и обрезаем по границе таблиц. Профиль Chrome для магазинов не используется.
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

PADDING = 12  # белое поле вокруг таблицы, px


def quicklook_html(xlsx, workdir):
    subprocess.run(["qlmanage", "-p", "-o", str(workdir), str(xlsx)],
                   check=True, capture_output=True, timeout=120)
    previews = list(Path(workdir).glob("*.qlpreview"))
    if not previews:
        raise RuntimeError("Quick Look не сделал предпросмотр таблицы")
    preview = previews[0]
    html = (preview / "Preview.html").read_text(encoding="utf-8", errors="replace")
    # Вложения (стили) в предпросмотре ссылаются через cid: — превращаем в обычные относительные пути
    html = re.sub(r'(href|src)="cid:([^"]+)"', r'\1="\2"', html)
    page = preview / "page.html"
    page.write_text(html, encoding="utf-8")
    return page


def own_html(xlsx, workdir):
    from excel_html import sheet_to_html
    page = Path(workdir) / "page.html"
    page.write_text(sheet_to_html(xlsx), encoding="utf-8")
    return page


def use_quicklook():
    return sys.platform == "darwin" and os.environ.get("SCREENSHOT_RENDERER") != "html"


async def launch_browser(p):
    """Установленный Chrome (на Windows он нужен и для магазинов), иначе встроенный Chromium Playwright."""
    try:
        return await p.chromium.launch(channel="chrome")
    except Exception:
        return await p.chromium.launch()


async def render(page_html, png):
    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
        await page.goto(page_html.as_uri())
        await page.wait_for_load_state("networkidle")
        # Граница содержимого: объединение прямоугольников всех таблиц
        box = await page.evaluate("""() => {
            const r = [...document.querySelectorAll('table')].map(t => t.getBoundingClientRect());
            if (!r.length) return null;
            return {x: Math.min(...r.map(b => b.left)), y: Math.min(...r.map(b => b.top)),
                    r: Math.max(...r.map(b => b.right)), b: Math.max(...r.map(b => b.bottom))};
        }""")
        clip = None
        if box:
            x, y = max(box["x"] - PADDING, 0), max(box["y"] - PADDING, 0)
            clip = {"x": x, "y": y, "width": box["r"] + PADDING - x, "height": box["b"] + PADDING - y}
        await page.screenshot(path=str(png), full_page=True, clip=clip)
        await browser.close()


async def screenshot(xlsx, png):
    png = Path(png)
    png.parent.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="ql-"))
    try:
        page = await asyncio.to_thread(quicklook_html if use_quicklook() else own_html, xlsx, workdir)
        await render(page, png)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return png


if __name__ == "__main__":
    print(asyncio.run(screenshot(sys.argv[1], sys.argv[2])))

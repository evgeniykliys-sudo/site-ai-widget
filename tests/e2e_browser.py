"""Сквозная проверка в настоящем браузере: демо-страница → виджет → вопрос (ответ печатается стримом) →
«хочу замер» → форма → заявка. Заодно снимает скриншоты для README (docs/).

    python tests/e2e_browser.py      (сервер должен быть запущен: uvicorn app:app --port 8010)
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

URL = "http://localhost:8010/"
DOCS = Path(__file__).parent.parent / "docs"
ok = True


def check(name, cond):
    global ok
    ok &= bool(cond)
    print(("✅" if cond else "❌"), name)


async def wait_answer(page, n):
    # n-й ответ бота дописан: пузырь без «печатает», ввод снова доступен
    await page.wait_for_function(
        f"""() => {{ const r = document.querySelector('div[style*="2147483000"]').shadowRoot;
                    const b = r.querySelectorAll('.m.bot:not(.typing)');
                    return b.length >= {n} && !r.querySelector('.send').disabled; }}""", timeout=60000)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=2)
        await page.goto(URL)
        root = page.locator('div[style*="2147483000"]')
        fab = root.locator(".fab")
        check("кнопка виджета на странице", await fab.is_visible())
        font = await root.locator(".fab").evaluate("e => getComputedStyle(e).fontFamily")
        check(f"стили сайта (Times !important) не пролезли в виджет: {font[:30]}", "Times" not in font)
        await fab.click()
        await root.locator(".hints button").first.click()                     # «Сколько стоит ремонт санузла?»
        await wait_answer(page, 2)
        a1 = await root.locator(".m.bot").nth(1).inner_text()
        check(f"ответ по базе: «{a1[:60]}…»", "180" in a1)
        await root.locator(".inp textarea").fill("Хочу бесплатный замер на следующей неделе")
        await root.locator(".send").click()
        await wait_answer(page, 3)
        form = root.locator("form.form")
        await form.wait_for(timeout=10000)
        check("после «хочу замер» появилась форма заявки", await form.is_visible())
        last = await root.locator(".log > *").last.evaluate("e => e.tagName")
        check("форма — внизу ленты, под последним ответом", last == "FORM")
        await page.screenshot(path=str(DOCS / "screen-desktop.png"))
        await form.locator("input[name=phone]").fill("123")
        await form.locator("input[name=name]").fill("[тест] Ирина")
        await form.locator("button").click()
        await form.locator(".bad").wait_for(state="visible", timeout=10000)
        check("неверный телефон → понятная подсказка в форме", "телефон" in (await form.locator(".bad").inner_text()).lower())
        await form.locator("input[name=phone]").fill("8 913 000-00-00")
        await form.locator("button").click()
        await root.locator("form.form.done").wait_for(timeout=15000)
        check("заявка отправлена → «Заявка принята»", "принята" in await root.locator("form.form.done").inner_text())

        # мобильный: панель на весь экран, история диалога сохраняется при переходе по страницам
        m = await b.new_page(viewport={"width": 390, "height": 760}, device_scale_factor=3, is_mobile=True, has_touch=True)
        await m.goto(URL)
        mroot = m.locator('div[style*="2147483000"]')
        await mroot.locator(".fab").click()
        await mroot.locator(".inp textarea").fill("Какая гарантия?")
        await mroot.locator(".send").click()
        await wait_answer(m, 2)
        w = await mroot.locator(".panel").evaluate("e => e.getBoundingClientRect().width")
        check(f"телефон: чат на всю ширину экрана ({w:.0f}px)", w >= 389)
        await m.screenshot(path=str(DOCS / "screen-mobile.png"))
        await m.reload()
        await mroot.locator(".fab").click()
        check("после перезагрузки страницы диалог на месте", await mroot.locator(".m.user").count() == 1)
        await b.close()
    print("\nИТОГ:", "все проверки пройдены" if ok else "ЕСТЬ ОШИБКИ")
    sys.exit(0 if ok else 1)


asyncio.run(main())

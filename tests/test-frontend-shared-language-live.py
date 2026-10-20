#!/usr/bin/env python3
"""Demo-only Chrome check: main, trade, tenant and docs share EN/ZH preference.

Checks real localhost ports without logging in, modifying tenant state or
reading private files. Independent browser contexts avoid preexisting cookies.
"""
import argparse
from playwright.sync_api import sync_playwright

PORTS = {'main': 18094, 'trade': 18088, 'tenant': 18092, 'docs': 18096}


def run(mobile=False):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        context = browser.new_context(viewport={'width': 390 if mobile else 1440,
                                                'height': 844 if mobile else 900})
        def load(name, path='/'):
            page = context.new_page()
            page.goto(f'http://127.0.0.1:{PORTS[name]}{path}',
                      wait_until='domcontentloaded', timeout=30000)
            return page
        try:
            main = load('main')
            if mobile:
                # Mobile language select is inside an initially collapsed menu.
                main.locator('#mobileMenuToggle').click(timeout=10000)
                main.locator('#mobileLanguageSelect').select_option('zh-CN', timeout=10000)
            else:
                main.locator('#languageSelect').select_option('zh-CN', timeout=10000)
            assert main.evaluate('window.OTCSharedLanguage.get()') == 'zh-CN'
            print('PASS main switch to Chinese',flush=True)
            trade = load('trade','/#/login?location=N9NZV5')
            assert trade.evaluate('window.OTCSharedLanguage.get()') == 'zh-CN'
            assert trade.evaluate('localStorage.getItem("dc-trade-language")') == 'zh'
            print('PASS trade inherited Chinese',flush=True)
            tenant = load('tenant')
            assert tenant.evaluate('localStorage.getItem("otc.tenant.lang")') == 'zh'
            print('PASS tenant inherited Chinese',flush=True)
            docs = load('docs','/en/')
            docs.wait_for_url('**/zh/',timeout=12000)
            print('PASS API docs routed to Chinese',flush=True)
            tenant.get_by_text('EN',exact=True).first.click(timeout=10000)
            assert tenant.evaluate('window.OTCSharedLanguage.get()') == 'en'
            print('PASS tenant switch to English',flush=True)
            home = load('main')
            assert home.evaluate('window.OTCSharedLanguage.get()') == 'en'
            docs_en = load('docs','/zh/')
            docs_en.wait_for_url('**/en/', timeout=12000)
            print('PASS main and API docs inherited English',flush=True)
            trade.get_by_text('中文',exact=True).first.click(timeout=10000)
            assert trade.evaluate('window.OTCSharedLanguage.get()') == 'zh-CN'
            docs_zh = load('docs','/en/')
            docs_zh.wait_for_url('**/zh/',timeout=12000)
            print('PASS trade switch propagates to docs',flush=True)
            docs_zh.locator('a.md-select__link[hreflang=en]').first.evaluate('(el)=>el.click()')
            docs_zh.wait_for_url('**/en/',timeout=12000)
            after_docs=load('main')
            assert after_docs.evaluate('window.OTCSharedLanguage.get()') == 'en'
            print('PASS API docs switch propagates to main',flush=True)
            return True
        finally:
            browser.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mobile',action='store_true')
    args=parser.parse_args()
    run(mobile=args.mobile)
    print('SHARED_LANGUAGE_LIVE_PASS mobile=' + str(args.mobile))

if __name__ == '__main__':
    main()

#!/usr/bin/env node
'use strict'

// Public-site/API Docs integration smoke: no authentication or credentials.
// Run from the Playwright E2E runner, or with playwright installed.
const assert = require('node:assert/strict')
const { chromium } = require('playwright')

const publicSite = (process.env.PUBLIC_WEB_BASE_URL || 'http://127.0.0.1:18094').replace(/\/$/, '')
const docsSite = (process.env.API_DOCS_BASE_URL || 'http://127.0.0.1:18096').replace(/\/$/, '')
const canonical = 'https://api.opentradingcore.com/'
const routes = [
  '/en/', '/zh/', '/en/api-keys/', '/zh/api-keys/',
  '/en/delegated-trading/', '/zh/delegated-trading/',
  '/en/openapi/CATALOG_GENERATED/', '/zh/openapi/CATALOG_GENERATED/',
  '/en/examples/trader_broker_client.py', '/zh/examples/trader_broker_client.py'
]

async function main() {
  const browser = await chromium.launch({ headless: true })
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport })
      await page.goto(publicSite + '/', { waitUntil: 'domcontentloaded', timeout: 20000 })
      const links = await page.locator('a').evaluateAll(nodes => nodes
        .map(node => ({
          name: (node.textContent || node.getAttribute('aria-label') || '').trim(),
          href: node.href
        })).filter(item => item.href.includes('api.opentradingcore.com')))
      assert(links.length >= 2, 'main site must expose API links on PC and mobile')
      assert(links.every(link => link.href === canonical),
        'main-site API links must use only the canonical Docker-backed docs host')
      assert(links.some(link => /docs/i.test(link.name)),
        'main site must expose a visible View API Docs entry')
      console.log('MAIN_SITE_DOCS_LINK_PASS', viewport.width, 'links=' + links.length)
      await page.close()
    }
    // Docs are static Nginx assets. Check routes via HTTP directly rather
    // than waiting for browser-side scripts and third-party resource loading.
    const root = await fetch(docsSite + '/', { redirect: 'manual', signal: AbortSignal.timeout(12000) })
    assert(root.status === 302 && root.headers.get('location') === '/en/',
      'API Docs canonical root must redirect to the English entry point')

    for (const path of routes) {
      const result = await fetch(docsSite + path, { signal: AbortSignal.timeout(12000) })
      assert(result.status === 200, 'API Docs route failed: ' + path)
      const body = await result.text()
      if (path.includes('CATALOG_GENERATED')) {
        assert(body.includes('gw-ordersvr-placeorder'),
          'API method catalog must provide placeOrder anchor')
      }
      if (path.includes('api-keys')) {
        assert(body.includes('ORDER_WRITE'),
          'API key guide must explain scoped order access')
      }
      console.log('API_DOCS_ROUTE_PASS', path)
    }
    console.log('PUBLIC_API_DOCS_INTEGRATION_PASS')
  } finally {
    await browser.close()
  }
}

main().catch(error => {
  console.error('PUBLIC_API_DOCS_INTEGRATION_FAIL', error.message)
  process.exitCode = 1
})

const { chromium } = require('playwright');

const url = process.env.EVIDENCE_URL;
const output = process.env.EVIDENCE_OUTPUT;

if (!url || !output) {
  throw new Error('EVIDENCE_URL and EVIDENCE_OUTPUT are required');
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 1680, height: 1050 },
      deviceScaleFactor: 1,
    });
    await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
    await page.screenshot({ path: output, fullPage: true });
    console.log(`Evidence screenshot written to ${output}`);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

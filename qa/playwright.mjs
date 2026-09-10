import { chromium } from 'playwright';

const base = process.env.QA_URL || 'http://127.0.0.1:4173/qa.html';
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
const failures = [];

page.on('console', msg => { if (msg.type() === 'error') failures.push(`console: ${msg.text()}`); });
page.on('pageerror', err => failures.push(`pageerror: ${err.message}`));

await page.goto(base, { waitUntil: 'networkidle' });
await page.waitForTimeout(500);

const summary = await page.locator('#summary').innerText();
console.log(`QA summary: ${summary}`);

for (const role of ['owner', 'admin', 'smm', 'guest']) {
  await page.locator(`[data-role="${role}"]`).click();
  await page.waitForTimeout(100);
  const roleText = await page.locator('#app .role').innerText();
  if (roleText !== role.toUpperCase()) failures.push(`${role}: role label is ${roleText}`);
  const more = page.locator('#app [data-more]');
  await more.click();
  await page.waitForTimeout(50);
  if (!(await page.locator('#drawer').evaluate(el => el.classList.contains('open')))) failures.push(`${role}: drawer did not open`);
  await page.locator('#drawer [data-drawer-close]').click();
  if (await page.locator('#drawer').evaluate(el => el.classList.contains('open'))) failures.push(`${role}: drawer did not close`);
}

if (failures.length) {
  console.error(failures.join('\n'));
  await page.screenshot({ path: 'qa-failure.png', fullPage: true });
  process.exit(1);
}

await page.screenshot({ path: 'qa-pass.png', fullPage: true });
await browser.close();
console.log('Browser smoke checks passed.');

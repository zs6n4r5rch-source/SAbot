import { chromium } from 'playwright';

const base = process.env.QA_URL || 'http://127.0.0.1:4173/qa.html';
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
const failures = [];

page.on('console', msg => { if (msg.type() === 'error') failures.push(`console: ${msg.text()}`); });
page.on('pageerror', err => failures.push(`pageerror: ${err.message}`));
await page.route('**/api/smm/marketing-analytics**', async route => {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ role: 'smm', guests: 42, campaigns: 4, telegram_links: 12, marketing_consent: 9 }) });
});

await page.goto(base, { waitUntil: 'networkidle' });
await page.waitForTimeout(500);
await page.addScriptTag({ url: '/static/role-ui-v2.js?v=qa' });
await page.waitForTimeout(100);

const routeLabels = {
  overview: 'Главная', work: 'Работа', finance: 'Финансы', warehouse: 'Склад',
  crm: 'CRM', crmSearch: 'Поиск гостей', localLinks: 'Telegram / consent', analytics: 'Аналитика',
  shifts: 'Смены', previous: 'Предыдущая смена', closeReports: 'Закрытия смен', penalties: 'Штрафы',
  salary: 'Зарплата', admin: 'Контроль администратора', profiles: 'Профили доступа', settings: 'Настройки',
  campaigns: 'Кампании', guest: 'Мой профиль', warehouseCritical: 'Критические остатки',
  warehouseCategories: 'Категории склада', warehouseArrivals: 'Приходы', warehouseSales: 'Продажи товаров',
  warehouseHistory: 'История склада', warehouseWriteoffs: 'Списания', warehouseInventories: 'Инвентаризации',
  warehouseDiscrepancies: 'Расхождения',
};
const allowed = {
  owner: Object.keys(routeLabels),
  admin: ['overview','work','warehouse','crm','crmSearch','localLinks','shifts','previous','closeReports','penalties','salary','admin','profiles','settings','warehouseCritical','warehouseCategories','warehouseArrivals','warehouseSales','warehouseHistory','warehouseWriteoffs','warehouseInventories','warehouseDiscrepancies'],
  smm: ['overview','crm','crmSearch','localLinks','campaigns'],
  guest: ['overview','guest'],
};

const summary = await page.locator('#summary').innerText();
console.log(`QA bootstrap summary: ${summary}`);

for (const role of ['owner', 'admin', 'smm', 'guest']) {
  await page.evaluate(r => window.__SA_START_APP__(r), role);
  await page.waitForTimeout(120);
  const roleText = await page.locator('#app .role').innerText();
  if (roleText !== role.toUpperCase()) failures.push(`${role}: role label is ${roleText}`);

  const nav = await page.locator('#app .bottom button').allTextContents();
  const expectedNav = role === 'owner' ? ['Главная','Работа','Финансы','Ещё']
    : role === 'admin' ? ['Главная','Работа','Склад','Ещё']
    : role === 'smm' ? ['Главная','Работа','Ещё']
    : ['Главная','Профиль','Ещё'];
  for (const item of expectedNav) if (!nav.some(x => x.trim() === item)) failures.push(`${role}: missing nav ${item}`);
  if (role !== 'owner' && nav.some(x => x.trim() === 'Финансы')) failures.push(`${role}: finance leaked into bottom nav`);

  const homeText = await page.locator('#app').innerText();
  if (role === 'owner' && !homeText.includes('12 345') && !homeText.includes('12 345')) failures.push('owner: revenue fixture not rendered');
  if (role === 'admin' && !homeText.includes('3')) failures.push('admin: warehouse KPI fixture not rendered');
  if (role === 'smm' && (!homeText.includes('42') || !homeText.includes('12') || !homeText.includes('9'))) failures.push('smm: marketing KPI fixture not rendered');
  if (role === 'guest' && !homeText.includes('Тестовый гость')) failures.push('guest: profile fixture not rendered');

  const more = page.locator('#app [data-more], #app [data-smm-more]').first();
  if (!(await more.count())) { failures.push(`${role}: missing «Ещё»`); continue; }
  await more.click();
  await page.waitForTimeout(50);
  if (!(await page.locator('#drawer').evaluate(el => el.classList.contains('open')))) failures.push(`${role}: drawer did not open`);
  const drawerText = await page.locator('#drawer').innerText();
  if (role === 'owner' && !drawerText.includes('Контроль администратора')) failures.push('owner: admin control missing');
  if (role === 'owner' && !drawerText.includes('Настройки')) failures.push('owner: settings missing');
  if (role === 'admin' && drawerText.includes('Финансы')) failures.push('admin: finance leaked into drawer');
  if (role === 'admin' && !drawerText.includes('Склад')) failures.push('admin: warehouse missing');
  if (role === 'admin' && !drawerText.includes('Зарплата')) failures.push('admin: salary missing');
  if (role === 'smm' && !drawerText.includes('CRM')) failures.push('smm: CRM missing');
  if (role === 'smm' && drawerText.includes('Финансы')) failures.push('smm: finance leaked into drawer');
  if (role === 'guest' && !drawerText.includes('Мой профиль')) failures.push('guest: profile missing');

  const close = page.locator('#drawer [data-drawer-close]').first();
  if (await close.count()) await close.click(); else await page.locator('#drawerBackdrop').click();
  if (await page.locator('#drawer').evaluate(el => el.classList.contains('open'))) failures.push(`${role}: drawer did not close`);

  for (const route of allowed[role]) {
    if (route === 'overview' || route === 'guest') continue;
    const currentMore = page.locator('#app [data-more], #app [data-smm-more]').first();
    await currentMore.click();
    const label = routeLabels[route];
    const button = page.locator(`#drawer [data-drawer-page], #drawer [data-smm-page]`).filter({ hasText: label }).first();
    if (!(await button.count())) { failures.push(`${role}: route ${route} missing from drawer`); await page.locator('#drawerBackdrop').click(); continue; }
    await button.click();
    await page.waitForTimeout(40);
    const heading = await page.locator('#app .section-head h1').innerText().catch(() => '');
    if (!heading.includes(label)) failures.push(`${role}: route ${route} rendered heading ${heading}`);
  }
}

if (failures.length) {
  console.error(failures.join('\n'));
  await page.screenshot({ path: 'qa-failure.png', fullPage: true });
  process.exit(1);
}

await page.screenshot({ path: 'qa-pass.png', fullPage: true });
await browser.close();
console.log('Browser smoke + product acceptance checks passed.');

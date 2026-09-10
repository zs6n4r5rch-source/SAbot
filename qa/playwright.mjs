import { chromium } from 'playwright';

const base = process.env.QA_URL || 'http://127.0.0.1:4173/static/qa.html';
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
const failures = [];

page.on('console', msg => { if (msg.type() === 'error') failures.push(`console: ${msg.text()}`); });
page.on('pageerror', err => failures.push(`pageerror: ${err.message}`));
await page.goto(base, { waitUntil: 'networkidle' });
await page.waitForTimeout(600);

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
  admin: ['overview','work','warehouse','shifts','previous','closeReports','penalties','salary','warehouseCritical','warehouseCategories','warehouseArrivals','warehouseSales','warehouseHistory','warehouseWriteoffs','warehouseInventories','warehouseDiscrepancies'],
  smm: ['overview','crm','crmSearch','localLinks','campaigns'],
  guest: ['overview','guest'],
};

const expectedNav = {
  owner: ['Главная','Работа','Финансы','Ещё'],
  admin: ['Главная','Работа','Склад','Ещё'],
  smm: ['Главная','Работа','CRM','Ещё'],
  guest: ['Главная','Профиль','Ещё'],
};

console.log(`QA bootstrap summary: ${await page.locator('#summary').innerText()}`);

for (const role of ['owner', 'admin', 'smm', 'guest']) {
  const roleButton = page.locator(`#roles [data-role="${role}"]`).first();
  if (!(await roleButton.count())) { failures.push(`${role}: missing QA role control`); continue; }
  await roleButton.click();
  await page.waitForTimeout(80);

  const roleText = await page.locator('#app .role').innerText();
  if (roleText !== role.toUpperCase()) failures.push(`${role}: role label is ${roleText}`);

  const nav = await page.locator('#app .bottom button').allTextContents();
  for (const item of expectedNav[role]) if (!nav.some(x => x.trim() === item)) failures.push(`${role}: missing nav ${item}`);
  if (role !== 'owner' && nav.some(x => x.trim() === 'Финансы')) failures.push(`${role}: finance leaked into bottom nav`);

  const homeText = await page.locator('#app').innerText();
  if (role === 'owner' && !homeText.includes('12 345') && !homeText.includes('12 345')) failures.push('owner: revenue fixture not rendered');
  if (role === 'admin' && !homeText.includes('3')) failures.push('admin: warehouse KPI fixture not rendered');
  if (role === 'smm' && (!homeText.includes('42') || !homeText.includes('12') || !homeText.includes('4'))) failures.push('smm: marketing KPI fixture not rendered');
  if (role === 'guest' && !homeText.includes('Тестовый гость')) failures.push('guest: profile fixture not rendered');

  const more = page.locator('#app [data-more]').first();
  if (!(await more.count())) { failures.push(`${role}: missing «Ещё»`); continue; }
  await more.click();
  await page.waitForTimeout(50);
  if (!(await page.locator('#drawer').evaluate(el => el.classList.contains('open')))) failures.push(`${role}: drawer did not open`);
  const drawerText = await page.locator('#drawer').innerText();
  if (role === 'owner' && !drawerText.includes('Контроль администратора')) failures.push('owner: admin control missing');
  if (role === 'owner' && !drawerText.includes('Настройки')) failures.push('owner: settings missing');
  if (role === 'admin' && drawerText.includes('Финансы')) failures.push('admin: finance leaked into drawer');
  if (role === 'admin' && drawerText.includes('CRM')) failures.push('admin: CRM leaked into drawer');
  if (role === 'admin' && drawerText.includes('Контроль администратора')) failures.push('admin: owner control leaked into drawer');
  if (role === 'admin' && !drawerText.includes('Склад')) failures.push('admin: warehouse missing');
  if (role === 'admin' && !drawerText.includes('Зарплата')) failures.push('admin: salary missing');
  if (role === 'smm' && !drawerText.includes('CRM')) failures.push('smm: CRM missing');
  if (role === 'smm' && drawerText.includes('Финансы')) failures.push('smm: finance leaked into drawer');
  if (role === 'guest' && !drawerText.includes('Мой профиль')) failures.push('guest: profile missing');

  const close = page.locator('#drawer [data-drawer-close]').first();
  if (await close.count()) await close.click();
  else if (await page.locator('#drawer').evaluate(el => el.classList.contains('open'))) await page.locator('#drawerBackdrop').evaluate(el => el.click());
  if (await page.locator('#drawer').evaluate(el => el.classList.contains('open'))) failures.push(`${role}: drawer did not close`);

  for (const route of allowed[role]) {
    if (route === 'overview' || route === 'guest') continue;
    const currentMore = page.locator('#app [data-more]').first();
    await currentMore.click();
    const label = routeLabels[route];
    const button = page.locator(`#drawer [data-drawer-page]`).filter({ hasText: label }).first();
    if (!(await button.count())) {
      failures.push(`${role}: route ${route} missing from drawer`);
      if (await page.locator('#drawer').evaluate(el => el.classList.contains('open'))) await page.locator('#drawerBackdrop').evaluate(el => el.click());
      continue;
    }
    await button.evaluate(el => el.click());
    await page.waitForTimeout(40);
    const heading = await page.locator('#app .section-head h1').innerText().catch(() => '');
    if (!heading.includes(label)) failures.push(`${role}: route ${route} rendered heading ${heading}`);
  }
}

if (failures.length) {
  console.error(failures.join('\n'));
  await page.screenshot({ path: 'qa-failure.png', fullPage: true });
  await browser.close();
  process.exit(1);
}

await page.screenshot({ path: 'qa-pass.png', fullPage: true });
await browser.close();
console.log('Browser smoke + product acceptance checks passed.');

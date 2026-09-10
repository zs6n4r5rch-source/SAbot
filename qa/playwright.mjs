import { chromium } from 'playwright';

const base = process.env.QA_URL || 'http://127.0.0.1:4173/static/qa-browser.html';
const browser = await chromium.launch({ headless: true });
const failures = [];
const routeLabels={overview:'Главная',work:'Работа',finance:'Финансы',warehouse:'Склад',crm:'CRM',crmSearch:'Поиск гостей',localLinks:'Telegram / согласие',analytics:'Аналитика',shifts:'Смены',previous:'Предыдущая смена',closeReports:'Закрытия смен',penalties:'Штрафы',salary:'Зарплата',admin:'Контроль администратора',profiles:'Профили доступа',settings:'Настройки',campaigns:'Кампании',guest:'Мой профиль',warehouseCritical:'Критические остатки',warehouseCategories:'Категории склада',warehouseArrivals:'Приходы',warehouseSales:'Продажи товаров',warehouseHistory:'История склада',warehouseWriteoffs:'Списания',warehouseInventories:'Инвентаризации',warehouseDiscrepancies:'Расхождения'};
const allowed={owner:Object.keys(routeLabels),admin:['overview','work','warehouse','shifts','previous','closeReports','penalties','salary','warehouseCritical','warehouseCategories','warehouseArrivals','warehouseSales','warehouseHistory','warehouseWriteoffs','warehouseInventories','warehouseDiscrepancies'],smm:['overview','crm','crmSearch','localLinks','campaigns'],guest:['overview','guest']};
const expectedNav={owner:['Главная','Работа','Финансы','Ещё'],admin:['Главная','Работа','Склад','Ещё'],smm:['Главная','Работа','CRM','Ещё'],guest:['Главная','Профиль','Ещё']};

for(const role of ['owner','admin','smm','guest']){
  const page=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1});
  page.on('console',m=>{if(m.type()==='error')failures.push(`${role}: console: ${m.text()}`)});
  page.on('pageerror',e=>failures.push(`${role}: pageerror: ${e.message}`));
  await page.goto(`${base}?role=${role}`,{waitUntil:'networkidle'});
  await page.waitForFunction(r=>document.querySelector('#app .role')?.textContent?.trim()===r.toUpperCase(),role,{timeout:5000});
  const nav=await page.locator('#app .bottom button').allTextContents();
  for(const item of expectedNav[role])if(!nav.some(x=>x.trim()===item))failures.push(`${role}: missing nav ${item}`);
  if(role!=='owner'&&nav.some(x=>x.trim()==='Финансы'))failures.push(`${role}: finance leaked into bottom nav`);
  const home=await page.locator('#app').innerText();
  if(role==='owner'&&!home.includes('12 345')&&!home.includes('12 345'))failures.push('owner: revenue fixture not rendered');
  if(role==='admin'&&!home.includes('3'))failures.push('admin: warehouse KPI fixture not rendered');
  if(role==='smm'&&(!home.includes('42')||!home.includes('12')||!home.includes('4')))failures.push('smm: marketing KPI fixture not rendered');
  if(role==='guest'&&!home.includes('Тестовый гость'))failures.push('guest: profile fixture not rendered');
  const more=page.locator('#app [data-more]').first();
  if(!(await more.count())){failures.push(`${role}: missing «Ещё»`);await page.close();continue;}
  await more.click();await page.waitForTimeout(40);
  if(!(await page.locator('#drawer').evaluate(el=>el.classList.contains('open'))))failures.push(`${role}: drawer did not open`);
  const drawer=await page.locator('#drawer').innerText();
  if(role==='owner'&&!drawer.includes('Контроль администратора'))failures.push('owner: admin control missing');
  if(role==='owner'&&!drawer.includes('Настройки'))failures.push('owner: settings missing');
  if(role==='admin'&&drawer.includes('Финансы'))failures.push('admin: finance leaked into drawer');
  if(role==='admin'&&drawer.includes('CRM'))failures.push('admin: CRM leaked into drawer');
  if(role==='admin'&&drawer.includes('Контроль администратора'))failures.push('admin: owner control leaked into drawer');
  if(role==='admin'&&!drawer.includes('Склад'))failures.push('admin: warehouse missing');
  if(role==='admin'&&!drawer.includes('Зарплата'))failures.push('admin: salary missing');
  if(role==='smm'&&!drawer.includes('CRM'))failures.push('smm: CRM missing');
  if(role==='smm'&&drawer.includes('Финансы'))failures.push('smm: finance leaked into drawer');
  if(role==='guest'&&!drawer.includes('Мой профиль'))failures.push('guest: profile missing');
  const close=page.locator('#drawer [data-drawer-close]').first();
  if(await close.count())await close.click();else if(await page.locator('#drawer').evaluate(el=>el.classList.contains('open')))await page.locator('#drawerBackdrop').evaluate(el=>el.click());
  for(const route of allowed[role]){
    if(route==='overview'||route==='guest')continue;
    await page.locator('#app [data-more]').first().click();
    const button=page.locator(`#drawer [data-drawer-page]`).filter({hasText:routeLabels[route]}).first();
    if(!(await button.count())){failures.push(`${role}: route ${route} missing from drawer`);if(await page.locator('#drawer').evaluate(el=>el.classList.contains('open')))await page.locator('#drawerBackdrop').evaluate(el=>el.click());continue;}
    await button.evaluate(el=>el.click());await page.waitForTimeout(40);
    const heading=await page.locator('#app .section-head h1').innerText().catch(()=>'' );
    if(!heading.includes(routeLabels[route]))failures.push(`${role}: route ${route} rendered heading ${heading}`);
  }
  await page.screenshot({path:`qa-${role}.png`,fullPage:true});await page.close();
}
if(failures.length){console.error(failures.join('\n'));process.exit(1)}
console.log('Browser smoke + product acceptance checks passed.');
await browser.close();

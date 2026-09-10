import { chromium } from 'playwright';

const base = process.env.QA_URL || 'http://127.0.0.1:4173/static/qa-browser.html';
const browser = await chromium.launch({ headless: true });
const failures = [];
const matrix={owner:{overview:true,work:true,finance:true,warehouse:true,crm:true,crmSearch:true,localLinks:true,analytics:true,shifts:true,previous:true,closeReports:true,penalties:true,salary:true,admin:true,profiles:true,settings:true,campaigns:true,guest:false},admin:{overview:true,work:true,finance:false,warehouse:true,crm:false,crmSearch:false,localLinks:false,analytics:false,shifts:true,previous:true,closeReports:true,penalties:true,salary:true,admin:false,profiles:false,settings:false,campaigns:false,guest:false},smm:{overview:true,work:false,finance:false,warehouse:false,crm:true,crmSearch:true,localLinks:true,analytics:false,shifts:false,previous:false,closeReports:false,penalties:false,salary:false,admin:false,profiles:false,settings:false,campaigns:true,guest:false},guest:{overview:true,work:false,finance:false,warehouse:false,crm:false,crmSearch:false,localLinks:false,analytics:false,shifts:false,previous:false,closeReports:false,penalties:false,salary:false,admin:false,profiles:false,settings:false,campaigns:false,guest:true}};

for(const role of Object.keys(matrix)){
  const page=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1});
  page.on('console',m=>{if(m.type()==='error')failures.push(`${role}: console: ${m.text()}`)});
  page.on('pageerror',e=>failures.push(`${role}: pageerror: ${e.message}`));
  await page.goto(`${base}?role=${role}`,{waitUntil:'networkidle'});
  await page.waitForFunction(()=>window.__QA_READY__&&window.__SA_QA_CAN__,null,{timeout:5000});
  for(const [route,expected] of Object.entries(matrix[role])){
    const actual=await page.evaluate(([r,p])=>window.__SA_QA_CAN__(r,p),[role,route]);
    if(actual!==expected)failures.push(`${role}: can(${route})=${actual}, expected ${expected}`);
  }
  const start=await page.evaluate(()=>typeof window.__SA_START_APP__==='function');
  if(!start)failures.push(`${role}: app start contract missing`);
  await page.screenshot({path:`qa-${role}.png`,fullPage:true});
  await page.close();
}

if(failures.length){console.error(failures.join('\n'));process.exit(1)}
console.log('Browser smoke + role acceptance checks passed.');
await browser.close();

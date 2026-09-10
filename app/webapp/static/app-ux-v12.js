(function(){'use strict';
const init=()=>window.Telegram?.WebApp?.initData||'';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(Number(v||0))+' ₽';
async function loadBonuses(role){
  const app=document.getElementById('app'); if(!app)return;
  const r=await fetch('/api/app/bonuses',{cache:'no-store',headers:{'X-Telegram-Init-Data':init(),Accept:'application/json'}});
  const text=await r.text(); let d={}; try{d=text?JSON.parse(text):{};}catch{throw Error('Некорректный ответ сервера');}
  if(!r.ok)throw Error(d.detail||`HTTP ${r.status}`);
  const c=d.cleaning||{};
  const missed=(c.missed||[]).map(x=>`<div class="review-item"><div><b>Смена #${esc(x.langame_shift_id||x.shift_id)}</b><div class="review-reason">Клуб ${esc(x.club_id)} · ${esc(x.ended_at||'')}</div></div><div class="review-score">Пропуск</div></div>`).join('');
  const records=(d.items||[]).map(x=>`<div class="review-item"><div><b>${esc(x.employee||'Бонус')}</b><div class="review-reason">${esc(x.reason)} · ${esc(x.created_at||'')}</div></div><div class="review-score">${money(x.amount)}</div></div>`).join('');
  const statusClass=c.missed?.length?'error':'notice';
  const status=c.status||'Нет данных';
  const body=`<header class="app-header"><div class="brand-row"><span class="mark"></span><div style="min-width:0"><div class="brand-name">Strike Arena</div><div class="small">БОНУСЫ</div></div></div><span class="role">${esc(role.toUpperCase())}</span></header><div class="section-head"><h1>Бонусы</h1><p>Уборка: 500 ₽ один раз за календарный месяц</p></div><section class="card"><div class="section-title"><h2>Бонус за уборку: 500 ₽ / месяц</h2></div><div class="${statusClass}"><b>${esc(status)}</b></div><div class="metric-strip"><div><div class="m-label">Обязательных уборок</div><div class="m-value">${esc(c.required_count||0)}</div></div><div><div class="m-label">Выполнено</div><div class="m-value">${esc(c.completed_count||0)}</div></div></div>${missed?`<div class="section-title"><h2>Пропущенные уборки</h2></div><div class="review-list">${missed}</div>`:''}</section>${records?`<section class="card"><div class="section-title"><h2>${role==='owner'?'Начисленные бонусы':'Мои бонусы'}</h2></div><div class="review-list">${records}</div></section>`:''}<div class="back"><button type="button" id="sa-bonus-back">← Назад</button></div>`;
  app.innerHTML=body;
  document.getElementById('sa-bonus-back')?.addEventListener('click',()=>window.__SA_START_APP__?.(role));
}
function install(){
  const app=document.getElementById('app'); if(!app)return;
  const role=(document.querySelector('.role')?.textContent||'').trim().toLowerCase();
  if(!['owner','admin'].includes(role))return;
  const work=document.querySelector('.actions-grid');
  if(work && !work.querySelector('[data-sa-bonuses]')){
    const b=document.createElement('button'); b.type='button'; b.textContent='Бонусы'; b.setAttribute('data-sa-bonuses','1'); work.appendChild(b);
    b.addEventListener('click',()=>loadBonuses(role).catch(e=>{window.alert(e.message||String(e));}));
  }
}
window.addEventListener('sa:app-state',e=>{if(e.detail?.state==='ready')setTimeout(install,0);});
window.__SA_UX_V12_READY__=true;
})();
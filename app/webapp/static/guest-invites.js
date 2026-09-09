/* Owner-only bulk guest invite surface. Keeps navigation owned by the unified shell. */
(function(){
  'use strict';
  var app=document.getElementById('app');
  if(!app)return;

  function tg(){return window.Telegram&&window.Telegram.WebApp?window.Telegram.WebApp:null;}
  function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function isOwner(){
    if(window.__SA_INVITE_OWNER__)return true;
    var role=document.querySelector('.role');
    return !!(role&&role.textContent.trim().toLowerCase()==='owner');
  }
  function api(path,options){
    var t=tg();
    if(!t||!t.initData)throw Error('Telegram initData не получен');
    var opts=options||{};
    opts.headers=Object.assign({'X-Telegram-Init-Data':t.initData,'Accept':'application/json'},opts.headers||{});
    opts.cache='no-store';
    return fetch(path,opts).then(function(r){return r.text().then(function(text){var d={};try{d=text?JSON.parse(text):{};}catch(e){throw Error('Некорректный ответ сервера HTTP '+r.status);}if(!r.ok)throw Error(d.detail||('HTTP '+r.status));return d;});});
  }
  function bottom(){return '<nav class="bottom"><button type="button" data-invite-home><span class="ico">⌂</span>Главная</button><button type="button"><span class="ico">▣</span>Работа</button><button type="button"><span class="ico">₽</span>Финансы</button><button type="button"><span class="ico">•••</span>Ещё</button></nav>';}
  function renderPage(){
    app.innerHTML='<header class="app-header"><div class="brand-row"><span class="mark"></span><div style="min-width:0"><div class="brand-name">Strike Arena</div><div class="small">Единый центр управления клубом</div></div></div><span class="role">OWNER</span></header>'+
      '<div class="back"><button type="button" data-invite-back>← Назад</button></div>'+
      '<div class="section-head"><h1>Инвайты гостей</h1><p>Создайте персональные одноразовые ссылки сразу для всех гостей клуба, у которых ещё нет привязанного Telegram.</p></div>'+
      '<div id="inviteResult"><div class="card"><div class="card-title">Персональные ссылки</div><p class="small">Ссылка действует 7 дней. Уже привязанные профили повторно не приглашаются, действующие ссылки переиспользуются.</p><button type="button" class="primary" id="createBulkInvites">Создать инвайты для всех гостей</button></div></div>'+bottom();
    document.querySelector('[data-invite-back]').onclick=function(){window.__SA_START_APP__('owner');};
    document.querySelector('[data-invite-home]').onclick=function(){window.__SA_START_APP__('owner');};
    document.getElementById('createBulkInvites').onclick=create;
  }
  function copy(text,button){
    var done=function(){var old=button.textContent;button.textContent='Скопировано';setTimeout(function(){button.textContent=old;},1200);};
    if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(done).catch(function(){fallback(text,done);});}
    else fallback(text,done);
  }
  function fallback(text,done){var ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();try{document.execCommand('copy');done();}finally{ta.remove();}}
  function create(){
    var button=document.getElementById('createBulkInvites'),out=document.getElementById('inviteResult');
    button.disabled=true;button.textContent='Создаём…';
    api('/api/app/guest/invites/bulk',{method:'POST'}).then(function(d){
      var items=d.items||[];
      var html='<div class="card"><div class="card-title">Результат</div><div class="grid">'+
        '<div class="stat"><div class="label">Всего гостей</div><div class="value">'+esc(d.total)+'</div></div>'+
        '<div class="stat accent"><div class="label">Создано</div><div class="value">'+esc(d.created)+'</div></div>'+
        '<div class="stat"><div class="label">Повторно использовано</div><div class="value">'+esc(d.reused)+'</div></div>'+
        '<div class="stat"><div class="label">Уже привязаны</div><div class="value">'+esc(d.already_linked)+'</div></div></div>';
      if(items.length){
        var all=items.map(function(x){return x.name+' — '+x.url;}).join('\n');
        html+='<button type="button" class="primary" id="copyAllInvites">Скопировать все ссылки</button><div class="list">'+items.map(function(x){return '<div class="row"><div class="row-main"><b>'+esc(x.name)+'</b><span>'+esc(x.phone||('Гость #'+x.guest_id))+' · до '+esc(new Date(x.expires_at).toLocaleDateString('ru-RU'))+'</span><span>'+esc(x.url)+'</span></div><button type="button" data-copy-invite="'+esc(x.url)+'">Копировать</button></div>';}).join('')+'</div>';
        html+='<div class="source">Скопируйте список и передайте персональные ссылки гостям. Отправка сообщений гостям автоматически не выполняется.</div>';
        setTimeout(function(){
          var allBtn=document.getElementById('copyAllInvites');if(allBtn)allBtn.onclick=function(){copy(all,allBtn);};
          document.querySelectorAll('[data-copy-invite]').forEach(function(b){b.onclick=function(){copy(b.getAttribute('data-copy-invite'),b);};});
        },0);
      }else html+='<div class="empty">Нет гостей, которым требуется привязка Telegram.</div>';
      html+='</div>';
      out.innerHTML=html;
    }).catch(function(e){out.innerHTML='<div class="error"><h2>Не удалось создать инвайты</h2><p>'+esc(e.message||e)+'</p><button type="button" class="primary" id="retryBulkInvites">Повторить</button></div>';var r=document.getElementById('retryBulkInvites');if(r)r.onclick=create;}).finally(function(){if(button){button.disabled=false;button.textContent='Создать инвайты для всех гостей';}});
  }
  function mountButton(){
    if(!isOwner())return;
    var groups=document.querySelectorAll('.drawer-group');
    for(var i=0;i<groups.length;i++){
      var title=groups[i].querySelector('.drawer-group-title');
      if(title&&title.textContent.trim()==='Администрирование'&&!groups[i].querySelector('[data-owner-invites]')){
        var b=document.createElement('button');b.type='button';b.setAttribute('data-owner-invites','1');b.textContent='Инвайты гостей';groups[i].appendChild(b);
      }
    }
  }
  document.addEventListener('click',function(ev){
    var more=ev.target.closest&&ev.target.closest('[data-more]');
    if(more&&isOwner())setTimeout(mountButton,0);
    var invite=ev.target.closest&&ev.target.closest('[data-owner-invites]');
    if(invite){ev.preventDefault();ev.stopImmediatePropagation();renderPage();}
  },true);
  window.addEventListener('sa:app-state',function(ev){
    window.__SA_INVITE_OWNER__=ev.detail&&ev.detail.role==='owner';
    if(window.__SA_INVITE_OWNER__&&ev.detail.state==='ready')setTimeout(mountButton,0);
  });
  setTimeout(mountButton,300);
}());

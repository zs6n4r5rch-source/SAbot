from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from pathlib import Path


JS = r'''<script>
(function(){
  const oldAdmins=window.admins;
  if(typeof oldAdmins!=='function') return;
  window.admins=async function(){
    await oldAdmins();
    try{
      const d=await api('/api/admins');
      document.querySelectorAll('#root .admin-card').forEach((card,i)=>{
        const item=(d.items||[])[i];
        if(!item || card.querySelector('.manual-penalty-btn')) return;
        const b=document.createElement('button');
        b.className='secondary manual-penalty-btn';
        b.style.marginTop='8px';
        b.textContent='⚠️ Штрафы';
        b.onclick=()=>adminPenalties(Number(item.id));
        card.appendChild(b);
      });
    }catch(e){console.error(e)}
  };
})();
</script>'''


async def _index():
    from app.webapp.current_summary_v3 import _index as current_index
    response = await current_index()
    html = response.body.decode('utf-8')
    return HTMLResponse(html.replace('</body>', JS + '</body>', 1))


def install(web_app):
    web_app.add_api_route('/', _index, methods=['GET'], include_in_schema=False)
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path == '/' and route.endpoint is _index:
            web_app.routes.remove(route)
            web_app.routes.insert(0, route)
            break

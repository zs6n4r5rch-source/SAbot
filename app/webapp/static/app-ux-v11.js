(function(){'use strict';
/* Live dashboard refresh is owned by app-guard.js. This layer intentionally adds no competing polling. */
(function loadV12(){
  if(document.querySelector('script[data-sa-ux-v12]'))return;
  const s=document.createElement('script');s.src='/static/app-ux-v12.js?v=1';s.async=false;s.dataset.saUxV12='1';document.head.appendChild(s);
})();
window.__SA_UX_V11_READY__=true;
})();
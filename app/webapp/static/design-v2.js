/* Compatibility loader: the unified shell owns navigation; role-ui isolates role-specific presentation. */
(function(){'use strict';
  ['/static/role-ui-v2.js?v=2','/static/smm-actions.js?v=2','/static/guest-invites.js?v=1'].forEach(function(src){
    var s=document.createElement('script');s.src=src;document.body.appendChild(s);
  });
}());

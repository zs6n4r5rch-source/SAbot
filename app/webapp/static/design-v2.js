/* Compatibility loader: the unified shell owns navigation; this file only mounts functional secondary surfaces. */
(function(){'use strict';
  ['/static/smm-actions.js?v=2','/static/guest-invites.js?v=1'].forEach(function(src){
    var s=document.createElement('script');s.defer=true;s.src=src;document.body.appendChild(s);
  });
}());

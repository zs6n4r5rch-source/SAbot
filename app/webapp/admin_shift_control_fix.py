from app.webapp import admin_shift_control


def apply():
    marker = "<script>\nasync function admins"
    global_escape = "<script>\nconst esc=v=>String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));\nasync function admins"
    admin_shift_control.JS = admin_shift_control.JS.replace(marker, global_escape, 1)

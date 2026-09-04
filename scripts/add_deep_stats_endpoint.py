from pathlib import Path

path = Path('app/webapp/app.py')
s = path.read_text()
needle = '@app.get("/api/penalties")'
if 'from app.webapp.deep_stats import build_deep_stats' not in s:
    s = s.replace('from app.services.langame import langame_client, LangameAPIError\n', 'from app.services.langame import langame_client, LangameAPIError\nfrom app.webapp.deep_stats import build_deep_stats\n')
if '@app.get("/api/deep-stats")' not in s:
    route = '''@app.get("/api/deep-stats")\nasync def deep_stats(request: Request, days: int = 30):\n    user, _ = await current_user(request)\n    owner_required(user)\n    return await build_deep_stats(days)\n\n\n'''
    if needle not in s:
        raise SystemExit('endpoint insertion point not found')
    s = s.replace(needle, route + needle, 1)
path.write_text(s)

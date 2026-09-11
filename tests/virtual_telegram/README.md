# Virtual Telegram RBAC tests

This suite signs synthetic Telegram WebApp `initData` with the real HMAC scheme and sends requests to the production FastAPI ASGI app in-process via `httpx.ASGITransport`.

It verifies the current access contract:

- owner: full Mini App contour, including salary, penalties and settings;
- admin: operational contour only;
- admin: no salary and no penalty management;
- SMM: overview/CRM contour;
- guest: guest contour without staff binding;
- unbound accounts cannot claim staff roles;
- owner can preview admin UI shape;
- tampered Telegram `initData` is rejected.

## Running

Use a disposable PostgreSQL database. The suite needs the same application environment used by the backend, including `DATABASE_URL` and `TELEGRAM_BOT_TOKEN`.

```bash
pip install -e . pytest pytest-asyncio httpx
export DATABASE_URL=postgresql+asyncpg://localhost/sabot_test
export TELEGRAM_BOT_TOKEN=<real bot token>
alembic upgrade head
pytest tests/virtual_telegram/ -v
```

The suite does **not** contact Telegram. LANGAME-backed endpoints must be mocked or disabled in CI before treating the suite as a network-free test. The current tests focus on authorization and use endpoints whose access decision happens before external data is required.

This is not a replacement for a real Telegram client smoke test: button clicks, Telegram WebApp rendering, browser navigation, and live LANGAME data still require separate checks.

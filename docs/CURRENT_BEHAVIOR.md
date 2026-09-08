# G0 Audit — Current Behavior

Audit baseline: branch `main`, commit `7f59e1af16f880655c2ea9218096a0c809671847`.

## Confirmed from repository
- FastAPI web app is `app.webapp.app` and Telegram bot startup is `app.main`.
- PostgreSQL/SQLAlchemy and Alembic are used.
- LANGAME is configured as read-only in `app.services.langame`.
- LANGAME adapter currently exposes clubs, users, shifts, balances, sessions, transactions, operations, products, stock, product sales/arrivals, guest groups and guest search/profile.
- Existing application has accumulated several web UI modules and previously used runtime page composition/overrides.
- The new R1-R3 branch removes the runtime use of those override installers and introduces one unified Mini App shell plus `/api/app/*` business API.

## Not assumed
Gaming revenue, occupancy, ARPU, retention and other metrics are not treated as confirmed merely because they are requested. They require a confirmed source field/endpoint or an explicit derived formula.

## Production baseline
Render service: `strike-arena`, URL `https://strike-arena.onrender.com`, branch `main`, Docker runtime, auto-deploy enabled.

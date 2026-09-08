# Repository Audit (G0)

Status: CONFIRMED against repository `main` at `50a5569266f600ecd48697a7ab7938e1a85d03de`.

## 1. Current architecture

[CONFIRMED]
Source: repository tree and application modules.
Evidence: `app/main.py` starts the Telegram bot and Uvicorn; `app/webapp/app.py` owns the base FastAPI app; `app/webapp/unified_api.py` adds the newer `/api/app` contour.

The project is a mixed Telegram bot + FastAPI Mini App + PostgreSQL/SQLAlchemy application. LANGAME is treated as an external read-only source for supported integrations.

## 2. Runtime route owners

- `/`: `app.webapp.app.index`.
- Legacy `/api/*`: `app.webapp.app` plus installed routers.
- Unified `/api/app/*`: `app.webapp.unified_api.router`.
- RBAC middleware: `app.webapp.rbac_middleware.UnifiedRBACMiddleware` is installed in `main.py` for `/api/app/*`.

Discrepancy: `/` still imports `page_composer.compose_page`, while the target architecture requires one explicit production owner without legacy composition chains.

## 3. API inventory

Confirmed implemented contours include legacy summary/dashboard/admin/client/inventory/finance/analytics/statistics/export endpoints and unified overview/work-center/CRM groups/guest/warehouse/finance/previous shift/analytics endpoints.

Target-required endpoint groups not yet represented as one complete contract: `/api/crm`, `/api/crm/groups/{id}`, `/api/warehouse/categories`, `/api/warehouse/critical`, `/api/warehouse/sales`, `/api/shifts`, `/api/penalties`, `/api/admin/*`, `/api/smm/*`, `/api/guest/*`.

## 4. LANGAME integration inventory

[CONFIRMED — project contract]
- guest groups;
- guest search;
- product sales;
- clubs;
- balances;
- guest sessions;
- products;
- stock;
- shift/user synchronization.

[TO VERIFY]
Every field not explicitly validated by the current integration contract, including guest-by-id semantics, occupancy totals, balances/history detail, gaming revenue, COGS field availability, retention metrics, booking APIs and mutation APIs.

## 5. Database inventory

Confirmed local domains include clubs, employees, Telegram users/access profiles, shifts, product categories/products, inventory balances/operations/writeoffs/inventories/discrepancies, guests/guest links/consent, salary periods/adjustments/violations/payments, bonuses, audit, owner reports and SMM tasks/rates/access.

Migration chain reaches at least `0026_enforce_inventory_min_stock_default`; historical branches are merged by `0014_merge_shift_close_heads`.

## 6. Frontend ownership

The current tree contains multiple historical page and UI implementations (`current_summary.py`, `_v2`, `_v3`, `management_dashboard.py`, `work_center_v3.py`, `index_v2.html`, page composer and hotfix files). This is technical debt even where old startup injection has been neutralized.

## 7. Dead/shadowed code

[TO VERIFY before deletion]
`owner_critical_hotfix.py`, `owner_final_hotfix.py`, `sitecustomize.py`, old summary versions, page composer and several standalone static pages require dependency/runtime proof before deletion.

## 8. Existing penalties

[CONFIRMED — SAbot local]
`SalaryViolation` and bot/web penalty workflows exist. There is no confirmed `PenaltyType` directory matching the target approved-penalty workflow.

## 9. Existing Excel

Multiple exports exist, including analytics and statistics exports. There is no confirmed centralized `ExportService` satisfying the global KPI → detail → filtered Excel contract.

## 10. Existing RBAC

Backend auth validates Telegram Mini App init data. OWNER checks exist. Unified `/api/app/*` middleware denies roles outside owner/admin. SMM exists as a model role but is intentionally restricted in the unified middleware; GUEST role is not yet a first-class database/API contour.

## 11. Existing Admin

Admin shift control, penalties, inventory, clients and Telegram handlers exist. The target unified ADMIN contour is incomplete.

## 12. Existing SMM

SMM access, task rates/tasks, bot module and API/static modules exist. Campaign delivery through LANGAME is not confirmed and must not be simulated.

## 13. Existing Guest

Guest onboarding, Telegram linking and consent exist. A first-class backend-isolated GUEST API contour for own profile/balance/history is incomplete.

## 14. Technical debt

- parallel legacy and unified API/UI contours;
- multiple historical summary/work-center implementations;
- ad-hoc exports;
- inconsistent timezone use across modules;
- empty repositories package;
- incomplete centralized permissions;
- LANGAME integration verification gaps.

## 15. Migration risks

- production database migration history must be checked live before schema changes;
- do not rewrite applied Alembic revisions;
- legacy deletion requires runtime/import/route/frontend/deployment dependency proof;
- production data must never be replaced with fixtures or fake fallbacks.

## 16. Discrepancies

1. Expected: one root/home/work-center owner. Actual: root still composes through `page_composer`; historical UI modules remain. Impact: ownership is not fully clean. Resolution: explicit shell owner and later legacy cleanup after production acceptance.
2. Expected: four role contours. Actual: owner/admin enforced, SMM partially modeled, GUEST absent as first-class role. Impact: incomplete data isolation matrix. Resolution: implement centralized permissions and dedicated contours.
3. Expected: centralized ExportService/timezone. Actual: multiple export paths and mixed direct `datetime.now(...)` use. Resolution: create shared services and migrate new contour.

## 17. Confirmed / Hypothesis / To Verify matrix

| Feature | Current SAbot | LANGAME | API | Status |
|---|---|---|---|---|
| Guests | Yes | CONFIRMED capability | partial project integration | TO VERIFY |
| Groups | Yes | CONFIRMED capability | project endpoint exists | TO VERIFY contract fields |
| Sales | Yes | CONFIRMED capability | integrated | CONFIRMED project integration |
| COGS | partial | CONFIRMED capability | field availability not guaranteed | TO VERIFY |
| Warehouse | Yes | CONFIRMED capability | integrated | CONFIRMED project integration |
| Penalties | Yes | not required | local | SAbot NEW |
| Excel | Yes | n/a | local | partial |
| SMM | Yes | capability/API uncertain | partial local | TO VERIFY |
| Guest self-service | partial | capability uncertain | incomplete | TO VERIFY |
| Retention | partial | metrics capability | incomplete | TO VERIFY |

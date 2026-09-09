# Final TZ audit — 2026-09-09

## Scope
Verified current `main` against the final Strike Arena Mini App target: four roles, deterministic Telegram startup, unified navigation, backend RBAC, LANGAME read-only, domain separation, guest isolation, SMM campaigns, timezone policy, Excel/export and schedulers.

## Fixed in this pass

- Added `app/webapp/final_contract_api.py` as the authoritative subject-scoped Mini App contract layer.
- Registered it before the legacy `unified_api` router.
- Removed runtime installation of `admin_shift_control.py` from production bootstrap; the old installer was a route/root mutation mechanism outside the target architecture.
- ADMIN shift, previous-shift, close-report, penalty and salary endpoints are now scoped to the authenticated employee.
- SMM can use CRM search/groups/local-links through the approved marketing contour without receiving finance access.
- Guest profile now resolves balance/bonus/history from the authenticated local Telegram↔guest link using LANGAME read-only calls when available.
- Added SMM campaign creation, scheduling and immediate send API actions, backed by the existing marketing scheduler and Telegram sender.
- Added a functional SMM Mini App surface without reintroducing a MutationObserver or legacy navigation controller.
- Added regression coverage for the final role/domain contract.

## Confirmed architecture

- One FastAPI root shell serves `/`.
- `app/main.py` registers the final contract before the legacy unified router.
- `UnifiedRBACMiddleware` remains active for `/api/app/*`.
- Telegram `initData` is validated server-side.
- LANGAME mutation methods remain blocked; only the documented read-only guest search POST is allowlisted.
- PostgreSQL remains the local control/audit/salary/marketing layer.
- `local_day_bounds()` and the configured IANA timezone are used by the authoritative owner dashboard.

## Remaining legacy/dead code

The repository still contains historical web modules and static pages (`current_summary*`, `management_dashboard`, `page_composer`, legacy HTML pages, etc.). They were not deleted blindly. The production bootstrap no longer installs the old `admin_shift_control` route mutation chain; the unified shell and final contract are the active contour.

## External verification limits

The following cannot be fully simulated by repository tooling:

1. Telegram iOS WebView rendering/touch behavior on a physical device.
2. Real SMM delivery to Telegram recipients without performing an actual campaign.
3. Every possible upstream LANGAME payload variant beyond the production responses observed by the running sync.

These are runtime/E2E boundaries, not known code-level blockers.

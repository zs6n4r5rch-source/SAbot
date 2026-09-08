# Route Ownership — R1-R3

## Web runtime owner
`app.webapp.app` is the single FastAPI application object.

## Root UI
`GET /` is owned by `app.webapp.app.index` and serves the unified static shell. The legacy `page_composer` is compatibility-only and performs no injection.

## Unified business API
All new management UI data flows through the `/api/app/*` router in `app/webapp/unified_api.py`.

Current routes:
- `/api/app/overview`
- `/api/app/work-center`
- `/api/app/crm/groups`
- `/api/app/crm/groups/{group_id}/guests`
- `/api/app/crm/guests/{guest_id}`
- `/api/app/warehouse`
- `/api/app/finance`
- `/api/app/shifts/previous`
- `/api/app/analytics`

Legacy APIs remain available for compatibility while the new UI is verified. They are not used by the new shell for its core screens.

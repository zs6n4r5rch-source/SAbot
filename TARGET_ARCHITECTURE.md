# Target Architecture (G1)

## Layers

Data Layer → LANGAME Integration → Business Services → API Contracts → Central RBAC → Unified Frontend Shell → OWNER / ADMIN / SMM / GUEST.

## Route ownership

One production FastAPI application owns `/`. One shell owns home and Work Center. Domain APIs are mounted once. No runtime monkey-patch or sitecustomize chain may redefine page functions.

## API contracts

The canonical contour uses `/api/app/*` during migration, with explicit domain groups: summary, work-center, finance, crm, warehouse, shifts, penalties, analytics, admin, smm and guest. Missing external capabilities return explicit `null`, 404/409/502 or a structured status; never fake success.

## Permissions

Permissions are centralized and checked in backend before domain access.

- OWNER: all management read/write operations explicitly granted.
- ADMIN: own shift/hall/guests/sales/warehouse/tasks/own penalties only.
- SMM: audience/segments/campaigns/activities/results only.
- GUEST: own profile and linked records only.

Frontend visibility is convenience, not authorization.

## Timezone

Store instants in UTC. Use one configured IANA timezone for club-day boundaries and display/export conversion. Domain code must use a shared clock/timezone service rather than scattered local-time arithmetic.

## Exports

A shared `ExportService` owns workbook creation, filters, period, timezone metadata, totals, numeric/date types and Cyrillic-safe output. KPI drilldowns export the exact filtered detail used for the KPI.

## Logging and errors

Integration calls record success/failure with source and operation context without leaking secrets. Empty results and failed calls are distinct states. Upstream LANGAME errors propagate as explicit dependency errors.

## Data isolation

All resource lookup APIs apply role and subject scoping server-side. Guest records are resolved from the authenticated Telegram identity/link, never from a freely supplied guest ID alone. Admin endpoints cannot expose owner controls; SMM cannot expose restricted finance.

## Status vocabulary

`CONFIRMED`, `HYPOTHESIS`, `TO VERIFY`, `SAbot NEW`, and `BLOCKED` are used for external capability claims and implementation decisions.

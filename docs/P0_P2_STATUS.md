# P0–P2 implementation status

This branch keeps the existing page composer as the single root-page composition point and applies the known LANGAME loyalty-count runtime fix before web routes are registered.

## Confirmed in source
- Work Center UI/JS is composed into the root page.
- Work Center reads active LANGAME sessions and exposes them as “Гости сейчас”.
- Shift reports have a dedicated API and historical report UI.
- Warehouse/critical-stock and control APIs are present.
- CRM group and guest APIs are present.
- Owner-only financial/analytics endpoints are protected by `owner_required`.
- Administrator UI is restricted to own shifts/own accruals by the composed admin guard.

## Fixed here
- LANGAME loyalty group counts no longer call `.get()` on an un-awaited coroutine.
- A regression test covers the corrected pagination shape.

## Still requires production verification
- Actual LANGAME data values and semantics in the connected club.
- Telegram role/access behavior with real users.
- Render deployment health and live endpoint smoke tests.
- Full browser E2E navigation/button audit.

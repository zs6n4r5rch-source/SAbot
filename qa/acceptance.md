# SAbot UI acceptance matrix

This is a product-level QA checklist, not only a smoke-test list. A screen is considered complete only when its route, role visibility, and **actual content** match the agreed product scope.

## OWNER

### Главная
- Revenue / product sales totals.
- Payment breakdown: cash, card, mobile.
- KPI relevant to the owner, including guests and open shifts.
- Source/status notes when a metric is unavailable; no invented values.

### Работа
- Current/open shifts.
- Previous shift details.
- Shift closing reports.
- Penalties.
- Salary calculations/payments.
- Shift-level signals needed for review.

### Финансы
- Cashflow / payment totals.
- Product sales totals.
- Unsupported values shown explicitly as unavailable, not fabricated.

### Аналитика
- Periods: 7 days, 30 days, current month.
- Sales, inventory, administrators, salary, clients views.
- Administrator ranking by product sales, hours, shifts, sales per hour.
- Administrator detail: shifts, attributed sales, cash difference, approved write-offs, discrepancies, overlapping salary periods.
- Shift comparison with personal baseline where sufficient history exists (5+ shifts); deviations are review signals, not proof of misconduct.

### Контроль администраторов / Требует внимания
- Risk score 0–100 and explainable reasons.
- Concrete shifts/events behind the signal.
- Compact review dossier.
- No automatic accusation or guilt decision.

### Настройки
- Daily report: enable/disable, time, IANA timezone, report sections, Excel toggle.
- Administrator access: Telegram binding, block/unblock, rebind Telegram ID, recent actions.
- Add owner.

## ADMIN

### Главная / Работа
- Own operational shift information and relevant personal statistics.
- Current shift / previous shift / closing flow.
- Night-shift cleaning confirmation and the fixed 500 ₽ cleaning bonus when applicable.
- Salary information for the administrator.

### Склад
- Current warehouse state.
- Critical stock.
- Categories.
- Arrivals.
- Product sales.
- Warehouse history.
- Write-offs.
- Inventories.
- Discrepancies.
- Local control operations must not overwrite LANGAME source-of-truth data.

## SMM

### Главная / CRM
- Guest count and marketing-relevant KPIs.
- CRM groups.
- Guest search.
- Telegram links / marketing consent.

### Кампании
- Campaign list/state.
- Campaign creation with consent-based audience only.
- Campaign message and scheduling state.

## GUEST

### Мой профиль
- Linked guest profile data when linked.
- Marketing consent state.
- Clear unlinked state and onboarding instruction when no guest link exists.

## Cross-role acceptance

- No role sees menu items outside its permission matrix.
- Owner preview of another role must render that role's UI, not leak owner navigation.
- Every visible section must have meaningful labels and its planned fields/lists; a generic JSON/scalar dump is not accepted as final UX.
- Loading, empty, error, and retry states must be usable.
- Drawer opens and closes by button, backdrop, and Escape.
- Back navigation works after entering nested sections.
- API failures must not leave a blank or stuck screen.
- Read-only LANGAME policy is preserved: UI actions may change the bot's local control layer but must not mutate LANGAME operational data.

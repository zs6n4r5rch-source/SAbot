# Data Sources — R1-R3

| Domain | Source | Status |
|---|---|---|
| Telegram identity/role | SAbot PostgreSQL | CONFIRMED |
| Employees/shifts | LANGAME + local cached relations | CONFIRMED BY PROJECT |
| Product sales | LANGAME `products/expense` | CONFIRMED BY PROJECT |
| Product catalog | LANGAME `products/list` | CONFIRMED BY PROJECT |
| Warehouse | LANGAME `goods/list` | CONFIRMED BY PROJECT |
| Guest groups | LANGAME `guests/groups` | CONFIRMED BY PROJECT |
| Guest search/profile | LANGAME `guests/search` | CONFIRMED BY PROJECT |
| Guest sessions | LANGAME `guests/sessions` | CONFIRMED BY PROJECT |
| Gaming revenue | — | TO_VERIFY |
| Occupancy/PC count | — | TO_VERIFY |
| ARPU/retention | — | TO_VERIFY until a valid event/history formula is available |
| Product COGS | LANGAME sale row cost field if actually present; otherwise not fabricated | TO_VERIFY |

Rule: NULL/TO_VERIFY is preferable to a plausible but false number.

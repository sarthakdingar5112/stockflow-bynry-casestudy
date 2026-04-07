# StockFlow – Inventory Management System
### Bynry Backend Engineering Intern – Case Study
**Submitted by:** Sarthak Dingar

---

## Repository Structure

```
stockflow/
├── part1/
│   ├── buggy_code.py          # Original code with issue annotations
│   └── fixed_code.py          # Corrected implementation with explanations
├── part2/
│   └── schema.sql             # Full PostgreSQL database schema
├── part3/
│   └── low_stock_alerts.py    # Low-stock alert API endpoint
└── README.md                  # This file
```

---

## Part 1 – Code Review & Debugging

### Issues Found in Original Code

| # | Issue | Impact | Fix |
|---|-------|--------|-----|
| 1 | **Split commits** (two `db.session.commit()`) | Race condition — product created but inventory missing if crash occurs between commits | Use `flush()` + single `commit()` in one transaction |
| 2 | **No input validation** | `KeyError` crash if any field is missing | Validate all required fields, return `400` |
| 3 | **No SKU uniqueness check** at app layer | Duplicate SKUs silently inserted | Catch `IntegrityError`, return `409 Conflict` |
| 4 | **`warehouse_id` on Product model** | Products can exist in multiple warehouses — wrong design | Remove from Product; relationship lives in Inventory |
| 5 | **No price/quantity validation** | Negative or non-numeric values stored in DB | Cast and validate both fields |
| 6 | **No authentication/authorization** | Anyone can create products | Add auth decorator |
| 7 | **Returns 200 instead of 201** | Violates REST conventions | Return `201 Created` |
| 8 | **`request.json` instead of `get_json()`** | Raises exception on wrong Content-Type | Use `request.get_json()` |
| 9 | **No error logging** | Silent failures in production | Add `logging.exception()` |
| 10 | **No rollback on exception** | DB left in inconsistent state | `db.session.rollback()` in except block |

See `part1/fixed_code.py` for the corrected implementation.

---

## Part 2 – Database Design

**Tables designed:**
- `companies` → `warehouses` (one company, many warehouses)
- `products` (SKU unique per company; has `low_stock_threshold` and `product_type`)
- `inventory` (product ↔ warehouse many-to-many with quantity)
- `inventory_transactions` (full audit ledger — every stock change recorded)
- `suppliers` + `product_suppliers` (many-to-many with unit cost & primary flag)
- `bundle_components` (self-referential for bundle SKUs)
- `orders` + `order_items` (for sales velocity calculation)

**Key decisions:**
- `NUMERIC(12,2)` for price — avoids floating point errors
- `CHECK (quantity >= 0)` — prevents negative stock at DB level
- Audit ledger (delta-based) instead of just storing current count
- All timestamps as `TIMESTAMPTZ` (UTC)

**Questions I'd ask the product team:**
1. Is SKU unique globally or per-company?
2. Multi-currency support needed?
3. Can bundles contain other bundles?
4. What defines "recent sales activity" — last N days?
5. Are there purchase orders / inbound shipments to track?

See `part2/schema.sql` for full DDL.

---

## Part 3 – Low-Stock Alert API

**Endpoint:** `GET /api/companies/{company_id}/alerts/low-stock`

**Assumptions made:**
- "Recent sales activity" = at least 1 sale in last 30 days
- `days_until_stockout` = `current_stock ÷ avg_daily_sales` (null if no velocity)
- Low-stock threshold stored on `products.low_stock_threshold`
- Primary supplier returned (via `product_suppliers.is_primary = TRUE`)
- Cancelled orders excluded from velocity calculation

**Edge cases handled:**
- Company not found → `404`
- No alerts → `{alerts: [], total_alerts: 0}` (never 404)
- No supplier → `supplier: null`
- Zero sales velocity → `days_until_stockout: null` (no division by zero)
- DB error → logged + generic `500` (no stack trace leaked)

See `part3/low_stock_alerts.py` for full implementation.

---

## Assumptions & Notes
- Database: PostgreSQL
- Framework: Python / Flask / SQLAlchemy
- Auth/authorization assumed to exist (out of scope for this case study)
- All code is production-oriented: validated, logged, transactional

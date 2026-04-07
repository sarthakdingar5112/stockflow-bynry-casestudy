from flask import jsonify
from sqlalchemy import text
from datetime import datetime, timedelta
import logging

# ──────────────────────────────────────────────────────────────
# Assumptions:
#   1. "Recent sales activity" = at least 1 unit sold in last 30 days
#   2. days_until_stockout = current_stock / avg_daily_sales (None if no data)
#   3. Low-stock threshold is stored on products.low_stock_threshold
#   4. Primary supplier returned via product_suppliers.is_primary = TRUE
#   5. Cancelled orders excluded from sales velocity calculation
#   6. Alerts ordered by urgency (lowest stock/threshold ratio first)
# ──────────────────────────────────────────────────────────────

RECENT_DAYS = 30  # Definition of "recent sales activity"


@app.route('/api/companies/<int:company_id>/alerts/low-stock', methods=['GET'])
def low_stock_alerts(company_id):
    """
    Returns low-stock alerts for all warehouses belonging to a company.
    Only includes products with at least 1 sale in the last RECENT_DAYS days.

    Response: { "alerts": [...], "total_alerts": N }
    """

    # 1. Validate company exists — return 404 early, no need to run heavy query
    company = Company.query.get(company_id)
    if not company:
        return jsonify({"error": "Company not found"}), 404

    cutoff_date = datetime.utcnow() - timedelta(days=RECENT_DAYS)

    # 2. Single optimised query using a CTE.
    #    Why CTE instead of ORM?
    #    - Combines inventory + sales velocity + supplier in one round-trip
    #    - ORM approach would require N+1 queries or complex eager loading
    #    - CTE is readable, debuggable, and easy to move into a DB view later
    sql = text("""
        WITH recent_sales AS (
            -- Calculate total sold and average daily sales per (product, warehouse)
            -- for the last RECENT_DAYS days. Only products with actual sales are included.
            SELECT
                oi.product_id,
                w.id                                AS warehouse_id,
                SUM(oi.quantity)                    AS total_sold,
                SUM(oi.quantity) * 1.0 / :days      AS avg_daily
            FROM order_items oi
            JOIN orders o       ON o.id = oi.order_id
            JOIN warehouses w   ON w.company_id = :company_id
            WHERE o.created_at >= :cutoff
              AND o.status != 'cancelled'     -- Exclude cancelled orders from velocity
            GROUP BY oi.product_id, w.id
            HAVING SUM(oi.quantity) > 0       -- Must have at least 1 sale (recent activity check)
        )
        SELECT
            p.id                        AS product_id,
            p.name                      AS product_name,
            p.sku,
            p.low_stock_threshold       AS threshold,
            w.id                        AS warehouse_id,
            w.name                      AS warehouse_name,
            inv.quantity                AS current_stock,
            rs.avg_daily,
            s.id                        AS supplier_id,
            s.name                      AS supplier_name,
            s.contact_email
        FROM inventory inv
        JOIN products p         ON p.id = inv.product_id
        JOIN warehouses w       ON w.id = inv.warehouse_id
        -- INNER JOIN with recent_sales filters to only products with recent activity
        JOIN recent_sales rs    ON rs.product_id = p.id
                                AND rs.warehouse_id = w.id
        -- LEFT JOIN supplier — product may have no supplier (returns null)
        LEFT JOIN product_suppliers ps  ON ps.product_id = p.id
                                       AND ps.is_primary = TRUE
        LEFT JOIN suppliers s           ON s.id = ps.supplier_id
        WHERE w.company_id = :company_id
          AND p.is_active = TRUE
          AND inv.quantity < p.low_stock_threshold   -- Only low-stock items
        -- Most urgent first: lowest (current_stock / threshold) ratio
        ORDER BY (inv.quantity * 1.0 / NULLIF(p.low_stock_threshold, 0)) ASC
    """)

    try:
        rows = db.session.execute(sql, {
            "company_id": company_id,
            "cutoff": cutoff_date,
            "days": RECENT_DAYS
        }).fetchall()

    except Exception:
        logging.exception("DB error while fetching low-stock alerts for company %s", company_id)
        # Return generic error — never leak stack traces to clients
        return jsonify({"error": "Internal server error"}), 500

    # 3. Build response
    alerts = []
    for row in rows:
        avg_daily = float(row.avg_daily) if row.avg_daily else 0

        # Avoid division by zero — return None if no sales velocity data
        if avg_daily > 0:
            days_until_stockout = int(row.current_stock / avg_daily)
        else:
            days_until_stockout = None

        alerts.append({
            "product_id":           row.product_id,
            "product_name":         row.product_name,
            "sku":                  row.sku,
            "warehouse_id":         row.warehouse_id,
            "warehouse_name":       row.warehouse_name,
            "current_stock":        row.current_stock,
            "threshold":            row.threshold,
            "days_until_stockout":  days_until_stockout,
            # supplier is None if no supplier linked (LEFT JOIN returned null)
            "supplier": {
                "id":            row.supplier_id,
                "name":          row.supplier_name,
                "contact_email": row.contact_email,
            } if row.supplier_id else None
        })

    # Always return 200 with empty list — never 404 for "no alerts"
    return jsonify({
        "alerts":       alerts,
        "total_alerts": len(alerts)
    }), 200


# ──────────────────────────────────────────────────────────────
# Edge Cases Handled:
#   - Company not found              → 404 (early return)
#   - No low-stock products          → { alerts: [], total_alerts: 0 }
#   - Product has no supplier        → supplier: null (LEFT JOIN)
#   - Zero sales velocity            → days_until_stockout: null (no div by zero)
#   - DB error                       → logged + generic 500 (no stack trace leak)
#   - Company with no warehouses     → empty result naturally
#   - Product in multiple warehouses → separate alert row per warehouse
#   - Cancelled orders               → excluded from velocity (o.status != 'cancelled')
#   - Inactive products              → excluded (p.is_active = TRUE)
#
# Production Improvements (out of scope):
#   - Redis cache (5-min TTL keyed by company_id) for high-traffic companies
#   - Cursor-based pagination for companies with 100s of low-stock items
#   - Move CTE into a PostgreSQL view for reuse across endpoints
#   - Celery scheduled task to pre-compute alerts (trades real-time for speed)
# ──────────────────────────────────────────────────────────────

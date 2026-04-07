-- =============================================================
-- StockFlow – Database Schema (PostgreSQL)
-- Sarthak Dingar – Bynry Backend Engineering Intern Case Study
-- =============================================================


-- ── COMPANIES ────────────────────────────────────────────────
CREATE TABLE companies (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);


-- ── WAREHOUSES ───────────────────────────────────────────────
-- A company can have many warehouses.
CREATE TABLE warehouses (
    id          SERIAL PRIMARY KEY,
    company_id  INT          NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    address     TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_warehouses_company ON warehouses(company_id);


-- ── PRODUCTS ─────────────────────────────────────────────────
-- SKU is unique per company (B2B: different companies may reuse SKUs).
-- product_type drives the default low_stock_threshold at application layer.
-- low_stock_threshold stored directly on product to allow per-SKU overrides.
CREATE TABLE products (
    id                   SERIAL PRIMARY KEY,
    company_id           INT          NOT NULL REFERENCES companies(id),
    name                 VARCHAR(255) NOT NULL,
    sku                  VARCHAR(100) NOT NULL,
    -- NUMERIC(12,2) avoids floating-point rounding errors (never use FLOAT for money)
    price                NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (price >= 0),
    product_type         VARCHAR(50)  NOT NULL DEFAULT 'standard',
    -- 'standard' | 'bundle' | 'perishable' | 'high_value'
    low_stock_threshold  INT          NOT NULL DEFAULT 10 CHECK (low_stock_threshold >= 0),
    is_active            BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    -- SKU must be unique within a company
    UNIQUE (company_id, sku)
);
CREATE INDEX idx_products_company ON products(company_id);
CREATE INDEX idx_products_sku     ON products(sku);


-- ── INVENTORY ────────────────────────────────────────────────
-- Tracks current stock level of a product at a specific warehouse.
-- A product can be in many warehouses (many-to-many via this table).
CREATE TABLE inventory (
    id            SERIAL PRIMARY KEY,
    product_id    INT NOT NULL REFERENCES products(id),
    warehouse_id  INT NOT NULL REFERENCES warehouses(id),
    -- CHECK constraint prevents negative stock at DB level (safety net)
    quantity      INT NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, warehouse_id)
);
CREATE INDEX idx_inventory_product   ON inventory(product_id);
CREATE INDEX idx_inventory_warehouse ON inventory(warehouse_id);


-- ── INVENTORY TRANSACTIONS (Audit Ledger) ────────────────────
-- Every stock change is recorded as a delta (positive = in, negative = out).
-- This gives a full audit trail and enables point-in-time reconstruction.
-- Required for compliance in most B2B contexts.
CREATE TABLE inventory_transactions (
    id              SERIAL PRIMARY KEY,
    inventory_id    INT         NOT NULL REFERENCES inventory(id),
    delta           INT         NOT NULL,   -- +ve = stock received, -ve = sold/adjusted
    reason          VARCHAR(100),           -- 'sale' | 'purchase' | 'adjustment' | 'return'
    reference_id    INT,                    -- FK to orders or purchases (polymorphic)
    reference_type  VARCHAR(50),            -- 'order' | 'purchase_order'
    created_by      INT,                    -- FK to users table (add when users table exists)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_inv_tx_inventory   ON inventory_transactions(inventory_id);
-- Index on created_at is critical for sales velocity queries (last 30 days)
CREATE INDEX idx_inv_tx_created_at  ON inventory_transactions(created_at);


-- ── SUPPLIERS ────────────────────────────────────────────────
CREATE TABLE suppliers (
    id             SERIAL PRIMARY KEY,
    company_id     INT          NOT NULL REFERENCES companies(id),
    name           VARCHAR(255) NOT NULL,
    contact_email  VARCHAR(255),
    contact_phone  VARCHAR(50),
    lead_time_days INT,                     -- average days from order to delivery
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_suppliers_company ON suppliers(company_id);


-- ── PRODUCT ↔ SUPPLIER (Many-to-Many) ───────────────────────
-- A product can have multiple suppliers; one is marked as primary for reordering.
CREATE TABLE product_suppliers (
    id           SERIAL PRIMARY KEY,
    product_id   INT           NOT NULL REFERENCES products(id),
    supplier_id  INT           NOT NULL REFERENCES suppliers(id),
    unit_cost    NUMERIC(12,2),             -- cost price from this supplier
    is_primary   BOOLEAN       NOT NULL DEFAULT FALSE,
    UNIQUE (product_id, supplier_id)
);
CREATE INDEX idx_product_suppliers_product  ON product_suppliers(product_id);
CREATE INDEX idx_product_suppliers_supplier ON product_suppliers(supplier_id);


-- ── BUNDLE COMPONENTS (Self-Referential) ─────────────────────
-- Allows products of type 'bundle' to contain other products.
-- CHECK prevents a product from being a component of itself.
CREATE TABLE bundle_components (
    id            SERIAL PRIMARY KEY,
    bundle_id     INT NOT NULL REFERENCES products(id),
    component_id  INT NOT NULL REFERENCES products(id),
    quantity      INT NOT NULL DEFAULT 1 CHECK (quantity > 0),
    UNIQUE (bundle_id, component_id),
    CHECK (bundle_id <> component_id)   -- prevent self-reference
);


-- ── ORDERS ───────────────────────────────────────────────────
-- Referenced by the low-stock alert query for sales velocity.
CREATE TABLE orders (
    id          SERIAL PRIMARY KEY,
    company_id  INT         NOT NULL REFERENCES companies(id),
    status      VARCHAR(50) NOT NULL DEFAULT 'pending',
    -- 'pending' | 'confirmed' | 'shipped' | 'delivered' | 'cancelled'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_orders_company    ON orders(company_id);
-- Index on created_at is critical for "last 30 days" velocity queries
CREATE INDEX idx_orders_created_at ON orders(created_at);

CREATE TABLE order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INT           NOT NULL REFERENCES orders(id),
    product_id  INT           NOT NULL REFERENCES products(id),
    quantity    INT           NOT NULL CHECK (quantity > 0),
    unit_price  NUMERIC(12,2) NOT NULL   -- price at time of order (snapshot)
);
CREATE INDEX idx_order_items_order   ON order_items(order_id);
CREATE INDEX idx_order_items_product ON order_items(product_id);


-- =============================================================
-- QUESTIONS FOR PRODUCT TEAM (Gaps in Requirements)
-- =============================================================
-- 1. Is SKU unique globally or per-company?
--    (Assumed: per-company for B2B — different clients may have same SKU)
-- 2. Multi-currency support needed for price?
-- 3. Can a bundle contain other bundles (nested bundles)?
-- 4. What exactly defines "recent sales activity" — last N days?
-- 5. Are purchase orders / inbound shipments tracked separately?
-- 6. Do we need batch tracking or expiry dates for perishable products?
-- 7. Are there user roles per warehouse (e.g. warehouse manager)?
-- 8. Soft-delete for products (is_active flag) or hard-delete?
-- 9. Can a product belong to multiple companies (marketplace model)?
-- 10. How should inventory be handled when a bundle is sold —
--     deduct from bundle stock or from component stocks?
-- =============================================================

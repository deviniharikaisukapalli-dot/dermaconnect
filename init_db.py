import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).parent / "instance" / "dermaconnect.sqlite3"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS doctors (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    license_number TEXT NOT NULL UNIQUE,
    phone TEXT,
    email TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stores (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    phone TEXT,
    is_partner INTEGER NOT NULL DEFAULT 1 CHECK (is_partner IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    brand TEXT,
    category TEXT,
    description TEXT,
    sku TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory (
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (store_id, product_id)
);

CREATE TABLE IF NOT EXISTS prescriptions (
    id INTEGER PRIMARY KEY,
    qr_token TEXT NOT NULL UNIQUE,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    status TEXT NOT NULL DEFAULT 'issued'
        CHECK (status IN ('issued', 'fulfilled', 'cancelled')),
    refill_interval_days INTEGER NOT NULL DEFAULT 30
        CHECK (refill_interval_days > 0),
    issued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fulfilled_at TEXT
);

CREATE TABLE IF NOT EXISTS prescription_items (
    id INTEGER PRIMARY KEY,
    prescription_id INTEGER NOT NULL REFERENCES prescriptions(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    instructions TEXT NOT NULL,
    UNIQUE (prescription_id, product_id)
);

CREATE TABLE IF NOT EXISTS fulfillments (
    id INTEGER PRIMARY KEY,
    prescription_id INTEGER NOT NULL UNIQUE REFERENCES prescriptions(id),
    store_id INTEGER NOT NULL REFERENCES stores(id),
    fulfilled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reward_points INTEGER NOT NULL DEFAULT 0 CHECK (reward_points >= 0)
);

CREATE TABLE IF NOT EXISTS loyalty_transactions (
    id INTEGER PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    fulfillment_id INTEGER NOT NULL UNIQUE REFERENCES fulfillments(id),
    points INTEGER NOT NULL CHECK (points > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS refill_reminders (
    id INTEGER PRIMARY KEY,
    prescription_id INTEGER NOT NULL REFERENCES prescriptions(id) ON DELETE CASCADE,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'sent', 'cancelled')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (prescription_id, due_at)
);

CREATE INDEX IF NOT EXISTS idx_prescriptions_status
    ON prescriptions(status);
CREATE INDEX IF NOT EXISTS idx_inventory_product_stock
    ON inventory(product_id, stock_quantity);
CREATE INDEX IF NOT EXISTS idx_refill_reminders_due_status
    ON refill_reminders(due_at, status);
"""


def initialize_database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.executescript(SCHEMA)
    finally:
        connection.close()
    return DB_PATH


if __name__ == "__main__":
    print(f"Database initialized at {initialize_database()}")
import sqlite3

# --- Database File Definitions ---
# The main PO data, which can be safely deleted/reset
DB_NAME_PO = "po_data.db"
# The permanent style master data
DB_NAME_MASTER = "style_master.db"


# --- Connection Helper Functions ---

# NOTE: The original function 'get_db_connection' is renamed to match the PO data file
def get_po_db_connection():
    """Connects to the main PO data DB (po_data.db)."""
    conn = sqlite3.connect(DB_NAME_PO)
    conn.row_factory = sqlite3.Row
    return conn
    
def get_master_db_connection():
    """Connects to the permanent Style Master DB (style_master.db)."""
    conn = sqlite3.connect(DB_NAME_MASTER)
    conn.row_factory = sqlite3.Row
    return conn


# --- Initialization Function ---

def initialize_db():
    # 1. Initialize STYLE MASTER DB (Permanent)
    conn_m = get_master_db_connection()
    cur_m = conn_m.cursor()
    cur_m.execute("""
        CREATE TABLE IF NOT EXISTS style_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ean      TEXT UNIQUE,
            style_no TEXT,
            buyer    TEXT
        )
    """)
    conn_m.commit()
    conn_m.close()

    # 2. Initialize PO DATA DB (Resettable)
    conn_p = get_po_db_connection()
    cur_p = conn_p.cursor()

    # FIX: Changed 'cur.execute' to 'cur_p.execute'
    cur_p.execute("""
        CREATE TABLE IF NOT EXISTS po_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            filename         TEXT,
            po_number        TEXT,
            po_date          TEXT,
            style_no         TEXT,
            ocn              TEXT,
            buyer            TEXT,

            delivery_date    TEXT,
            delivery_month   TEXT,
            location         TEXT,
            ean              TEXT,
            description      TEXT,
            caselot          INTEGER,
            quantity         INTEGER,
            no_of_boxes      INTEGER,

            factory          TEXT,
            ex_factory_date  TEXT,
            factory_remarks  TEXT,

            dispatched_box   INTEGER,
            dispatched_qty   INTEGER,
            balance          INTEGER,
            status           TEXT,
            dispatch_date    TEXT,
            transporter      TEXT,
            grn_date         TEXT,
            grn_status       TEXT,

            is_revised       INTEGER DEFAULT 0,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn_p.commit()
    conn_p.close()
    print("Databases initialized.")


# --- Run on Execution ---

if __name__ == "__main__":
    initialize_db()
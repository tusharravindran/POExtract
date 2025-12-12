from flask import Flask, render_template, request, jsonify, redirect, Response
import os
import fitz
import pandas as pd
import io
from datetime import datetime, timedelta

from extractor import extract_items
from database import get_po_db_connection, initialize_db

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Make sure DB + tables exist
initialize_db()

# ----------------- CONSTANTS / MASTER LISTS ----------------- #

FACTORIES = ["Unit 1", "Unit 2", "Unit 3", "Unit 4", "Unit 5"]

TRANSPORTERS = ["Balaji RD Lines", "JJ LOG", "Rectus", "Others"]

BUYERS = [
    "ASL-Mens AW Fashion",
    "ASL-Wmns AW Core",
    "ASL-Wmns AW Fashion",
    "ASL-Wmns SW Core",
    "ASL-Wmns SW Fashion",
    "ASL-Wmns WW Core",
    "ASL-Wmns WW Fashion",
    "ASL-Boys AW Core",
    "ASL-Boys AW Fashion",
    "ASL-Girls Core",
    "ASL-Girls Fashion",
]

# ----------------- HELPER FUNCTIONS ----------------- #


def get_style_and_buyer_from_db(ean: str):
    """
    Returns (style_no, buyer) from style_master for a given EAN.
    If not found, returns ("", "").
    """
    conn = get_po_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT style_no, buyer FROM style_master WHERE ean=?", (ean,))
    row = cur.fetchone()
    conn.close()

    if row:
        return (row["style_no"] or "", row["buyer"] or "")
    return "", ""


def calc_delivery_minus_4(date_str: str) -> str:
    """Delivery date = extracted date - 4 days (always)."""
    try:
        d = datetime.strptime(date_str, "%d.%m.%Y")
        d -= timedelta(days=4)
        return d.strftime("%d.%m.%Y")
    except Exception:
        return date_str  # fallback


def calc_delivery_month(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%d.%m.%Y")
        return d.strftime("%B")
    except Exception:
        return ""


def calc_no_of_boxes(caselot, qty) -> int:
    try:
        c = int(caselot)
        q = int(qty)
        return q // c if c > 0 else 0
    except Exception:
        return 0


def calc_ex_factory(location: str, delv_date_str: str) -> str:
    """
    Ex-Factory Date = (Delivery Date AFTER -4 days) minus location-based days:
      Vadodara -> -6 days
      Bhiwandi -> -4 days
      Mandal / Isnapur / Medak / Manoharabad  -> -3 days
      Others -> same as delivery date
    """
    try:
        d = datetime.strptime(delv_date_str, "%d.%m.%Y")
    except Exception:
        return ""

    loc = (location or "").lower()
    days = 0
    if "vadodara" in loc:
        days = 6
    elif "bhiwandi" in loc:
        days = 4
    elif "mandal" in loc or "isnapur" in loc or "medak" in loc or "manoharabad" in loc:
        days = 3

    d -= timedelta(days=days)
    return d.strftime("%d.%m.%Y")


def calculate_exfactory_flag(date_str):
    """Returns: 'overdue' / 'due' / '' based on ex-factory date."""
    if not date_str:
        return ""
    try:
        d = datetime.strptime(date_str, "%d.%m.%Y").date()
        today = datetime.today().date()

        if today >= d:
            return "overdue"       # red
        days_left = (d - today).days
        if days_left <= 3:
            return "due"           # yellow
        return ""
    except Exception:
        return ""


def upsert_po_item(cur, row):
    """
    Avoid duplicates in po_items:
    - Key = (po_number, ean)
    - If not exists -> INSERT
    - If exists and values changed -> UPDATE + is_revised=1
    - If exists and same -> do nothing
    """
    cur.execute("SELECT * FROM po_items WHERE po_number=? AND ean=?",
                (row["po_number"], row["ean"]))
    existing = cur.fetchone()

    if existing is None:
        # Insert new
        cur.execute(
            """
            INSERT INTO po_items
            (filename, po_number, po_date, style_no, ocn, buyer,
             delivery_date, delivery_month, location,
             ean, description, caselot, quantity,
             no_of_boxes, factory, ex_factory_date, factory_remarks,
             dispatched_box, dispatched_qty, balance, status,
             dispatch_date, transporter, grn_date, grn_status,
             is_revised)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["filename"],
                row["po_number"],
                row["po_date"],
                row["style_no"],
                row["ocn"],
                row["buyer"],
                row["delivery_date"],
                row["delivery_month"],
                row["location"],
                row["ean"],
                row["description"],
                row["caselot"],
                row["quantity"],
                row["no_of_boxes"],
                row["factory"],
                row["ex_factory_date"],
                row["factory_remarks"],
                row["dispatched_box"],
                row["dispatched_qty"],
                row["balance"],
                row["status"],
                row["dispatch_date"],
                row["transporter"],
                row["grn_date"],
                row["grn_status"],
                0,  # new row, not revised
            ),
        )
    else:
        # Compare core business fields only
        changed = False

        fields_to_check = [
            "style_no",
            "delivery_date",
            "delivery_month",
            "location",
            "description",
            "caselot",
            "quantity",
            "no_of_boxes",
            "ex_factory_date",
        ]

        for f in fields_to_check:
            if row[f] != existing[f]:
                changed = True
                break

        if not changed:
            # exact duplicate, ignore
            return

        # When revised -> update business fields, keep dispatch/factory/buyer/status etc as they are
        new_qty = row["quantity"]
        old_dispatched = existing["dispatched_qty"] or 0
        new_balance = new_qty - old_dispatched

        cur.execute(
            """
            UPDATE po_items
               SET style_no=?,
                   delivery_date=?,
                   delivery_month=?,
                   location=?,
                   description=?,
                   caselot=?,
                   quantity=?,
                   no_of_boxes=?,
                   ex_factory_date=?,
                   balance=?,
                   is_revised=1
             WHERE id=?
            """,
            (
                row["style_no"],
                row["delivery_date"],
                row["delivery_month"],
                row["location"],
                row["description"],
                row["caselot"],
                row["quantity"],
                row["no_of_boxes"],
                row["ex_factory_date"],
                new_balance,
                existing["id"],
            ),
        )

# ---------------- STYLE MASTER ROUTES ---------------- #


@app.route("/style-master")
def style_master():
    conn = get_po_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM style_master ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return render_template("style_master.html", styles=rows, buyers=BUYERS)


@app.route("/save_style", methods=["POST"])
def save_style():
    ean = request.form.get("ean", "").strip()
    style = request.form.get("style_no", "").strip()
    buyer = request.form.get("buyer", "").strip()

    if not ean:
        return redirect("/style-master")

    conn = get_po_db_connection()
    cur = conn.cursor()

    # If same EAN exists, update it; else insert new
    cur.execute("SELECT id FROM style_master WHERE ean=?", (ean,))
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE style_master SET style_no=?, buyer=? WHERE ean=?",
            (style, buyer, ean),
        )
    else:
        cur.execute(
            "INSERT INTO style_master (ean, style_no, buyer) VALUES (?, ?, ?)",
            (ean, style, buyer),
        )

    conn.commit()
    conn.close()
    return redirect("/style-master")


@app.route("/delete_style/<int:id>")
def delete_style(id):
    conn = get_po_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM style_master WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect("/style-master")

@app.route("/refresh_styles")
def refresh_styles():
    conn = get_po_db_connection()
    cur = conn.cursor()

    # Get all PO rows
    cur.execute("SELECT id, ean FROM po_items")
    rows = cur.fetchall()

    for r in rows:
        style_no, buyer = get_style_and_buyer_from_db(r["ean"])
        cur.execute("""
            UPDATE po_items
            SET style_no=?, buyer=?
            WHERE id=?
        """, (style_no, buyer, r["id"]))

    conn.commit()
    conn.close()

    return redirect("/dashboard")



# ---------------- MAIN ROUTES ---------------- #


@app.route("/")
def home():
    return render_template("upload.html")


@app.route("/upload", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        files = request.files.getlist("pdf_files")
        extracted_data = []

        conn = get_po_db_connection()
        cur = conn.cursor()

        for pdf in files:
            if not pdf.filename:
                continue

            filepath = os.path.join(UPLOAD_FOLDER, pdf.filename)
            pdf.save(filepath)

            with fitz.open(filepath) as doc:
                text = "".join(page.get_text("text") for page in doc)

            rows = extract_items(text, pdf.filename)
            extracted_data.extend(rows)

            for r in rows:
                # Extracted from PDF via extractor
                original_delv = r["Delivery Date"]
                po_no = r["PO #"]
                po_date = r["PO Date"]
                loc = r["Location"]
                ean = r["EAN NO"]
                desc = r["Article Description"]
                caselot_raw = r["CaseLot"]
                qty_raw = r["Quantity"]
                fname = r["Filename"]

                # Delivery date -4 days (as per your logic)
                delv_adjusted = calc_delivery_minus_4(original_delv)

                # Convert int
                try:
                    caselot_int = int(caselot_raw)
                except Exception:
                    caselot_int = 0

                try:
                    qty_int = int(qty_raw)
                except Exception:
                    qty_int = 0

                # Derived fields
                style_no, buyer = get_style_and_buyer_from_db(ean)
                delv_month = calc_delivery_month(delv_adjusted)
                no_boxes = calc_no_of_boxes(caselot_int, qty_int)
                ex_fty = calc_ex_factory(loc, delv_adjusted)
                balance = qty_int

                row = {
                    "filename": fname,
                    "po_number": po_no,
                    "po_date": po_date,
                    "style_no": style_no,
                    "ocn": "",          # you can fill later in dashboard
                    "buyer": buyer,
                    "delivery_date": delv_adjusted,
                    "delivery_month": delv_month,
                    "location": loc,
                    "ean": ean,
                    "description": desc,
                    "caselot": caselot_int,
                    "quantity": qty_int,
                    "no_of_boxes": no_boxes,
                    "factory": "",
                    "ex_factory_date": ex_fty,
                    "factory_remarks": "",
                    "dispatched_box": 0,
                    "dispatched_qty": 0,
                    "balance": balance,
                    "status": "Pending",
                    "dispatch_date": "",
                    "transporter": "",
                    "grn_date": "",
                    "grn_status": "",
                }

                upsert_po_item(cur, row)

        conn.commit()
        conn.close()

        return render_template("results.html", data=extracted_data)

    return render_template("upload.html")


@app.route("/dashboard")
def dashboard():
    conn = get_po_db_connection() 
    cur = conn.cursor()
    
    # FIX for Issue 2: Ensure sorting by date, pushing empty/invalid dates to the bottom.
    cur.execute("""
        SELECT * FROM po_items 
        ORDER BY 
            -- 1. Sort by Status Priority (0=Pending, 1=Cancelled, 2=Dispatched)
            CASE 
                WHEN status = 'Dispatched' THEN 2
                WHEN status = 'Cancelled' THEN 1
                ELSE 0 
            END,
            
            -- 2. Push null/empty dates to the bottom of their group
            CASE 
                WHEN ex_factory_date IS NULL OR ex_factory_date = '' THEN 1
                ELSE 0 
            END,
            
            -- 3. CRITICAL FIX: Sort the DD.MM.YYYY date chronologically (YYYY-MM-DD)
            SUBSTR(ex_factory_date, 7, 4) || SUBSTR(ex_factory_date, 4, 2) || SUBSTR(ex_factory_date, 1, 2) ASC,  
            
            id DESC
    """)
    rows = cur.fetchall()
    conn.close()

    processed = []

    for r in rows:
        d = dict(r)

        d["remarks"] = d.get("factory_remarks", "")

        # FIX for Issue 3 (Part 2: Server-side check for row highlight)
        if d.get("status") == "Dispatched":
            d["ex_factory_flag"] = ""  
        else:
            d["ex_factory_flag"] = calculate_exfactory_flag(d.get("ex_factory_date", ""))

        processed.append(d)

    return render_template(
        "dashboard.html",
        data=processed,
        factories=FACTORIES,
        transporters=TRANSPORTERS,
    )

# ---------------- EXCEL DOWNLOAD ROUTE ---------------- #

@app.route("/download_excel")
def download_excel():
    conn = get_po_db_connection()
    
    # 1. Fetch data into a pandas DataFrame
    # Fetch all data from po_items table
    df = pd.read_sql_query("SELECT * FROM po_items", conn)
    
    conn.close()
    
    # 2. Prepare the Excel file in memory
    output = io.BytesIO()
    # Use io.BytesIO for in-memory file handling
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    
    # Write the dataframe to the Excel file
    # We exclude the 'id', 'is_revised', and 'created_at' columns for a cleaner report
    cols_to_exclude = ['id', 'is_revised', 'created_at', 'factory_remarks']
    cols_to_use = [col for col in df.columns if col not in cols_to_exclude]
    
    df[cols_to_use].to_excel(writer, index=False, sheet_name='PO Dashboard Data')
    writer.close()
    output.seek(0)
    
    # 3. Send the file to the user
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"PO_Dashboard_Export_{date_str}.xlsx"
    
    return Response(
        output.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )




# ----------- AJAX UPDATE ROUTE (INLINE EDITS) ----------- #

@app.route("/update_field", methods=["POST"])
def update_field():
    data = request.get_json()
    row_id = data.get("row_id")
    field = data.get("field")
    value = (data.get("value") or "").strip()

    allowed = {
        "ocn",
        "factory",
        "remarks",
        "dispatched_box",
        "status",
        "dispatch_date",
        "transporter",
        "grn_date",
        "grn_status",
    }

    if field not in allowed:
        return jsonify({"ok": False})

    conn = get_po_db_connection()
    cur = conn.cursor()

    db_field = "factory_remarks" if field == "remarks" else field

    # ---------- 1️⃣ DISPATCHED BOX → AUTO CALCULATE QTY + BALANCE ----------
    # FIX for Issue 5: Calculation and JSON response verified.
    if field == "dispatched_box":
        try:
            dbox = int(value)
        except Exception:
            dbox = 0

        cur.execute("SELECT caselot, quantity FROM po_items WHERE id=?", (row_id,))
        row = cur.fetchone()
        
        if not row:
            conn.close()
            return jsonify({"ok": False, "error": "Row not found"})

        caselot = row["caselot"] or 0
        qty = row["quantity"] or 0

        dispatched_qty = dbox * caselot
        balance = qty - dispatched_qty

        cur.execute(
            """
            UPDATE po_items
            SET dispatched_box = ?, dispatched_qty = ?, balance = ?
            WHERE id = ?
            """,
            (dbox, dispatched_qty, balance, row_id),
        )

        conn.commit()
        conn.close()
        # Ensure the response contains the new calculated values
        return jsonify({"ok": True, "dispatched_qty": dispatched_qty, "balance": balance})

    # ---------- 2️⃣ GRN DATE → AUTO SET GRN STATUS ----------
    # FIX for Issue 6: GRN Status update and JSON response verified.
    if field == "grn_date":
        new_status = "Cleared" if value else "Pending"
        
        cur.execute(
            """
            UPDATE po_items SET grn_date=?, grn_status=? WHERE id=?
            """, 
            (value, new_status, row_id)
        )

        conn.commit()
        conn.close()
        # Ensure the response contains the new status
        return jsonify({"ok": True, "new_grn_status": new_status})

    # ---------- 3️⃣ NORMAL FIELD UPDATE ----------
    # This also handles status, dispatch_date, transporter, factory etc.
    cur.execute(f"UPDATE po_items SET {db_field}=? WHERE id=?", (value, row_id))
    conn.commit()
    conn.close()

    return jsonify({"ok": True})

# ---------------- ENTRY POINT ---------------- #

if __name__ == "__main__":
    app.run(debug=True)

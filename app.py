from flask import Flask, render_template, request, jsonify, redirect, Response
import os
import fitz
import pandas as pd
import io
from datetime import datetime, timedelta
from sqlalchemy import case, func, or_

from extractor import extract_items
from database import (
    get_po_db_connection, 
    initialize_db, 
    get_db_session,
    POItem, 
    StyleMaster
)

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


def upsert_po_item(session, row):
    """
    Avoid duplicates in po_items using SQLAlchemy:
    - Key = (po_number, ean)
    - If not exists -> INSERT
    - If exists and values changed -> UPDATE + is_revised=1
    - If exists and same -> do nothing
    """
    existing = session.query(POItem).filter_by(
        po_number=row["po_number"],
        ean=row["ean"]
    ).first()

    if existing is None:
        # Insert new
        po_item = POItem(
            filename=row["filename"],
            po_number=row["po_number"],
            po_date=row["po_date"],
            style_no=row["style_no"],
            ocn=row["ocn"],
            buyer=row["buyer"],
            delivery_date=row["delivery_date"],
            delivery_month=row["delivery_month"],
            location=row["location"],
            ean=row["ean"],
            description=row["description"],
            caselot=row["caselot"],
            quantity=row["quantity"],
            no_of_boxes=row["no_of_boxes"],
            factory=row["factory"],
            ex_factory_date=row["ex_factory_date"],
            factory_remarks=row["factory_remarks"],
            dispatched_box=row["dispatched_box"],
            dispatched_qty=row["dispatched_qty"],
            balance=row["balance"],
            status=row["status"],
            dispatch_date=row["dispatch_date"],
            transporter=row["transporter"],
            grn_date=row["grn_date"],
            grn_status=row["grn_status"],
            is_revised=False
        )
        session.add(po_item)
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
            if row[f] != getattr(existing, f, None):
                changed = True
                break

        if not changed:
            # exact duplicate, ignore
            return

        # When revised -> update business fields, keep dispatch/factory/buyer/status etc as they are
        new_qty = row["quantity"]
        old_dispatched = existing.dispatched_qty or 0
        new_balance = new_qty - old_dispatched

        existing.style_no = row["style_no"]
        existing.delivery_date = row["delivery_date"]
        existing.delivery_month = row["delivery_month"]
        existing.location = row["location"]
        existing.description = row["description"]
        existing.caselot = row["caselot"]
        existing.quantity = row["quantity"]
        existing.no_of_boxes = row["no_of_boxes"]
        existing.ex_factory_date = row["ex_factory_date"]
        existing.balance = new_balance
        existing.is_revised = True

# ---------------- STYLE MASTER ROUTES ---------------- #


@app.route("/style-master")
def style_master():
    with get_db_session() as session:
        # Query style_master table (id is primary key, ean is unique)
        styles = session.query(StyleMaster).order_by(StyleMaster.id.desc()).all()
        rows = [style.to_dict() for style in styles]
    return render_template("style_master.html", styles=rows, buyers=BUYERS)


@app.route("/save_style", methods=["POST"])
def save_style():
    ean = request.form.get("ean", "").strip()
    style = request.form.get("style_no", "").strip()
    buyer = request.form.get("buyer", "").strip()

    if not ean:
        return redirect("/style-master")

    with get_db_session() as session:
        # If same EAN exists, update it; else insert new
        style_master = session.query(StyleMaster).filter_by(ean=ean).first()
        if style_master:
            style_master.style_no = style
            style_master.buyer = buyer
        else:
            style_master = StyleMaster(ean=ean, style_no=style, buyer=buyer)
            session.add(style_master)
        # commit happens automatically via context manager
    
    return redirect("/style-master")


@app.route("/delete_style/<int:id>")
def delete_style(id):
    """Delete style_master by id"""
    with get_db_session() as session:
        style_master = session.query(StyleMaster).filter_by(id=id).first()
        if style_master:
            session.delete(style_master)
        # commit happens automatically via context manager
    return redirect("/style-master")

@app.route("/refresh_styles")
def refresh_styles():
    """Refresh style_no and buyer in po_items from style_master using JOIN"""
    with get_db_session() as session:
        # Use JOIN to update po_items with style_master data
        # This is more efficient than individual lookups
        po_items = session.query(POItem).all()
        for po_item in po_items:
            if po_item.ean:
                # Get style_master via relationship or direct query
                style_master = session.query(StyleMaster).filter_by(ean=po_item.ean).first()
                if style_master:
                    po_item.style_no = style_master.style_no or ""
                    po_item.buyer = style_master.buyer or ""
        # commit happens automatically via context manager
    
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

        with get_db_session() as session:
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

                    # Derived fields - Get from style_master using JOIN (via get_style_and_buyer_from_db)
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

                    upsert_po_item(session, row)
            # commit happens automatically via context manager

        return render_template("results.html", data=extracted_data)

    return render_template("upload.html")


@app.route("/dashboard")
def dashboard():
    """Dashboard with JOIN query: SELECT * FROM po_items JOIN style_master ON po_items.ean = style_master.ean"""
    with get_db_session() as session:
        # Use JOIN to get po_items with style_master data
        # This is the proper way: SELECT * FROM po_items JOIN style_master ON po_items.ean = style_master.ean
        query = session.query(POItem, StyleMaster).outerjoin(
            StyleMaster, POItem.ean == StyleMaster.ean
        )
        
        # Sort by status priority, then ex_factory_date
        status_order = case(
            (POItem.status == 'Dispatched', 2),
            (POItem.status == 'Cancelled', 1),
            else_=0
        )
        
        # Handle date sorting (DD.MM.YYYY format)
        # For PostgreSQL, we can use TO_DATE; for SQLite, use string manipulation
        query = query.order_by(
            status_order,
            case(
                (or_(POItem.ex_factory_date == None, POItem.ex_factory_date == ''), 1),
                else_=0
            ),
            POItem.ex_factory_date.asc(),
            POItem.id.desc()
        )
        
        results = query.all()
        
        processed = []
        for po_item, style_master in results:
            d = po_item.to_dict()
            
            # Override with style_master data if available (from JOIN)
            if style_master:
                d['style_no'] = style_master.style_no or d.get('style_no', '')
                d['buyer'] = style_master.buyer or d.get('buyer', '')
            
            d["remarks"] = d.get("factory_remarks", "")

            # Server-side check for row highlight
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
    """Download Excel with JOIN: SELECT * FROM po_items JOIN style_master ON po_items.ean = style_master.ean"""
    with get_db_session() as session:
        # Use JOIN query to get po_items with style_master data
        query = session.query(POItem, StyleMaster).outerjoin(
            StyleMaster, POItem.ean == StyleMaster.ean
        )
        
        # Convert to list of dictionaries
        data = []
        for po_item, style_master in query.all():
            row = po_item.to_dict()
            if style_master:
                row['style_no'] = style_master.style_no or row.get('style_no', '')
                row['buyer'] = style_master.buyer or row.get('buyer', '')
            data.append(row)
        
        df = pd.DataFrame(data)
    
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

    with get_db_session() as session:
        po_item = session.query(POItem).filter_by(id=row_id).first()
        
        if not po_item:
            return jsonify({"ok": False, "error": "Row not found"})

        # ---------- 1️⃣ DISPATCHED BOX → AUTO CALCULATE QTY + BALANCE ----------
        if field == "dispatched_box":
            try:
                dbox = int(value)
            except Exception:
                dbox = 0

            caselot = po_item.caselot or 0
            qty = po_item.quantity or 0

            dispatched_qty = dbox * caselot
            balance = qty - dispatched_qty

            po_item.dispatched_box = dbox
            po_item.dispatched_qty = dispatched_qty
            po_item.balance = balance
            
            # commit happens automatically via context manager
            return jsonify({"ok": True, "dispatched_qty": dispatched_qty, "balance": balance})

        # ---------- 2️⃣ GRN DATE → AUTO SET GRN STATUS ----------
        if field == "grn_date":
            new_status = "Cleared" if value else "Pending"
            po_item.grn_date = value
            po_item.grn_status = new_status
            
            # commit happens automatically via context manager
            return jsonify({"ok": True, "new_grn_status": new_status})

        # ---------- 3️⃣ NORMAL FIELD UPDATE ----------
        # Map field names
        if field == "remarks":
            po_item.factory_remarks = value
        else:
            setattr(po_item, field, value)
        
        # commit happens automatically via context manager

    return jsonify({"ok": True})

# ---------------- ENTRY POINT ---------------- #

if __name__ == "__main__":
    # Production: Use environment PORT, default to 5001 (5000 is often used by AirPlay on macOS)
    # Development: Can still use debug mode
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)

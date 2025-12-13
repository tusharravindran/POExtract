"""
PO Routes - Upload and manage Purchase Orders
"""
from flask import Blueprint, render_template, request, jsonify, redirect, Response
import os
import fitz
import pandas as pd
import io
from datetime import datetime
from database import get_db_session
from models.po_item import POItem
from models.style_master import StyleMaster
from auth.decorators import login_required
from extractor import extract_items
from utils.helpers import (
    calc_delivery_minus_4,
    calc_delivery_month,
    calc_no_of_boxes,
    calc_ex_factory
)

po_bp = Blueprint('po', __name__)

UPLOAD_FOLDER = "uploads"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


def get_style_and_buyer_from_db(ean: str):
    """
    Returns (style_no, buyer) from style_master for a given EAN.
    If not found, returns ("", "").
    """
    with get_db_session() as session:
        style_master = session.query(StyleMaster).filter_by(ean=ean).first()
        if style_master:
            return (style_master.style_no or "", style_master.buyer or "")
    return "", ""


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
        ean=row.get("ean", "")
    ).first()
    
    if not existing:
        # New record
        po_item = POItem(**row)
        session.add(po_item)
    else:
        # Check if values changed
        changed = False
        if existing.quantity != row.get("quantity", 0):
            changed = True
            existing.quantity = row["quantity"]
        if existing.delivery_date != row.get("delivery_date", ""):
            changed = True
            existing.delivery_date = row["delivery_date"]
        if existing.ex_factory_date != row.get("ex_factory_date", ""):
            changed = True
            existing.ex_factory_date = row["ex_factory_date"]
        
        if changed:
            new_balance = row.get("quantity", 0) - existing.dispatched_qty
            existing.balance = new_balance
            existing.is_revised = True


@po_bp.route("/")
@login_required
def home():
    """Home page - redirects to upload"""
    return render_template("upload.html")


@po_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload_file():
    """Upload PDF files for processing"""
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

                    # Derived fields - Get from style_master
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
                        "ocn": "",
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


@po_bp.route("/download_excel")
@login_required
def download_excel():
    """Download dashboard data as Excel file"""
    from database import engine
    
    query = """
    SELECT 
        po_number, po_date, style_no, ocn, buyer, description,
        delivery_date, delivery_month, location, ean,
        caselot, quantity, no_of_boxes, factory, ex_factory_date,
        factory_remarks, dispatched_box, dispatched_qty, balance,
        status, dispatch_date, transporter, grn_date, grn_status,
        is_revised, created_at
    FROM po_items
    ORDER BY id DESC
    """
    
    df = pd.read_sql(query, engine)
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"PO_Dashboard_Export_{date_str}.xlsx"
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='PO Items')
    
    output.seek(0)
    return Response(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@po_bp.route("/update_field", methods=["POST"])
@login_required
def update_field():
    """Update a field in po_items"""
    data = request.get_json()
    po_id = data.get("id")
    field = data.get("field")
    value = data.get("value")
    
    if not po_id or not field:
        return jsonify({"error": "Missing id or field"}), 400
    
    with get_db_session() as session:
        po_item = session.query(POItem).filter_by(id=po_id).first()
        if not po_item:
            return jsonify({"error": "PO item not found"}), 404
        
        # Map field names
        if field == "remarks":
            po_item.factory_remarks = value
        else:
            setattr(po_item, field, value)
        
        # commit happens automatically via context manager

    return jsonify({"ok": True})


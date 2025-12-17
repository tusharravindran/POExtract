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
from auth.decorators import login_required, admin_required
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


def ensure_ean_in_style_master(session, ean):
    """
    Ensure EAN exists in style_master table.
    If EAN is invalid (N/A, empty) -> returns None
    If EAN doesn't exist -> creates placeholder entry
    Returns validated EAN or None
    """
    if not ean or ean.strip() == "" or ean.upper() == "N/A":
        return None  # Set to NULL (foreign key allows NULL)
    
    ean = ean.strip()
    
    # Check if EAN exists in style_master
    style_master = session.query(StyleMaster).filter_by(ean=ean).first()
    
    if not style_master:
        # Create placeholder entry in style_master to satisfy foreign key
        placeholder = StyleMaster(
            ean=ean,
            style_no=None,
            buyer=None
        )
        session.add(placeholder)
        session.flush()  # Flush to get the ID, but don't commit yet
    
    return ean


def upsert_po_item(session, row):
    """
    Avoid duplicates in po_items using SQLAlchemy:
    - Key = (po_number, ean)
    - If not exists -> INSERT
    - If exists and values changed -> UPDATE + is_revised=1
    - If exists and same -> do nothing
    """
    # Validate and ensure EAN exists in style_master
    original_ean = row.get("ean", "")
    validated_ean = ensure_ean_in_style_master(session, original_ean)
    
    # Update row with validated EAN (None if invalid)
    row["ean"] = validated_ean
    
    # Use validated_ean for query (handle None case)
    query_ean = validated_ean if validated_ean else None
    
    existing = session.query(POItem).filter_by(
        po_number=row["po_number"],
        ean=query_ean
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
    po_id = data.get("id") or data.get("row_id")  # Accept both 'id' and 'row_id'
    field = data.get("field")
    value = data.get("value")
    
    if not po_id or not field:
        return jsonify({"error": "Missing id or field"}), 400
    
    with get_db_session() as session:
        po_item = session.query(POItem).filter_by(id=po_id).first()
        if not po_item:
            return jsonify({"error": "PO item not found"}), 404
        
        response_data = {"ok": True}
        
        # Map field names
        if field == "remarks" or field == "factory_remarks":
            po_item.factory_remarks = value
        else:
            setattr(po_item, field, value)
        
        # Auto-update GRN Status to "Cleared" when GRN Date is set
        if field == "grn_date" and value and value.strip():
            po_item.grn_status = "Cleared"
            response_data["new_grn_status"] = "Cleared"
        
        # Auto-calculate Dispatched Qty and Balance when Dispatched Box is updated
        if field == "dispatched_box":
            try:
                dispatched_box = int(value) if value else 0
                caselot = po_item.caselot or 0
                quantity = po_item.quantity or 0
                
                # Calculate dispatched quantity: dispatched_box * caselot
                dispatched_qty = dispatched_box * caselot if caselot > 0 else 0
                po_item.dispatched_qty = dispatched_qty
                
                # Calculate balance: quantity - dispatched_qty
                balance = quantity - dispatched_qty
                po_item.balance = max(0, balance)  # Ensure balance is not negative
                
                response_data["dispatched_qty"] = dispatched_qty
                response_data["balance"] = po_item.balance
            except (ValueError, TypeError):
                # If conversion fails, keep existing values
                pass
        
        # commit happens automatically via context manager

    return jsonify(response_data)

# routes/po_routes.py

@po_bp.route("/admin/clear-po", methods=["POST"])
@admin_required
def clear_po_data():
    from models.po_item import POItem
    from database import get_db_session

    with get_db_session() as session:
        session.query(POItem).delete()
        session.commit()

    return redirect(url_for("dashboard.dashboard"))


@po_bp.route("/delete/<int:po_id>", methods=["POST"])
@login_required
@admin_required
def delete_po_record(po_id):
    """Delete a single PO record (Admin only)"""
    try:
        with get_db_session() as session:
            po_item = session.query(POItem).filter_by(id=po_id).first()
            if not po_item:
                return jsonify({"error": "PO record not found"}), 404
            
            # Store some info for the response
            po_number = po_item.po_number
            po_id_value = po_item.id
            
            session.delete(po_item)
            session.commit()
            
            return jsonify({
                "success": True,
                "message": f"PO record #{po_id_value} (PO: {po_number}) deleted successfully"
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

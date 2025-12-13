"""
Dashboard Routes - Main dashboard view
"""
from datetime import datetime
from flask import Blueprint, render_template
from sqlalchemy import case, func, or_
from database import get_db_session
from models.po_item import POItem
from models.style_master import StyleMaster
from auth.decorators import login_required
from utils.helpers import calculate_exfactory_flag, parse_exfactory_date_for_sort
from config import FACTORIES, TRANSPORTERS

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/dashboard')
@login_required
def dashboard():
    """
    Main dashboard - shows all PO items with style and buyer info
    Requires authentication
    """
    with get_db_session() as session:
        # JOIN query to get PO items with style master data
        query = session.query(POItem, StyleMaster).outerjoin(
            StyleMaster, POItem.ean == StyleMaster.ean
        ).order_by(POItem.id.desc())
        
        results = query.all()
        
        processed = []
        for po_item, style_master in results:
            d = po_item.to_dict()
            
            # Override with style_master data if available
            if style_master:
                d['style_no'] = style_master.style_no or d.get('style_no', '')
                d['buyer'] = style_master.buyer or d.get('buyer', '')
            
            # Calculate ex-factory flag
            d['exfactory_flag'] = calculate_exfactory_flag(d.get("ex_factory_date", ""))
            
            processed.append(d)
        
        # Sort by Ex-Factory Date (earliest first), then Status (Pending first, Dispatched last), then OCN
        def get_status_priority(status):
            """Returns priority: 0 for Pending, 1 for others, 2 for Dispatched"""
            if status == "Pending":
                return 0
            elif status == "Dispatched":
                return 2
            else:
                return 1  # Cancelled and other statuses
        
        processed.sort(key=lambda x: (
            parse_exfactory_date_for_sort(x.get("ex_factory_date", "")) or datetime.max,  # Ex-Factory Date first (earliest first)
            get_status_priority(x.get("status", "Pending")),  # Then Status priority
            x.get("ocn", "") or ""  # Then OCN
        ))
    
    return render_template(
        "dashboard.html",
        data=processed,
        factories=FACTORIES,
        transporters=TRANSPORTERS,
    )


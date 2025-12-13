"""
Helper utility functions
"""
from datetime import datetime, timedelta


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


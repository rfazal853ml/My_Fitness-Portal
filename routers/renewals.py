"""
Renewals router — Membership Renewals module.
Two tabs: Renewals Members (active memberships needing renewal) and
Renewals History (derived renewal log from memberships.previous_plan_id).
"""
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from utils.dependencies import get_current_user
from services.renewal_service import RenewalService
from services.plan_service import PlanService
from services.supabase_client import get_supabase

router    = APIRouter(prefix="/renewals", tags=["renewals"])
templates = Jinja2Templates(directory="templates")


# ── Private helpers ────────────────────────────────────────────────────────────

def _gym_name() -> str:
    try:
        db = get_supabase()
        r  = db.table("settings").select("value").eq("key", "gym_name").single().execute()
        return r.data["value"] if r.data else "Gym25"
    except Exception:
        return "Gym25"


def _get_plans() -> list:
    try:
        return PlanService.get_all(status="active")
    except Exception:
        return []


# ── MAIN PAGE (Members tab default) ───────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def renewals_page(
    request:      Request,
    tab:          str  = "members",     # "members" | "history"
    search:       str  = "",
    days:         str  = "",
    status:       str  = "",
    page:         int  = 1,
    success:      str  = "",
    error:        str  = "",
    current_user: dict = Depends(get_current_user),
):
    stats = RenewalService.get_stats()
    plans = _get_plans()

    if tab == "history":
        data = RenewalService.get_renewal_history(search, page)
    else:
        data = RenewalService.get_renewal_members(search, days, status, page)

    return templates.TemplateResponse(request, "renewals/renewals.html", {
        "gym_name":    _gym_name(),
        "page_title":  "Membership Renewals",
        "active_page": "renewals",
        "user":        current_user,
        "stats":       stats,
        "plans":       plans,
        "tab":         tab,
        "items":       data["items"],
        "total":       data["total"],
        "page":        data["page"],
        "per_page":    data["per_page"],
        "total_pages": data["total_pages"],
        "search":      search,
        "days":        days,
        "status":      status,
        "success":     success,
        "error":       error,
    })


# ── SEARCH — HTMX partial (Members tab) ───────────────────────────────────────

@router.get("/search", response_class=HTMLResponse)
async def search_renewals(
    request:      Request,
    q:            str  = "",
    days:         str  = "",
    status:       str  = "",
    page:         int  = 1,
    current_user: dict = Depends(get_current_user),
):
    data = RenewalService.get_renewal_members(q, days, status, page)
    return templates.TemplateResponse(request, "renewals/partials/_renewal_rows.html", {
        "items":       data["items"],
        "total":       data["total"],
        "page":        data["page"],
        "total_pages": data["total_pages"],
        "search":      q,
        "days":        days,
        "status":      status,
    })


# ── SEARCH — HTMX partial (History tab) ───────────────────────────────────────

@router.get("/history/search", response_class=HTMLResponse)
async def search_history(
    request:      Request,
    q:            str  = "",
    page:         int  = 1,
    current_user: dict = Depends(get_current_user),
):
    data = RenewalService.get_renewal_history(q, page)
    return templates.TemplateResponse(request, "renewals/partials/_history_rows.html", {
        "items":       data["items"],
        "total":       data["total"],
        "page":        data["page"],
        "total_pages": data["total_pages"],
        "search":      q,
    })


# ── RENEWAL DETAIL — JSON (for modal) ─────────────────────────────────────────

@router.get("/detail/{membership_id}")
async def renewal_detail(
    membership_id: str,
    current_user:  dict = Depends(get_current_user),
):
    try:
        detail = RenewalService.get_renewal_detail(membership_id)
        return JSONResponse({"success": True, "data": detail})
    except HTTPException as e:
        return JSONResponse({"success": False, "error": e.detail}, status_code=404)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ── PROCESS RENEWAL ────────────────────────────────────────────────────────────

@router.post("/renew/{membership_id}")
async def process_renewal(
    membership_id:           str,
    new_plan_id:              str  = Form(...),
    duration_months:          str  = Form(""),
    start_date:               str  = Form(""),
    expiry_date:              str  = Form(""),
    extra_discount_percent:   str  = Form("0"),
    payment_method:           str  = Form("cash"),
    payment_status:           str  = Form("pending"),
    skip_dues:                str  = Form("false"),
    current_user:             dict = Depends(get_current_user),
):
    try:
        result = RenewalService.renew(membership_id, {
            "new_plan_id":             new_plan_id,
            "duration_months":         duration_months,
            "start_date":              start_date,
            "expiry_date":             expiry_date,
            "extra_discount_percent":  extra_discount_percent,
            "payment_method":          payment_method,
            "payment_status":          payment_status,
            "skip_dues":               skip_dues.lower() == "true",
        })
        return JSONResponse({"success": True, "data": result})
    except HTTPException as e:
        return JSONResponse({"success": False, "error": e.detail}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
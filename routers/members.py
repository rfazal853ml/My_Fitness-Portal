"""
Members router — list, add, edit, delete, view profile, invoice.
All HTML responses; HTMX partials for search/pagination.
"""
import json
from typing import Optional, List

from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from utils.dependencies import get_current_user
from services.member_service import MemberService
from services.plan_service import PlanService
from services.supabase_client import get_supabase
from services.storage_service import StorageService

router = APIRouter(prefix="/members", tags=["members"])
templates = Jinja2Templates(directory="templates")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _gym_name() -> str:
    try:
        db = get_supabase()
        r = db.table("settings").select("value").eq("key", "gym_name").single().execute()
        return r.data["value"] if r.data else "Gym25"
    except Exception:
        return "Gym25"


def _gym_settings() -> dict:
    """Fetch all gym settings as a key→value dict."""
    try:
        db = get_supabase()
        rows = db.table("settings").select("key, value").execute().data or []
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}


def _get_plans() -> list:
    try:
        return PlanService.get_all(status="active")
    except Exception:
        return []


# ── MEMBERS LIST ──────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def members_page(
    request:      Request,
    search:       str = "",
    plan_id:      str = "",
    status:       str = "",
    gender:       str = "",
    page:         int = 1,
    success:      str = "",
    error:        str = "",
    current_user: dict = Depends(get_current_user),
):
    stats  = MemberService.get_stats()
    data   = MemberService.get_all(search, plan_id, status, gender, page)
    plans  = _get_plans()

    return templates.TemplateResponse(request, "members/members.html", {
        "gym_name":    _gym_name(),
        "page_title":  "Members",
        "active_page": "members",
        "user":        current_user,
        "stats":       stats,
        "members":     data["members"],
        "total":       data["total"],
        "page":        data["page"],
        "per_page":    data["per_page"],
        "total_pages": data["total_pages"],
        "plans":       plans,
        "search":      search,
        "plan_id":     plan_id,
        "status":      status,
        "gender":      gender,
        "success":     success,
        "error":       error,
    })


# ── SEARCH (HTMX partial) ──────────────────────────────────────────────────────

@router.get("/search", response_class=HTMLResponse)
async def search_members(
    request:      Request,
    q:            str = "",
    plan_id:      str = "",
    status:       str = "",
    gender:       str = "",
    page:         int = 1,
    current_user: dict = Depends(get_current_user),
):
    data  = MemberService.get_all(q, plan_id, status, gender, page)
    plans = _get_plans()
    return templates.TemplateResponse(request, "members/partials/_member_rows.html", {
        "members":     data["members"],
        "total":       data["total"],
        "page":        data["page"],
        "total_pages": data["total_pages"],
        "plans":       plans,
        "search":      q,
        "plan_id":     plan_id,
        "status":      status,
        "gender":      gender,
    })


# ── CHECK CNIC (JSON, for Add Member modal) ────────────────────────────────────

@router.get("/check-cnic")
async def check_cnic(
    cnic:         str,
    cnic_type:    str = "member",
    exclude_id:   str = "",
    current_user: dict = Depends(get_current_user),
):
    exists = MemberService.check_cnic(cnic, exclude_id, cnic_type)
    return {"exists": exists}


# ── CREATE MEMBER ─────────────────────────────────────────────────────────────

@router.post("/create")
async def create_member(
    request:            Request,
    full_name:          str           = Form(...),
    father_name:        str           = Form(""),
    age:                str           = Form(""),
    date_of_birth:      str           = Form(""),
    cnic_type:          str           = Form("member"),
    cnic:               str           = Form(...),
    guardian_cnic:      str           = Form(""),
    phone:              str           = Form(...),
    gender:             str           = Form(""),
    blood_group:        str           = Form(""),
    email:              str           = Form(""),
    joining_date:       str           = Form(""),
    health_issues_json: str           = Form("[]"),
    address:            str           = Form(""),
    admission_fee:      str           = Form("0"),
    discount_percent:   str           = Form("0"),
    plan_id:            str           = Form(""),
    membership_start:   str           = Form(""),
    membership_expiry:  str           = Form(""),
    note_title:         str           = Form(""),
    note_description:   str           = Form(""),
    photo:              Optional[UploadFile] = File(None),
    current_user:       dict          = Depends(get_current_user),
):
    try:
        photo_url = None
        if photo and getattr(photo, "filename", ""):
            from uuid import uuid4
            photo_url = await StorageService.upload_profile_image(photo, f"member_{uuid4()}")

        health_issues = []
        try:
            health_issues = json.loads(health_issues_json) if health_issues_json else []
        except Exception:
            pass

        MemberService.create({
            "full_name":          full_name,
            "father_name":        father_name or None,
            "age":                age or None,
            "date_of_birth":      date_of_birth or None,
            "joining_date":       joining_date or None,
            "cnic_type":          cnic_type,
            "cnic":               cnic,
            "guardian_cnic":      guardian_cnic,
            "phone":              phone,
            "email":              email or None,
            "gender":             gender or None,
            "address":            address or None,
            "photo_url":          photo_url,
            "notes":              note_description or None,
            "plan_id":            plan_id or None,
            "membership_start":   membership_start or None,
            "membership_expiry":  membership_expiry or None,
            "registered_by":      current_user.get("id"),
        })
        return RedirectResponse(
            url="/members/?success=Member+added+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/members/?error={e.detail}",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/members/?error=Something+went+wrong:+{str(e)}",
            status_code=302,
        )


# ── UPDATE MEMBER ─────────────────────────────────────────────────────────────

@router.post("/update/{member_id}")
async def update_member(
    member_id:          str,
    full_name:          str  = Form(...),
    father_name:        str  = Form(""),
    age:                str  = Form(""),
    date_of_birth:      str  = Form(""),
    cnic_type:          str  = Form("member"),
    cnic:               str  = Form(...),
    guardian_cnic:      str  = Form(""),
    phone:              str  = Form(...),
    gender:             str  = Form(""),
    blood_group:        str  = Form(""),
    email:              str  = Form(""),
    joining_date:       str  = Form(""),
    health_issues_json: str  = Form("[]"),
    address:            str  = Form(""),
    admission_fee:      str  = Form("0"),
    discount_percent:   str  = Form("0"),
    is_active:          str  = Form("true"),
    plan_id:            str  = Form(""),
    membership_start:   str  = Form(""),
    membership_expiry:  str  = Form(""),
    note_title:         str  = Form(""),
    note_description:   str  = Form(""),
    photo:              Optional[UploadFile] = File(None),
    current_user:       dict = Depends(get_current_user),
):
    try:
        photo_url = None
        if photo and getattr(photo, "filename", ""):
            photo_url = await StorageService.upload_profile_image(photo, f"member_{member_id}")

        health_issues = []
        try:
            health_issues = json.loads(health_issues_json) if health_issues_json else []
        except Exception:
            pass

        MemberService.update(member_id, {
            "full_name":          full_name,
            "father_name":        father_name or None,
            "age":                age or None,
            "date_of_birth":      date_of_birth or None,
            "cnic_type":          cnic_type,
            "cnic":               cnic,
            "guardian_cnic":      guardian_cnic,
            "phone":              phone or None,
            "email":              email or None,
            "gender":             gender or None,
            "blood_group":        blood_group or None,
            "address":            address or None,
            "photo_url":          photo_url,
            "is_active":          is_active == "true",
            "health_issues":      health_issues,
            "notes":              note_description or None,
            "plan_id":            plan_id or None,
            "membership_start":   membership_start or None,
            "membership_expiry":  membership_expiry or None,
        })
        return RedirectResponse(
            url="/members/?success=Member+updated+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/members/?error={e.detail}",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/members/?error={str(e)}",
            status_code=302,
        )


# ── TOGGLE STATUS ─────────────────────────────────────────────────────────────

@router.post("/toggle-status/{member_id}")
async def toggle_member_status(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    try:
        new_status = MemberService.toggle_active(member_id)
        return {"success": True, "is_active": new_status}
    except HTTPException as e:
        return {"success": False, "error": e.detail}


# ── DELETE MEMBER ─────────────────────────────────────────────────────────────

@router.post("/delete/{member_id}")
async def delete_member(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    try:
        MemberService.delete(member_id)
        return RedirectResponse(
            url="/members/?success=Member+deleted+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/members/?error={e.detail}",
            status_code=302,
        )


# ── INVOICE / RECEIPT ─────────────────────────────────────────────────────────

@router.get("/{member_id}/invoice", response_class=HTMLResponse)
async def member_invoice(
    member_id:    str,
    request:      Request,
    payment_id:   str  = "",
    current_user: dict = Depends(get_current_user),
):
    """
    Render a print-ready invoice/receipt for the member's latest (or specified) payment.
    Opens in a new tab; user can Ctrl+P → Save as PDF.
    """
    member   = MemberService.get_by_id(member_id)
    payments = MemberService.get_payments(member_id)

    # Pick the requested payment or fall back to the most recent one
    payment = None
    if payment_id:
        payment = next((p for p in payments if p.get("id") == payment_id), None)
    if not payment and payments:
        payment = payments[0]

    gym_settings = _gym_settings()

    return templates.TemplateResponse(request, "members/invoice.html", {
        "member":       member,
        "payment":      payment,
        "gym_name":     _gym_name(),
        "gym_settings": gym_settings,
    })


# ── PROFILE — JSON endpoints (loaded by JS inside the profile modal) ───────────

@router.get("/profile/{member_id}/attendance")
async def profile_attendance(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    data = MemberService.get_attendance(member_id)
    return JSONResponse(data)


@router.get("/profile/{member_id}/payments")
async def profile_payments(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    payments = MemberService.get_payments(member_id)
    return JSONResponse(payments)


@router.get("/profile/{member_id}/memberships")
async def profile_memberships(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    data = MemberService.get_memberships(member_id)
    return JSONResponse(data)


@router.get("/profile/{member_id}/notes")
async def profile_notes(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    notes = MemberService.get_notes(member_id)
    return JSONResponse(notes)


@router.get("/profile/{member_id}")
async def profile_summary(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    member      = MemberService.get_by_id(member_id)
    attendance  = MemberService.get_attendance(member_id)
    days_active = MemberService.get_days_active(member_id)
    return JSONResponse({
        "member":          member,
        "days_active":     days_active,
        "attendance_rate": attendance["attendance_rate"],
        "last_entry":      attendance["last_entry"],
    })
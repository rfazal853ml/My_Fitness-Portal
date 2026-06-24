"""
Members router — list, add, edit, delete, toggle status, notes, profile tabs, invoice.
HTML page responses + HTMX partials + JSON endpoints for the profile modal.
"""
import json
from typing import Optional, List
from uuid import uuid4

from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from utils.dependencies import get_current_user
from services.member_service import MemberService
from services.plan_service import PlanService
from services.supabase_client import get_supabase
from services.storage_service import StorageService

router    = APIRouter(prefix="/members", tags=["members"])
templates = Jinja2Templates(directory="templates")


# ── Private helpers ────────────────────────────────────────────────────────────

def _gym_name() -> str:
    try:
        db = get_supabase()
        r  = db.table("settings").select("value").eq("key", "gym_name").single().execute()
        return r.data["value"] if r.data else "Gym25"
    except Exception:
        return "Gym25"


def _gym_settings() -> dict:
    try:
        rows = get_supabase().table("settings").select("key, value").execute().data or []
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}


def _get_plans() -> list:
    try:
        return PlanService.get_all(status="active")
    except Exception:
        return []


# ── MEMBERS LIST PAGE ─────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def members_page(
    request:      Request,
    search:       str  = "",
    plan_id:      str  = "",
    status:       str  = "",
    gender:       str  = "",
    page:         int  = 1,
    success:      str  = "",
    error:        str  = "",
    current_user: dict = Depends(get_current_user),
):
    stats = MemberService.get_stats()
    data  = MemberService.get_all(search, plan_id, status, gender, page)
    plans = _get_plans()

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


# ── SEARCH — HTMX partial ─────────────────────────────────────────────────────

@router.get("/search", response_class=HTMLResponse)
async def search_members(
    request:      Request,
    q:            str  = "",
    plan_id:      str  = "",
    status:       str  = "",
    gender:       str  = "",
    page:         int  = 1,
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


# ── CHECK CNIC — JSON (used by Add Member modal) ──────────────────────────────

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
    full_name:          str                  = Form(...),
    father_name:        str                  = Form(""),
    age:                str                  = Form(""),
    date_of_birth:      str                  = Form(""),
    cnic_type:          str                  = Form("member"),
    cnic:               str                  = Form(...),
    guardian_cnic:      str                  = Form(""),
    phone:              str                  = Form(...),
    gender:             str                  = Form(""),
    blood_group:        str                  = Form(""),
    email:              str                  = Form(""),
    joining_date:       str                  = Form(""),
    health_issues_json: str                  = Form("[]"),
    address:            str                  = Form(""),
    admission_fee:      str                  = Form("0"),
    discount_percent:   str                  = Form("0"),
    plan_id:            str                  = Form(""),
    membership_start:   str                  = Form(""),
    membership_expiry:  str                  = Form(""),
    note_title:         str                  = Form(""),
    note_description:   str                  = Form(""),
    photo:              Optional[UploadFile] = File(None),
    current_user:       dict                 = Depends(get_current_user),
):
    try:
        # Upload photo if provided
        photo_url = None
        if photo and getattr(photo, "filename", ""):
            photo_url = await StorageService.upload_profile_image(photo, f"member_{uuid4()}")

        # Parse health issues JSON
        health_issues = []
        try:
            health_issues = json.loads(health_issues_json) if health_issues_json else []
        except Exception:
            pass

        MemberService.create({
            "full_name":         full_name,
            "father_name":       father_name,
            "age":               age,
            "date_of_birth":     date_of_birth,
            "joining_date":      joining_date,
            "cnic_type":         cnic_type,
            "cnic":              cnic,
            "guardian_cnic":     guardian_cnic,
            "phone":             phone,
            "email":             email,
            "gender":            gender,
            "blood_group":       blood_group,
            "address":           address,
            "health_issues":     health_issues,
            "photo_url":         photo_url,
            "admission_fee":     admission_fee,
            "discount_percent":  discount_percent,
            "plan_id":           plan_id,
            "membership_start":  membership_start,
            "membership_expiry": membership_expiry,
            "note_title":        note_title,
            "note_description":  note_description,
            "registered_by":     current_user.get("id"),
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
    full_name:          str                  = Form(...),
    father_name:        str                  = Form(""),
    age:                str                  = Form(""),
    date_of_birth:      str                  = Form(""),
    cnic_type:          str                  = Form("member"),
    cnic:               str                  = Form(...),
    guardian_cnic:      str                  = Form(""),
    phone:              str                  = Form(...),
    gender:             str                  = Form(""),
    blood_group:        str                  = Form(""),
    email:              str                  = Form(""),
    joining_date:       str                  = Form(""),
    health_issues_json: str                  = Form("[]"),
    address:            str                  = Form(""),
    admission_fee:      str                  = Form("0"),
    discount_percent:   str                  = Form("0"),
    plan_id:            str                  = Form(""),
    membership_start:   str                  = Form(""),
    membership_expiry:  str                  = Form(""),
    note_title:         str                  = Form(""),
    note_description:   str                  = Form(""),
    photo:              Optional[UploadFile] = File(None),
    current_user:       dict                 = Depends(get_current_user),
):
    try:
        # Upload photo if a new one was provided
        photo_url = None
        if photo and getattr(photo, "filename", ""):
            photo_url = await StorageService.upload_profile_image(photo, f"member_{member_id}")

        # Parse health issues JSON
        health_issues = []
        try:
            health_issues = json.loads(health_issues_json) if health_issues_json else []
        except Exception:
            pass

        MemberService.update(member_id, {
            "full_name":         full_name,
            "father_name":       father_name,
            "age":               age,
            "date_of_birth":     date_of_birth,
            "joining_date":      joining_date,
            "cnic_type":         cnic_type,
            "cnic":              cnic,
            "guardian_cnic":     guardian_cnic,
            "phone":             phone,
            "email":             email,
            "gender":            gender,
            "blood_group":       blood_group,
            "address":           address,
            "health_issues":     health_issues,
            "photo_url":         photo_url,
            "plan_id":           plan_id,
            "membership_start":  membership_start,
            "membership_expiry": membership_expiry,
            "note_title":        note_title,
            "note_description":  note_description,
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
            url=f"/members/?error=Something+went+wrong:+{str(e)}",
            status_code=302,
        )


# ── TOGGLE STATUS — JSON (called by double-click on status badge) ─────────────

@router.post("/toggle-status/{member_id}")
async def toggle_member_status(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    try:
        new_status = MemberService.toggle_active(member_id)
        return {"success": True, "status": new_status}
    except HTTPException as e:
        return JSONResponse({"success": False, "error": e.detail}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


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
    except Exception as e:
        return RedirectResponse(
            url=f"/members/?error=Something+went+wrong:+{str(e)}",
            status_code=302,
        )


# ── ADD NOTE — JSON (called from profile modal Notes tab) ────────────────────

@router.post("/add-note/{member_id}")
async def add_member_note(
    member_id:    str,
    title:        str  = Form(...),
    description:  str  = Form(""),
    current_user: dict = Depends(get_current_user),
):
    try:
        note = MemberService.add_note(member_id, title, description)
        return JSONResponse({"success": True, "note": note})
    except HTTPException as e:
        return JSONResponse({"success": False, "error": e.detail}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ── INVOICE / RECEIPT — opens in new tab, Ctrl+P → PDF ───────────────────────

@router.get("/{member_id}/invoice", response_class=HTMLResponse)
async def member_invoice(
    member_id:    str,
    request:      Request,
    payment_id:   str  = "",
    current_user: dict = Depends(get_current_user),
):
    member   = MemberService.get_by_id(member_id)
    payments = MemberService.get_payments(member_id)

    # Use requested payment or fall back to most recent
    payment = None
    if payment_id:
        payment = next((p for p in payments if str(p.get("id")) == payment_id), None)
    if not payment and payments:
        payment = payments[0]

    return templates.TemplateResponse(request, "invoice/invoice.html", {
        "member":       member,
        "payment":      payment,
        "gym_name":     _gym_name(),
        "gym_settings": _gym_settings(),
    })


# ══════════════════════════════════════════════════════════════════════════════
#  PROFILE — JSON endpoints  (loaded dynamically by JS inside profile modal)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/profile/{member_id}")
async def profile_summary(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    """Header stats: days active, attendance rate, fee status, member details."""
    member      = MemberService.get_by_id(member_id)
    attendance  = MemberService.get_attendance(member_id)
    days_active = MemberService.get_days_active(member_id)

    # Safely convert health_issues for JSON
    hi = member.get("health_issues") or []
    if isinstance(hi, str):
        try:
            hi = json.loads(hi)
        except Exception:
            hi = []
    member["health_issues"] = hi

    # Remove non-serialisable nested objects
    member.pop("membership", None)
    member.pop("memberships", None)

    return JSONResponse({
        "member":          member,
        "days_active":     days_active,
        "attendance_rate": attendance["attendance_rate"],
        "fee_status":      member.get("fee_status", "unpaid"),
        "last_entry":      attendance["last_entry"],
    })


@router.get("/profile/{member_id}/attendance")
async def profile_attendance(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    """Attendance stats + present-date list for the heatmap."""
    return JSONResponse(MemberService.get_attendance(member_id))


@router.get("/profile/{member_id}/payments")
async def profile_payments(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    """Payment history table."""
    return JSONResponse(MemberService.get_payments(member_id))


@router.get("/profile/{member_id}/memberships")
async def profile_memberships(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    """Current plan + plan history."""
    return JSONResponse(MemberService.get_memberships(member_id))


@router.get("/profile/{member_id}/notes")
async def profile_notes(
    member_id:    str,
    current_user: dict = Depends(get_current_user),
):
    """All staff notes for this member."""
    return JSONResponse(MemberService.get_notes(member_id))
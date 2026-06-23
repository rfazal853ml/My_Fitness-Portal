import json
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional

from utils.dependencies import get_current_user
from services.plan_service import PlanService, duration_to_days
from services.supabase_client import get_supabase

router = APIRouter(prefix="/plans", tags=["plans"])
templates = Jinja2Templates(directory="templates")


def _gym_name() -> str:
    try:
        db = get_supabase()
        r = db.table("settings").select("value").eq("key", "gym_name").single().execute()
        return r.data["value"] if r.data else "Gym25"
    except Exception:
        return "Gym25"


# ── MAIN PAGE ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def plans_page(
    request:      Request,
    search:       str = "",
    gender:       str = "",
    status:       str = "",
    success:      str = "",
    error:        str = "",
    current_user: dict = Depends(get_current_user),
):
    stats = PlanService.get_stats()
    plans = PlanService.get_all(search, gender, status)

    return templates.TemplateResponse(request, "plans/plans.html", {
        "gym_name":    _gym_name(),
        "page_title":  "Plans",
        "active_page": "plans",
        "user":        current_user,
        "stats":       stats,
        "plans":       plans,
        "search":      search,
        "gender":      gender,
        "status":      status,
        "success":     success,
        "error":       error,
    })


# ── CREATE PLAN ───────────────────────────────────────────────────────────────

@router.post("/create")
async def create_plan(
    request:          Request,
    name:             str   = Form(...),
    price:            float = Form(...),
    duration_value:   int   = Form(...),
    duration_unit:    str   = Form("months"),
    gender:           str   = Form("any"),
    discount_percent: float = Form(0.0),
    features_json:    str   = Form("[]"),
    current_user:     dict  = Depends(get_current_user),
):
    try:
        features = json.loads(features_json) if features_json else []
        days     = duration_to_days(duration_value, duration_unit)

        PlanService.create({
            "name":             name,
            "price":            price,
            "duration_days":    days,
            "gender":           gender,
            "discount_percent": discount_percent,
            "features":         features,
        })
        return RedirectResponse(
            url="/plans/?success=Plan+created+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/plans/?error={e.detail}",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/plans/?error=Something+went+wrong:+{str(e)}",
            status_code=302,
        )


# ── UPDATE PLAN ───────────────────────────────────────────────────────────────

@router.post("/update/{plan_id}")
async def update_plan(
    plan_id:          str,
    name:             str   = Form(...),
    price:            float = Form(...),
    duration_value:   int   = Form(...),
    duration_unit:    str   = Form("months"),
    gender:           str   = Form("any"),
    discount_percent: float = Form(0.0),
    features_json:    str   = Form("[]"),
    is_active:        str   = Form("true"),
    current_user:     dict  = Depends(get_current_user),
):
    try:
        features = json.loads(features_json) if features_json else []
        days     = duration_to_days(duration_value, duration_unit)

        PlanService.update(plan_id, {
            "name":             name,
            "price":            price,
            "duration_days":    days,
            "gender":           gender,
            "discount_percent": discount_percent,
            "features":         features,
            "is_active":        is_active == "true",
        })
        return RedirectResponse(
            url="/plans/?success=Plan+updated+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/plans/?error={e.detail}",
            status_code=302,
        )


# ── TOGGLE ACTIVE ─────────────────────────────────────────────────────────────

@router.post("/toggle/{plan_id}")
async def toggle_plan(
    plan_id:      str,
    current_user: dict = Depends(get_current_user),
):
    try:
        new_status = PlanService.toggle_active(plan_id)
        label = "activated" if new_status else "deactivated"
        return RedirectResponse(
            url=f"/plans/?success=Plan+{label}+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(url=f"/plans/?error={e.detail}", status_code=302)


@router.post("/toggle-status/{plan_id}")
async def toggle_plan_status(
    plan_id:      str,
    current_user: dict = Depends(get_current_user),
):
    try:
        new_status = PlanService.toggle_active(plan_id)
        return {"success": True, "is_active": new_status}
    except HTTPException as e:
        return {"success": False, "error": e.detail}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── DELETE PLAN ───────────────────────────────────────────────────────────────

@router.post("/delete/{plan_id}")
async def delete_plan(
    plan_id:      str,
    current_user: dict = Depends(get_current_user),
):
    try:
        PlanService.delete(plan_id)
        return RedirectResponse(
            url="/plans/?success=Plan+deleted+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(url=f"/plans/?error={e.detail}", status_code=302)


# ── SEARCH (HTMX partial) ─────────────────────────────────────────────────────

@router.get("/search", response_class=HTMLResponse)
async def search_plans(
    request:      Request,
    q:            str  = "",
    gender:       str  = "",
    status:       str  = "",
    current_user: dict = Depends(get_current_user),
):
    plans = PlanService.get_all(q, gender, status)
    return templates.TemplateResponse(request, "plans/partials/_plan_cards.html", {
        "plans": plans,
    })
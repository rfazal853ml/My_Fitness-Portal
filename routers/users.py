from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional, List
import os
from uuid import uuid4

from utils.dependencies import get_current_user, require_role
from services.user_service import UserService, RoleService
from services.supabase_client import get_supabase
from services.storage_service import StorageService

router = APIRouter(prefix="/users", tags=["users"])
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
async def users_page(
    request: Request,
    tab:     str = "users",
    search:  str = "",
    success: str = "",
    error:   str = "",
    current_user: dict = Depends(require_role("admin")),
):
    stats       = UserService.get_stats()
    all_users   = UserService.get_all(search)
    roles       = RoleService.get_all()
    permissions = RoleService.get_all_permissions()

    # Group permissions by module for the modal checkboxes
    modules: dict[str, list] = {}
    for p in permissions:
        modules.setdefault(p["module"], []).append(p)

    return templates.TemplateResponse(request, "users/users.html", {
        "gym_name":     _gym_name(),
        "page_title":   "User Management",
        "active_page":  "users",
        "user":         current_user,
        "stats":        stats,
        "all_users":    all_users,
        "roles":        roles,
        "modules":      modules,
        "tab":          tab,
        "search":       search,
        "success":      success,
        "error":        error,
    })


# ── CREATE USER ───────────────────────────────────────────────────────────────

@router.post("/create")
async def create_user(
    request:  Request,
    name:     str = Form(...),
    email:    str = Form(...),
    phone:    str = Form(""),
    cnic:     str = Form(""),
    address:  str = Form(""),
    role_id:  str = Form(...),
    profile_pic: Optional[UploadFile] = File(None),
    current_user: dict = Depends(require_role("admin")),
):
    try:
        # handle optional profile picture upload to Supabase Storage
        photo_url = None
        if profile_pic is not None and getattr(profile_pic, "filename", ""):
            # Generate a temporary user identifier for storage path
            # (we use UUID to ensure uniqueness before user is created)
            temp_user_id = str(uuid4())
            photo_url = await StorageService.upload_profile_image(profile_pic, temp_user_id)

        result = UserService.create({
            "name": name, "email": email,
            "phone": phone, "cnic": cnic,
            "address": address, "role_id": role_id,
            "photo_url": photo_url,
        })
        temp_pw = result["temp_password"]
        return RedirectResponse(
            url=f"/users/?success=User+created!+Temp+password:+{temp_pw}",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/users/?error={e.detail}&tab=users",
            status_code=302,
        )


# ── UPDATE USER ───────────────────────────────────────────────────────────────

@router.post("/update/{user_id}")
async def update_user(
    user_id:  str,
    name:     str = Form(...),
    email:    str = Form(...),
    phone:    str = Form(""),
    cnic:     str = Form(""),
    address:  str = Form(""),
    role_id:  str = Form(...),
    is_active: str = Form("true"),
    profile_pic: Optional[UploadFile] = File(None),
    current_user: dict = Depends(require_role("admin")),
):
    try:
        # handle optional profile picture upload to Supabase Storage
        photo_url = None
        if profile_pic is not None and getattr(profile_pic, "filename", ""):
            photo_url = await StorageService.upload_profile_image(profile_pic, user_id)
            
            # Delete old image if new one is uploaded
            old_user = UserService.get_by_id(user_id)
            if old_user and old_user.get("photo_url"):
                StorageService.delete_profile_image(old_user["photo_url"])

        payload = {
            "name": name, "email": email,
            "phone": phone or None, "cnic": cnic or None,
            "address": address or None, "role_id": role_id,
            "is_active": is_active == "true",
        }
        if photo_url:
            payload["photo_url"] = photo_url

        UserService.update(user_id, payload)
        return RedirectResponse(
            url="/users/?success=User+updated+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/users/?error={e.detail}&tab=users",
            status_code=302,
        )


# ── DELETE USER ───────────────────────────────────────────────────────────────

@router.post("/delete/{user_id}")
async def delete_user(
    user_id:      str,
    current_user: dict = Depends(require_role("admin")),
):
    # Prevent deleting yourself
    if user_id == current_user["id"]:
        return RedirectResponse(
            url="/users/?error=You+cannot+delete+your+own+account",
            status_code=302,
        )
    try:
        # Delete profile image from Supabase Storage before deleting user
        user = UserService.get_by_id(user_id)
        if user and user.get("photo_url"):
            StorageService.delete_profile_image(user["photo_url"])
        
        UserService.delete(user_id)
        return RedirectResponse(
            url="/users/?success=User+deleted+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/users/?error={e.detail}",
            status_code=302,
        )


# ── RESET USER PASSWORD ───────────────────────────────────────────────────────

@router.post("/reset-password/{user_id}")
async def reset_user_password(
    user_id:      str,
    current_user: dict = Depends(require_role("admin")),
):
    temp_pw = UserService.reset_password(user_id)
    return RedirectResponse(
        url=f"/users/?success=Password+reset!+New+temp:+{temp_pw}",
        status_code=302,
    )


# ── CREATE ROLE ───────────────────────────────────────────────────────────────

@router.post("/roles/create")
async def create_role(
    request:        Request,
    name:           str        = Form(...),
    description:    str        = Form(""),
    permission_ids: List[str]  = Form(default=[]),
    current_user:   dict       = Depends(require_role("admin")),
):
    try:
        RoleService.create(name, description, permission_ids)
        return RedirectResponse(
            url="/users/?tab=roles&success=Role+created+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/users/?tab=roles&error={e.detail}",
            status_code=302,
        )


# ── UPDATE ROLE ───────────────────────────────────────────────────────────────

@router.post("/roles/update/{role_id}")
async def update_role(
    role_id:        str,
    name:           str        = Form(...),
    description:    str        = Form(""),
    permission_ids: List[str]  = Form(default=[]),
    current_user:   dict       = Depends(require_role("admin")),
):
    try:
        RoleService.update(role_id, name, description, permission_ids)
        return RedirectResponse(
            url="/users/?tab=roles&success=Role+updated+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/users/?tab=roles&error={e.detail}",
            status_code=302,
        )


# ── DELETE ROLE ───────────────────────────────────────────────────────────────

@router.post("/roles/delete/{role_id}")
async def delete_role(
    role_id:      str,
    current_user: dict = Depends(require_role("admin")),
):
    try:
        RoleService.delete(role_id)
        return RedirectResponse(
            url="/users/?tab=roles&success=Role+deleted+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/users/?tab=roles&error={e.detail}",
            status_code=302,
        )


# ── SEARCH USERS (HTMX partial) ───────────────────────────────────────────────

@router.get("/search", response_class=HTMLResponse)
async def search_users(
    request:      Request,
    q:            str  = "",
    tab:          str  = "users",
    current_user: dict = Depends(require_role("admin")),
):
    if tab == "roles":
        roles = RoleService.get_all(q)
        return templates.TemplateResponse(request, "users/partials/_role_cards.html", {
            "roles": roles,
        })

    users = UserService.get_all(q)
    roles = RoleService.get_all()
    return templates.TemplateResponse(request, "users/partials/_user_rows.html", {
        "all_users": users,
        "roles":     roles,
    })
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.auth_service import AuthService
from services.email_service import EmailService
from config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="templates")
settings = get_settings()


def _get_gym_name() -> str:
    """Fetch gym name from DB for templates."""
    try:
        from services.supabase_client import get_supabase
        db = get_supabase()
        result = db.table("settings").select("value").eq("key", "gym_name").single().execute()
        return result.data["value"] if result.data else settings.app_name
    except Exception:
        return settings.app_name


# ── LOGIN ────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # Already logged in → redirect to dashboard
    token = request.cookies.get("access_token")
    if token:
        return RedirectResponse(url="/dashboard", status_code=302)

    return templates.TemplateResponse(request, "auth/login.html", {
        "gym_name": _get_gym_name(),
        "error":    request.query_params.get("error"),
    })


@router.post("/login")
async def login_post(
    request: Request,
    email:    str = Form(...),
    password: str = Form(...),
):
    try:
        result = AuthService.login(email, password)
        response = RedirectResponse(url="/dashboard", status_code=302)
        response.set_cookie(
            key="access_token",
            value=result["token"],
            httponly=True,          # JS cannot access — XSS protection
            secure=not settings.debug,  # HTTPS only in production
            samesite="lax",
            max_age=settings.access_token_expire_minutes * 60,
        )
        return response
    except HTTPException as e:
        return templates.TemplateResponse(request, "auth/login.html", {
            "gym_name": _get_gym_name(),
            "error":    e.detail,
        }, status_code=400)


# ── LOGOUT ───────────────────────────────────────────────────────────────────

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie("access_token")
    return response


# ── FORGOT PASSWORD ──────────────────────────────────────────────────────────

@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(request, "auth/forgot_password.html", {
        "gym_name": _get_gym_name(),
        "error":    request.query_params.get("error"),
    })


@router.post("/forgot-password")
async def forgot_password_post(
    request:    Request,
    identifier: str = Form(...),
):
    try:
        user = AuthService.find_user_by_identifier(identifier)
        otp  = AuthService.create_and_store_otp(user["id"])

        try:
            EmailService.send_password_reset_otp(user["email"], otp, user.get("name"))
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Failed to send OTP email. Please check the mail server configuration and try again.",
            )

        return RedirectResponse(
            url=f"/auth/otp-verify?user_id={user['id']}&email={user['email']}",
            status_code=302,
        )
    except HTTPException as e:
        return templates.TemplateResponse(request, "auth/forgot_password.html", {
            "gym_name": _get_gym_name(),
            "error":    e.detail,
        }, status_code=400)


# ── OTP VERIFY ───────────────────────────────────────────────────────────────

@router.get("/otp-verify", response_class=HTMLResponse)
async def otp_verify_page(request: Request, user_id: str, email: str):
    return templates.TemplateResponse(request, "auth/otp_verify.html", {
        "gym_name": _get_gym_name(),
        "user_id":  user_id,
        "email":    email,
        "error":    request.query_params.get("error"),
    })


@router.post("/otp-verify")
async def otp_verify_post(
    request: Request,
    user_id: str = Form(...),
    email:   str = Form(...),
    otp:     str = Form(...),
):
    try:
        otp_id = AuthService.verify_otp(user_id, otp.strip())
        return RedirectResponse(
            url=f"/auth/reset-password?user_id={user_id}&otp_id={otp_id}",
            status_code=302,
        )
    except HTTPException as e:
        return templates.TemplateResponse(request, "auth/otp_verify.html", {
            "gym_name": _get_gym_name(),
            "user_id":  user_id,
            "email":    email,
            "error":    e.detail,
        }, status_code=400)


@router.post("/resend-otp")
async def resend_otp(
    request: Request,
    user_id: str = Form(...),
    email:   str = Form(...),
):
    """Resend OTP — called by the 'Resend code' button."""
    try:
        otp = AuthService.create_and_store_otp(user_id)
        try:
            EmailService.send_password_reset_otp(email, otp)
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Failed to resend OTP email. Please check the mail server configuration and try again.",
            )
        return RedirectResponse(
            url=f"/auth/otp-verify?user_id={user_id}&email={email}&resent=1",
            status_code=302,
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/auth/otp-verify?user_id={user_id}&email={email}&error={e.detail}",
            status_code=302,
        )


# ── RESET PASSWORD ───────────────────────────────────────────────────────────

@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, user_id: str, otp_id: str):
    return templates.TemplateResponse(request, "auth/reset_password.html", {
        "gym_name": _get_gym_name(),
        "user_id":  user_id,
        "otp_id":   otp_id,
        "error":    request.query_params.get("error"),
    })


@router.post("/reset-password")
async def reset_password_post(
    request:          Request,
    user_id:          str = Form(...),
    otp_id:           str = Form(...),
    new_password:     str = Form(...),
    confirm_password: str = Form(...),
):
    if new_password != confirm_password:
        return templates.TemplateResponse(request, "auth/reset_password.html", {
            "gym_name": _get_gym_name(),
            "user_id":  user_id,
            "otp_id":   otp_id,
            "error":    "Passwords do not match.",
        }, status_code=400)

    try:
        AuthService.reset_password(user_id, otp_id, new_password)
        return RedirectResponse(
            url="/auth/login?success=Password+updated+successfully",
            status_code=302,
        )
    except HTTPException as e:
        return templates.TemplateResponse(request, "auth/reset_password.html", {
            "gym_name": _get_gym_name(),
            "user_id":  user_id,
            "otp_id":   otp_id,
            "error":    e.detail,
        }, status_code=400)
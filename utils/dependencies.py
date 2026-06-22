from fastapi import Cookie, Request, HTTPException, status, Depends
from fastapi.responses import RedirectResponse
from typing import Optional

from services.auth_service import decode_access_token
from services.user_service import UserService, RoleService


async def get_current_user(
    request: Request,
    access_token: Optional[str] = Cookie(default=None),
) -> dict:
    """
    Reads JWT from HTTP-only cookie.
    - Full page requests  → redirect to /auth/login
    - HTMX partial requests → return 401 JSON
    """
    if not access_token:
        if request.headers.get("HX-Request"):
            raise HTTPException(status_code=401, detail="Not authenticated")
        raise HTTPException(
            status_code=302,
            headers={"Location": "/auth/login"},
        )

    try:
        payload = decode_access_token(access_token)
    except HTTPException:
        if request.headers.get("HX-Request"):
            raise HTTPException(status_code=401, detail="Session expired")
        raise HTTPException(
            status_code=302,
            headers={"Location": "/auth/login?error=Session+expired"},
        )

    # Try to load additional user fields (like `photo_url`) from DB
    try:
        db_user = UserService.get_by_id(payload.get("sub"))
    except HTTPException:
        if request.headers.get("HX-Request"):
            raise HTTPException(status_code=401, detail="Session expired")
        raise HTTPException(
            status_code=302,
            headers={"Location": "/auth/login?error=Session+expired"},
        )

    # fetch role permissions to expose to templates (as 'module:action' strings)
    try:
        perms = RoleService.get_permissions_for_role(payload.get("role"))
    except Exception:
        perms = []

    role_name = (payload.get("role") or "").strip()
    normalized_role = role_name.lower().replace("_", " ").replace("-", " ")
    full_access = normalized_role in {"admin", "super admin", "superadmin", "super user", "superuser", "super-user"}

    return {
        "id":           payload.get("sub"),
        "role":         role_name,
        "name":         payload.get("name"),
        "email":        payload.get("email"),
        "photo_url":    db_user.get("photo_url") if db_user else None,
        "permissions":  perms,
        "is_superuser": full_access,
    }


def require_role(*roles: str):
    """
    Dependency factory — restricts route to specific roles.
    Usage: Depends(require_role("admin", "manager"))
    """
    async def _check(current_user: dict = Depends(get_current_user)):
        if not current_user.get("is_superuser") and current_user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to access this page.",
            )
        return current_user
    return _check
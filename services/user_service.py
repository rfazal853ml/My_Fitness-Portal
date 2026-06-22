import secrets
import string
from typing import Optional

from fastapi import HTTPException, status

from services.supabase_client import get_supabase
from services.auth_service import hash_password


# ── Helpers ───────────────────────────────────────────────────────────────────

def _generate_temp_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _build_role_permissions_map(role_data: list) -> list:
    """
    Transform raw role_permissions join into a clean dict per role:
    {
        "id": "...", "name": "admin",
        "permissions": { "members": ["view","edit","delete"], ... }
    }
    """
    result = []
    for role in role_data:
        perm_map: dict[str, list[str]] = {}
        perm_ids: list[str] = []
        for rp in role.get("role_permissions", []):
            p = rp.get("permissions")
            if p:
                module = p["module"]
                action = p["action"]
                # collect permission id for pre-selecting checkboxes
                if p.get("id"):
                    perm_ids.append(p["id"])
                perm_map.setdefault(module, []).append(action)
        result.append({
            "id":          role["id"],
            "name":        role["name"],
            "description": role.get("description", ""),
            "permissions": perm_map,
            "permission_ids": perm_ids,
        })
    return result


# ── User Service ─────────────────────────────────────────────────────────────

class UserService:

    # ── Stats ─────────────────────────────────────────────────────────────────

    @staticmethod
    def get_stats() -> dict:
        db = get_supabase()
        result = db.table("staff_users").select("is_active, roles(name)").execute()
        users = result.data or []

        total    = len(users)
        active   = sum(1 for u in users if u.get("is_active"))
        inactive = total - active
        managers = sum(
            1 for u in users
            if (u.get("roles") or {}).get("name") == "manager"
        )
        return {
            "total":    total,
            "active":   active,
            "inactive": inactive,
            "managers": managers,
        }

    # ── List Users ────────────────────────────────────────────────────────────

    @staticmethod
    def get_all(search: str = "") -> list:
        db = get_supabase()
        query = (
            db.table("staff_users")
            .select("id, name, email, phone, photo_url, cnic, address, is_active, last_login, role_id, roles(id, name)")
            .order("created_at", desc=True)
        )
        if search:
            query = query.ilike("name", f"%{search}%")
        return query.execute().data or []

    # ── Get Single User ───────────────────────────────────────────────────────

    @staticmethod
    def get_by_id(user_id: str) -> dict:
        db = get_supabase()
        result = (
            db.table("staff_users")
            .select("*, roles(id, name)")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="User not found.")
        return result.data

    # ── Create User ───────────────────────────────────────────────────────────

    @staticmethod
    def create(data: dict) -> dict:
        db = get_supabase()

        # Check duplicate email
        existing = (
            db.table("staff_users")
            .select("id")
            .eq("email", data["email"].lower().strip())
            .execute()
        )
        if existing.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email already exists.",
            )

        # Initial temp password (default for new accounts)
        temp_password = "123"

        payload = {
            "name":          data["name"].strip(),
            "email":         data["email"].lower().strip(),
            "phone":         data.get("phone", ""),
            "cnic":          data.get("cnic", "") or None,
            "address":       data.get("address", "") or None,
            "photo_url":     data.get("photo_url") or None,
            "role_id":       data["role_id"],
            "password_hash": hash_password(temp_password),
            "is_active":     True,
        }

        result = db.table("staff_users").insert(payload).execute()
        return {
            "user":          result.data[0],
            "temp_password": temp_password,
        }

    # ── Update User ───────────────────────────────────────────────────────────

    @staticmethod
    def update(user_id: str, data: dict) -> dict:
        db = get_supabase()

        # Remove None values so we don't overwrite with nulls
        payload = {k: v for k, v in data.items() if v is not None}

        result = (
            db.table("staff_users")
            .update(payload)
            .eq("id", user_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="User not found.")
        return result.data[0]

    # ── Toggle Active ──────────────────────────────────────────────────────────

    @staticmethod
    def toggle_active(user_id: str, current_status: bool) -> None:
        db = get_supabase()
        db.table("staff_users").update(
            {"is_active": not current_status}
        ).eq("id", user_id).execute()

    # ── Delete User ───────────────────────────────────────────────────────────

    @staticmethod
    def delete(user_id: str) -> None:
        db = get_supabase()
        db.table("staff_users").delete().eq("id", user_id).execute()

    # ── Reset Password ────────────────────────────────────────────────────────

    @staticmethod
    def reset_password(user_id: str) -> str:
        """Generate a new temp password and save it. Returns the plain password."""
        db = get_supabase()
        temp_password = _generate_temp_password()
        db.table("staff_users").update(
            {"password_hash": hash_password(temp_password)}
        ).eq("id", user_id).execute()
        return temp_password


# ── Role Service ─────────────────────────────────────────────────────────────

class RoleService:

    # ── List Roles ────────────────────────────────────────────────────────────

    @staticmethod
    def get_all(search: str = "") -> list:
        db = get_supabase()
        query = (
            db.table("roles")
            .select("id, name, description, role_permissions(permissions(id, module, action))")
            .order("created_at")
        )
        if search:
            query = query.ilike("name", f"%{search}%")
        result = query.execute()
        return _build_role_permissions_map(result.data or [])

    # ── Get All Permissions ───────────────────────────────────────────────────

    @staticmethod
    def get_all_permissions() -> list:
        db = get_supabase()
        result = (
            db.table("permissions")
            .select("id, module, action")
            .order("module")
            .execute()
        )
        return result.data or []

    # ── Create Role ───────────────────────────────────────────────────────────

    @staticmethod
    def create(name: str, description: str, permission_ids: list[str]) -> dict:
        db = get_supabase()

        # Check duplicate name
        existing = db.table("roles").select("id").eq("name", name.lower().strip()).execute()
        if existing.data:
            raise HTTPException(
                status_code=400,
                detail=f"A role named '{name}' already exists.",
            )

        role_result = db.table("roles").insert({
            "name":        name.lower().strip(),
            "description": description or "",
        }).execute()

        role = role_result.data[0]

        if permission_ids:
            perms = [{"role_id": role["id"], "permission_id": pid} for pid in permission_ids]
            db.table("role_permissions").insert(perms).execute()

        return role

    # ── Update Role ───────────────────────────────────────────────────────────

    @staticmethod
    def update(role_id: str, name: str, description: str, permission_ids: list[str]) -> None:
        db = get_supabase()

        db.table("roles").update({
            "name":        name.lower().strip(),
            "description": description or "",
        }).eq("id", role_id).execute()

        # Replace all permissions
        db.table("role_permissions").delete().eq("role_id", role_id).execute()

        if permission_ids:
            perms = [{"role_id": role_id, "permission_id": pid} for pid in permission_ids]
            db.table("role_permissions").insert(perms).execute()

    # ── Delete Role ───────────────────────────────────────────────────────────

    @staticmethod
    def delete(role_id: str) -> None:
        db = get_supabase()
        # Check if any users have this role
        users = db.table("staff_users").select("id").eq("role_id", role_id).execute()
        if users.data:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete a role that has users assigned to it.",
            )
        db.table("roles").delete().eq("id", role_id).execute()

    @staticmethod
    def get_permissions_for_role(role_name: str) -> list:
        """
        Return a list of permission strings like 'members:view' for the given role name.
        """
        if not role_name:
            return []
        db = get_supabase()
        result = (
            db.table("roles")
            .select("role_permissions(permissions(module, action))")
            .eq("name", role_name)
            .single()
            .execute()
        )
        data = result.data or {}
        perms = []
        for rp in data.get("role_permissions", []):
            p = rp.get("permissions")
            if p:
                perms.append(f"{p.get('module')}:{p.get('action')}")
        return perms
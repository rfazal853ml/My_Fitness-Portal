import random
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status

from config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password Utilities ───────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT ──────────────────────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload["exp"] = expire
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )


# ── OTP ──────────────────────────────────────────────────────────────────────

def generate_otp(length: int = 5) -> str:
    return "".join(random.choices(string.digits, k=length))


# ── Auth Service Class ───────────────────────────────────────────────────────

class AuthService:

    @staticmethod
    def get_db():
        from services.supabase_client import get_supabase
        return get_supabase()

    # ── Login ────────────────────────────────────────────────────────────────

    @staticmethod
    def login(email: str, password: str) -> dict:
        db = AuthService.get_db()

        result = (
            db.table("staff_users")
            .select("*, roles(name)")
            .eq("email", email.lower().strip())
            .eq("is_active", True)
            .single()
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        user = result.data

        if not verify_password(password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        # ── FIX: Update last_login timestamp ────────────────────────────────
        db.table("staff_users").update({
            "last_login": datetime.now(timezone.utc).isoformat()
        }).eq("id", user["id"]).execute()
        # ─────────────────────────────────────────────────────────────────────

        role_name = user["roles"]["name"] if user.get("roles") else "staff"

        token = create_access_token({
            "sub":   user["id"],
            "role":  role_name,
            "name":  user["name"],
            "email": user["email"],
        })

        return {"token": token, "user": user, "role": role_name}

    # ── Find User for Password Reset ─────────────────────────────────────────

    @staticmethod
    def find_user_by_identifier(identifier: str) -> dict:
        db = AuthService.get_db()
        identifier = identifier.strip()

        result = (
            db.table("staff_users")
            .select("id, name, email, phone, is_active")
            .eq("email", identifier)
            .eq("is_active", True)
            .execute()
        )

        if not result.data:
            result = (
                db.table("staff_users")
                .select("id, name, email, phone, is_active")
                .eq("phone", identifier)
                .eq("is_active", True)
                .execute()
            )

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active account found with that information.",
            )

        return result.data[0]

    # ── Send OTP ─────────────────────────────────────────────────────────────

    @staticmethod
    def create_and_store_otp(user_id: str) -> str:
        db = AuthService.get_db()
        otp = generate_otp()

        db.table("password_reset_otps").update({"used": True}).eq(
            "user_id", user_id
        ).eq("used", False).execute()

        db.table("password_reset_otps").insert({
            "user_id":    user_id,
            "otp":        hash_password(otp),
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=10)
            ).isoformat(),
            "used": False,
        }).execute()

        return otp

    # ── Verify OTP ───────────────────────────────────────────────────────────

    @staticmethod
    def verify_otp(user_id: str, plain_otp: str) -> str:
        db = AuthService.get_db()

        result = (
            db.table("password_reset_otps")
            .select("*")
            .eq("user_id", user_id)
            .eq("used", False)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OTP not found or already used.",
            )

        record = result.data[0]

        expires_at = datetime.fromisoformat(
            record["expires_at"].replace("Z", "+00:00")
        )
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OTP has expired. Please request a new one.",
            )

        if not verify_password(plain_otp, record["otp"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP. Please try again.",
            )

        return record["id"]

    # ── Reset Password ───────────────────────────────────────────────────────

    @staticmethod
    def reset_password(user_id: str, otp_id: str, new_password: str) -> None:
        db = AuthService.get_db()

        if len(new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters.",
            )

        db.table("password_reset_otps").update({"used": True}).eq(
            "id", otp_id
        ).execute()

        db.table("staff_users").update({
            "password_hash": hash_password(new_password),
        }).eq("id", user_id).execute()

    # ── Get Current User ─────────────────────────────────────────────────────

    @staticmethod
    def get_user_by_id(user_id: str) -> dict:
        db = AuthService.get_db()
        result = (
            db.table("staff_users")
            .select("*, roles(name)")
            .eq("id", user_id)
            .eq("is_active", True)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=401, detail="User not found.")
        return result.data
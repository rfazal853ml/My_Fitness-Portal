import json
from fastapi import HTTPException, status
from services.supabase_client import get_supabase


# ── Helpers ───────────────────────────────────────────────────────────────────

def duration_label(days: int) -> str:
    """Convert days to a human-readable label: 30 → 1 Month, 365 → 1 Year"""
    if days >= 365 and days % 365 == 0:
        y = days // 365
        return f"{y} Year{'s' if y > 1 else ''}"
    if days >= 30 and days % 30 == 0:
        m = days // 30
        return f"{m} Month{'s' if m > 1 else ''}"
    return f"{days} Day{'s' if days > 1 else ''}"


def duration_to_days(value: int, unit: str) -> int:
    """Convert duration input + unit to days."""
    unit = unit.lower()
    if unit == "years":
        return value * 365
    if unit == "months":
        return value * 30
    return value   # days


def pkr_format(amount: float) -> str:
    """Format as PKR 1,500"""
    return f"PKR {amount:,.0f}"


# ── Plan Service ──────────────────────────────────────────────────────────────

class PlanService:

    # ── Stats ─────────────────────────────────────────────────────────────────

    @staticmethod
    def get_stats() -> dict:
        db = get_supabase()
        result = db.table("plans").select("is_active, gender").execute()
        plans = result.data or []

        total    = len(plans)
        active   = sum(1 for p in plans if p.get("is_active"))
        inactive = total - active
        male     = sum(1 for p in plans if p.get("gender") in ("male", "any"))
        female   = sum(1 for p in plans if p.get("gender") in ("female", "any"))

        return {
            "total":    total,
            "active":   active,
            "inactive": inactive,
            "male":     male,
            "female":   female,
        }

    # ── List Plans ────────────────────────────────────────────────────────────

    @staticmethod
    def get_all(search: str = "", gender: str = "", status: str = "") -> list:
        db = get_supabase()
        query = (
            db.table("plans")
            .select("*")
            .order("created_at", desc=True)
        )
        if search:
            query = query.ilike("name", f"%{search}%")
        if gender and gender != "all":
            query = query.eq("gender", gender)
        if status == "active":
            query = query.eq("is_active", True)
        elif status == "inactive":
            query = query.eq("is_active", False)

        plans = query.execute().data or []

        # Attach display helpers
        for p in plans:
            p["duration_label"] = duration_label(p.get("duration_days", 0))
            p["price_display"]  = pkr_format(p.get("price", 0))
            # Ensure features is a list
            features = p.get("features") or []
            if isinstance(features, str):
                try:
                    features = json.loads(features)
                except Exception:
                    features = []
            p["features"] = features

            # Discounted price
            disc = p.get("discount_percent", 0) or 0
            if disc > 0:
                discounted = p.get("price", 0) * (1 - disc / 100)
                p["discounted_price"] = pkr_format(discounted)
            else:
                p["discounted_price"] = None

        return plans

    # ── Get Single ────────────────────────────────────────────────────────────

    @staticmethod
    def get_by_id(plan_id: str) -> dict:
        db = get_supabase()
        result = (
            db.table("plans")
            .select("*")
            .eq("id", plan_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Plan not found.")
        return result.data

    # ── Create ────────────────────────────────────────────────────────────────

    @staticmethod
    def create(data: dict) -> dict:
        db = get_supabase()

        # Check duplicate name
        existing = (
            db.table("plans")
            .select("id")
            .ilike("name", data["name"].strip())
            .execute()
        )
        if existing.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A plan named '{data['name']}' already exists.",
            )

        payload = {
            "name":             data["name"].strip(),
            "price":            float(data["price"]),
            "duration_days":    int(data["duration_days"]),
            "gender":           data.get("gender", "any"),
            "discount_percent": float(data.get("discount_percent") or 0),
            "features":         data.get("features", []),
            "is_active":        True,
        }

        result = db.table("plans").insert(payload).execute()
        return result.data[0]

    # ── Update ────────────────────────────────────────────────────────────────

    @staticmethod
    def update(plan_id: str, data: dict) -> dict:
        db = get_supabase()
        payload = {k: v for k, v in data.items() if v is not None}
        result = (
            db.table("plans")
            .update(payload)
            .eq("id", plan_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Plan not found.")
        return result.data[0]

    # ── Toggle Active ─────────────────────────────────────────────────────────

    @staticmethod
    def toggle_active(plan_id: str) -> bool:
        db = get_supabase()
        plan = PlanService.get_by_id(plan_id)
        new_status = not plan.get("is_active", True)
        db.table("plans").update({"is_active": new_status}).eq("id", plan_id).execute()
        return new_status

    # ── Delete ────────────────────────────────────────────────────────────────

    @staticmethod
    def delete(plan_id: str) -> None:
        db = get_supabase()

        # Check if any memberships use this plan
        used = (
            db.table("memberships")
            .select("id")
            .eq("plan_id", plan_id)
            .eq("status", "active")
            .execute()
        )
        if used.data:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete a plan with active memberships. Deactivate it instead.",
            )

        db.table("plans").delete().eq("id", plan_id).execute()
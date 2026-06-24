"""
Member Service — all business logic for gym members.
No raw DB calls allowed in routers; everything goes through here.
"""
import json
from datetime import datetime, timezone, date, timedelta
from typing import Optional

from fastapi import HTTPException, status

from services.supabase_client import get_supabase



# ── Formatters ────────────────────────────────────────────────────────────────

def _pkr(amount) -> str:
    try:
        return f"PKR {float(amount):,.0f}"
    except (TypeError, ValueError):
        return "PKR 0"


def _fmt_date(d) -> str:
    """Convert ISO string / date → dd/mm/yyyy."""
    if not d:
        return ""
    try:
        if isinstance(d, str):
            d = d[:10]
            dt = datetime.strptime(d, "%Y-%m-%d")
        else:
            dt = d
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(d)


# ── Fee Status ────────────────────────────────────────────────────────────────

def _fee_status(membership: dict | None) -> str:
    if not membership:
        return "unpaid"
    expiry = membership.get("end_date") or membership.get("expiry_date")
    if not expiry:
        return "unpaid"
    try:
        exp_date = datetime.strptime(str(expiry)[:10], "%Y-%m-%d").date()
        today = date.today()
        if exp_date < today:
            return "expired"
        # Check if last payment covers current period
        if membership.get("fee_paid"):
            return "paid"
        return "unpaid"
    except Exception:
        return "unpaid"


def _enrich_member(m: dict) -> dict:
    """Attach display helpers to a member row."""
    membership = (m.get("memberships") or [None])[0] if isinstance(m.get("memberships"), list) else m.get("memberships")
    if isinstance(membership, list):
        membership = membership[0] if membership else None

    m["membership"] = membership
    m["fee_status"] = _fee_status(membership)
    m["plan_name"] = (membership or {}).get("plans", {}).get("name", "—") if membership else "—"
    m["joining_date_fmt"] = _fmt_date(m.get("joining_date"))
    m["expiry_date_fmt"] = _fmt_date((membership or {}).get("expiry_date")) if membership else "—"
    # Health issues — ensure list
    hi = m.get("health_issues") or []
    if isinstance(hi, str):
        try:
            hi = json.loads(hi)
        except Exception:
            hi = [hi] if hi else []
    m["health_issues"] = hi
    return m


# ── Member Service ────────────────────────────────────────────────────────────

class MemberService:

    # ── Stats ─────────────────────────────────────────────────────────────────

    @staticmethod
    def get_stats() -> dict:
        db = get_supabase()
        members = db.table("members").select("status, gender").execute().data or []
        total  = len(members)
        active = sum(1 for m in members if m.get("status") == "active")
        male   = sum(1 for m in members if m.get("gender") == "male")
        female = sum(1 for m in members if m.get("gender") == "female")
        return {"total": total, "active": active, "male": male, "female": female}

    # ── List Members ──────────────────────────────────────────────────────────

    @staticmethod
    def get_all(
        search: str = "",
        plan_id: str = "",
        status: str = "",
        gender: str = "",
        page: int = 1,
        per_page: int = 15,
    ) -> dict:
        db = get_supabase()

        query = (
            db.table("members")
            .select(
                "*, "
                "memberships!memberships_member_id_fkey("
                "  *,"
                "  plans(id, name, price)"
                ")"
            )
            .order("created_at", desc=True)
        )

        if search:
            # Search by name, cnic, or phone
            query = query.or_(
                f"name.ilike.%{search}%,"
                f"cnic.ilike.%{search}%,"
                f"phone.ilike.%{search}%"
            )
        if gender and gender != "all":
            query = query.eq("gender", gender)
        if status == "active":
            query = query.eq("status", "active")
        elif status == "inactive":
            query = query.neq("status", "active")

        # Filter by active membership plan
        if plan_id and plan_id != "all":
            query = query.eq("memberships.plan_id", plan_id)

        offset = (page - 1) * per_page
        query = query.range(offset, offset + per_page - 1)

        result = query.execute()
        members = [_enrich_member(m) for m in (result.data or [])]

        # Total count (approximate — re-query without range)
        count_result = db.table("members").select("id", count="exact")
        if search:
            count_result = count_result.or_(
                f"name.ilike.%{search}%,"
                f"cnic.ilike.%{search}%,"
                f"phone.ilike.%{search}%"
            )
        if gender and gender != "all":
            count_result = count_result.eq("gender", gender)
        if status == "active":
            count_result = count_result.eq("status", "active")
        elif status == "inactive":
            count_result = count_result.neq("status", "active")

        total = count_result.execute().count or 0
        total_pages = max(1, (total + per_page - 1) // per_page)

        return {
            "members": members,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    # ── Get Single ────────────────────────────────────────────────────────────

    @staticmethod
    def get_by_id(member_id: str) -> dict:
        db = get_supabase()
        result = (
            db.table("members")
            .select(
                "*, "
                "memberships!memberships_member_id_fkey("
                "  *,"
                "  plans(id, name, price)"
                ")"
            )
            .eq("id", member_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Member not found.")
        return _enrich_member(result.data)

    # ── Check CNIC duplicate ──────────────────────────────────────────────────

    @staticmethod
    def check_cnic(cnic: str, exclude_id: str = "", cnic_type: str = "member") -> bool:
        """Returns True if a member/guardian CNIC already exists (excluding the given member id)."""
        db = get_supabase()
        field = "cnic" if cnic_type == "member" else "guardian_cnic"
        q = db.table("members").select("id").eq(field, cnic.strip())
        if exclude_id:
            q = q.neq("id", exclude_id)
        result = q.execute()
        return bool(result.data)

    # ── Create Member ─────────────────────────────────────────────────────────

    @staticmethod
    def create(data: dict) -> dict:
        db = get_supabase()

        # Duplicate CNIC check — map based on selected type
        raw_cnic_input = (data.get("cnic") or "").strip()
        cnic_type = (data.get("cnic_type") or "member").lower()
        if raw_cnic_input and MemberService.check_cnic(raw_cnic_input, cnic_type=cnic_type):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A member with this CNIC already exists.",
            )

        # Ensure health_issues is a list
        health_issues = data.get("health_issues") or []
        if isinstance(health_issues, str):
            try:
                health_issues = json.loads(health_issues)
            except Exception:
                health_issues = [health_issues] if health_issues else []

        # Map CNIC input into correct DB column depending on selection
        cnic_val = raw_cnic_input if raw_cnic_input else None
        payload = {
            "name":             (data.get("full_name") or "").strip(),
            "father_name":      (data.get("father_name") or "").strip() or None,
            "age":              data.get("age") or None,
            "cnic":             cnic_val if cnic_type == "member" else (data.get("cnic") if data.get("cnic") else None),
            "guardian_cnic":    cnic_val if cnic_type != "member" else (data.get("guardian_cnic") or None),
            "phone":            (data.get("phone") or "").strip(),
            "email":            (data.get("email") or "").strip() or None,
            "gender":           data.get("gender") or None,
            "blood_group":      data.get("blood_group") or None,
            "date_of_birth":    data.get("date_of_birth") or None,
            "joining_date":     data.get("joining_date") or date.today().isoformat(),
            "address":          data.get("address") or None,
            "emergency_contact": data.get("emergency_contact") or None,
            # Admission fee is recorded as a payment, not stored on members table
            "photo_url":        data.get("photo_url") or None,
            "status":           "active",
            "notes":            data.get("notes") or None,
            "registered_by":    data.get("registered_by") or None,
        }

        member_result = db.table("members").insert(payload).execute()
        member = member_result.data[0]

        # If an admission fee was provided, record it as a payment
        admission_fee = data.get("admission_fee")
        try:
            if admission_fee is not None and str(admission_fee).strip() != "":
                amount = float(admission_fee)
            else:
                amount = 0
        except Exception:
            amount = 0

        if amount and amount > 0:
            # Determine discount amount: explicit `discount` (amount) preferred,
            # otherwise compute from `discount_percent` if provided.
            discount_amount = 0
            try:
                discount_amount = float(data.get("discount") or 0)
            except Exception:
                discount_amount = 0
            if (not discount_amount) and data.get("discount_percent") is not None and str(data.get("discount_percent")).strip() != "":
                try:
                    percent = float(data.get("discount_percent"))
                    discount_amount = round(amount * percent / 100.0, 2)
                except Exception:
                    discount_amount = discount_amount

            payment_payload = {
                "member_id": member["id"],
                "amount": amount,
                "discount": discount_amount,
                "payment_method": data.get("payment_method") or "cash",
                "payment_date": data.get("payment_date") or date.today().isoformat(),
                "notes": data.get("payment_notes") or "Admission fee",
                "status": "paid",
            }
            db.table("payments").insert(payment_payload).execute()

        # Create membership if plan selected
        plan_id = data.get("plan_id")
        if plan_id:
            membership_payload = {
                "member_id":  member["id"],
                "plan_id":    plan_id,
                "start_date": data.get("membership_start") or date.today().isoformat(),
                "expiry_date": data.get("membership_expiry") or None,
                "status":     "active",
            }
            db.table("memberships").insert(membership_payload).execute()

        # Create note if provided
        note_title = (data.get("note_title") or "").strip()
        note_desc  = (data.get("note_description") or "").strip()
        if note_title or note_desc:
            db.table("member_notes").insert({
                "member_id":   member["id"],
                "title":       note_title,
                "description": note_desc,
            }).execute()

        return member

    # ── Update Member ─────────────────────────────────────────────────────────

    @staticmethod
    def update(member_id: str, data: dict) -> dict:
        db = get_supabase()

        # CNIC duplicate check (excluding self) — support cnic_type mapping
        raw_cnic_input = (data.get("cnic") or "").strip()
        cnic_type = (data.get("cnic_type") or "member").lower()
        if raw_cnic_input and MemberService.check_cnic(raw_cnic_input, exclude_id=member_id, cnic_type=cnic_type):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Another member with this CNIC already exists.",
            )

        # Health issues normalise
        health_issues = data.get("health_issues") or []
        if isinstance(health_issues, str):
            try:
                health_issues = json.loads(health_issues)
            except Exception:
                health_issues = [health_issues] if health_issues else []

        # Map is_active form field to status values
        status_val = None
        if "is_active" in data and data.get("is_active") is not None:
            status_val = "active" if data.get("is_active") in [True, "true", "True"] else "suspended"
        
        # Map CNIC input into correct DB column depending on selection
        cnic_val = raw_cnic_input if raw_cnic_input else None
        payload = {k: v for k, v in {
            "name":             (data.get("full_name") or "").strip() or None,
            "father_name":      (data.get("father_name") or "").strip() or None,
            "age":              data.get("age") or None,
            "cnic":             cnic_val if cnic_type == "member" else (data.get("cnic") or None),
            "phone":            (data.get("phone") or "").strip() or None,
            "email":            (data.get("email") or "").strip() or None,
            "gender":           data.get("gender") or None,
            "blood_group":      data.get("blood_group") or None,
            "date_of_birth":    data.get("date_of_birth") or None,
            "joining_date":     data.get("joining_date") or None,
            "address":          data.get("address") or None,
            "emergency_contact": data.get("emergency_contact") or None,
            "photo_url":        data.get("photo_url") or None,
            "status":           status_val,
            "notes":            data.get("notes") or None,
            "guardian_cnic":    cnic_val if cnic_type != "member" else (data.get("guardian_cnic") or None),
        }.items() if v is not None}
        # Always write health_issues (even empty list) — not filtered by the None check above
        payload["health_issues"] = health_issues

        result = (
            db.table("members")
            .update(payload)
            .eq("id", member_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Member not found.")

        # Update membership if plan provided
        plan_id = data.get("plan_id")
        if plan_id:
            # check existing active membership
            existing = (
                db.table("memberships")
                .select("id")
                .eq("member_id", member_id)
                .eq("status", "active")
                .execute()
            )
            membership_payload = {
                "plan_id":    plan_id,
                "start_date": data.get("membership_start") or date.today().isoformat(),
                "expiry_date": data.get("membership_expiry") or None,
                "status":     "active",
            }
            if existing.data:
                # Archive old one first if plan changed
                old = existing.data[0]
                db.table("memberships").update({"status": "expired"}).eq("id", old["id"]).execute()

            db.table("memberships").insert({
                "member_id": member_id,
                **membership_payload,
            }).execute()

        # Add note if provided
        note_title = (data.get("note_title") or "").strip()
        note_desc  = (data.get("note_description") or "").strip()
        if note_title or note_desc:
            db.table("member_notes").insert({
                "member_id":   member_id,
                "title":       note_title,
                "description": note_desc,
            }).execute()

        return result.data[0]

    # ── Toggle Active ─────────────────────────────────────────────────────────

    @staticmethod
    def toggle_active(member_id: str) -> str:
        db = get_supabase()
        member = MemberService.get_by_id(member_id)
        current_status = member.get("status", "active")
        new_status = "suspended" if current_status == "active" else "active"
        db.table("members").update({"status": new_status}).eq("id", member_id).execute()
        return new_status

    # ── Delete Member ─────────────────────────────────────────────────────────

    @staticmethod
    def delete(member_id: str) -> None:
        db = get_supabase()
        # Cascade: notes, memberships, attendance_logs are handled by DB FK or deleted manually
        db.table("member_notes").delete().eq("member_id", member_id).execute()
        db.table("memberships").delete().eq("member_id", member_id).execute()
        db.table("members").delete().eq("id", member_id).execute()

    # ── Profile data ──────────────────────────────────────────────────────────

    @staticmethod
    def get_attendance(member_id: str) -> dict:
        db = get_supabase()
        logs = (
            db.table("attendance_logs")
            .select("*")
            .eq("member_id", member_id)
            .order("check_in", desc=True)
            .execute()
        ).data or []

        total_visits = len(logs)
        # Attendance rate = present days / (days since joining)
        member = (
            db.table("members")
            .select("joining_date")
            .eq("id", member_id)
            .single()
            .execute()
        ).data or {}

        joining = member.get("joining_date")
        if joining:
            try:
                join_date = datetime.strptime(str(joining)[:10], "%Y-%m-%d").date()
                days_since = (date.today() - join_date).days or 1
                rate = round(min(total_visits / days_since * 100, 100), 1)
            except Exception:
                rate = 0
        else:
            rate = 0

        # Build a set of present dates
        present_dates = set()
        last_checkin = None
        avg_hour_sum = 0
        for log in logs:
            ci = log.get("check_in")
            if ci:
                ci_str = str(ci)[:10]
                present_dates.add(ci_str)
                if last_checkin is None:
                    last_checkin = ci
                try:
                    h = datetime.fromisoformat(ci.replace("Z", "+00:00")).hour
                    avg_hour_sum += h
                except Exception:
                    pass

        avg_checkin = ""
        if present_dates:
            avg_h = avg_hour_sum // len(logs)
            ampm = "AM" if avg_h < 12 else "PM"
            h12 = avg_h % 12 or 12
            avg_checkin = f"{h12:02d}:00 {ampm}"

        last_entry = ""
        if last_checkin:
            try:
                dt = datetime.fromisoformat(str(last_checkin).replace("Z", "+00:00"))
                last_entry = dt.strftime("%d %b %Y %I:%M %p")
            except Exception:
                last_entry = str(last_checkin)[:16]

        return {
            "logs": logs,
            "total_visits": total_visits,
            "attendance_rate": rate,
            "avg_checkin": avg_checkin,
            "present_dates": list(present_dates),
            "last_entry": last_entry,
        }

    @staticmethod
    def get_payments(member_id: str) -> list:
        db = get_supabase()
        result = (
            db.table("payments")
            .select("*, plans(name)")
            .eq("member_id", member_id)
            .order("created_at", desc=True)
            .execute()
        )
        payments = result.data or []
        for p in payments:
            p["amount_fmt"] = _pkr(p.get("amount"))
            p["date_fmt"] = _fmt_date(p.get("payment_date") or p.get("created_at"))
        return payments

    @staticmethod
    def get_memberships(member_id: str) -> dict:
        db = get_supabase()
        # Active membership
        active = (
            db.table("memberships")
            .select("*, plans(name, price)")
            .eq("member_id", member_id)
            .eq("status", "active")
            .order("start_date", desc=True)
            .limit(1)
            .execute()
        ).data or []
        current = active[0] if active else None
        if current:
            current["price_fmt"] = _pkr((current.get("plans") or {}).get("price", 0))
            current["end_date_fmt"] = _fmt_date(current.get("expiry_date"))

        # History (past + all)
        history = (
            db.table("memberships")
            .select("*, plans(name)")
            .eq("member_id", member_id)
            .order("start_date", desc=True)
            .execute()
        ).data or []
        for h in history:
            h["start_date_fmt"] = _fmt_date(h.get("start_date"))
            h["end_date_fmt"] = _fmt_date(h.get("expiry_date"))
            h["plan_name"] = (h.get("plans") or {}).get("name", "—")

        return {"current": current, "history": history}

    @staticmethod
    def get_notes(member_id: str) -> list:
        db = get_supabase()
        return (
            db.table("member_notes")
            .select("*")
            .eq("member_id", member_id)
            .order("created_at", desc=True)
            .execute()
        ).data or []

    @staticmethod
    def get_days_active(member_id: str) -> int:
        db = get_supabase()
        member = (
            db.table("members")
            .select("joining_date")
            .eq("id", member_id)
            .single()
            .execute()
        ).data or {}
        joining = member.get("joining_date")
        if not joining:
            return 0
        try:
            join_date = datetime.strptime(str(joining)[:10], "%Y-%m-%d").date()
            return (date.today() - join_date).days
        except Exception:
            return 0
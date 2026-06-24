"""
Member Service — all business logic for the Members module.
No raw DB calls outside this file; routers call these static methods only.
"""

import json
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException, status

from services.supabase_client import get_supabase


# ── Private helpers ────────────────────────────────────────────────────────────

def _fmt_date(val: Optional[str]) -> str:
    """ISO date → 'DD/MM/YYYY' for display."""
    if not val:
        return "—"
    try:
        d = datetime.strptime(str(val)[:10], "%Y-%m-%d")
        return d.strftime("%d/%m/%Y")
    except Exception:
        return str(val)


def _fee_status(membership: Optional[dict]) -> str:
    """Derive fee status from the active membership."""
    if not membership:
        return "unpaid"
    expiry = membership.get("expiry_date")
    if expiry:
        try:
            exp_date = datetime.strptime(str(expiry)[:10], "%Y-%m-%d").date()
            if exp_date < date.today():
                return "expired"
        except Exception:
            pass
    return "paid" if membership.get("status") == "active" else "unpaid"


def _enrich_member(m: dict) -> dict:
    """Attach derived fields to a raw member row."""
    # Pick the most recent active membership
    memberships = m.get("memberships") or []
    if isinstance(memberships, list):
        active = [ms for ms in memberships if ms.get("status") == "active"]
        membership = active[0] if active else (memberships[0] if memberships else None)
    else:
        membership = memberships or None

    m["membership"]       = membership
    m["fee_status"]       = _fee_status(membership)
    m["plan_name"]        = (membership or {}).get("plans", {}).get("name", "—") if membership else "—"
    m["plan_id_active"]   = (membership or {}).get("plan_id") if membership else None
    m["joining_date_fmt"] = _fmt_date(m.get("joining_date"))
    m["expiry_date_fmt"]  = _fmt_date((membership or {}).get("expiry_date")) if membership else "—"

    # Health issues — ensure list
    hi = m.get("health_issues") or []
    if isinstance(hi, str):
        try:
            hi = json.loads(hi)
        except Exception:
            hi = [hi] if hi else []
    m["health_issues"] = hi

    return m


# ── Member Service ─────────────────────────────────────────────────────────────

class MemberService:

    # ── Stats ──────────────────────────────────────────────────────────────────

    @staticmethod
    def get_stats() -> dict:
        db = get_supabase()
        members = db.table("members").select("status, gender").execute().data or []
        total   = len(members)
        active  = sum(1 for m in members if m.get("status") == "active")
        male    = sum(1 for m in members if m.get("gender") == "male")
        female  = sum(1 for m in members if m.get("gender") == "female")
        return {"total": total, "active": active, "male": male, "female": female}

    # ── List Members ───────────────────────────────────────────────────────────

    @staticmethod
    def get_all(
        search:   str = "",
        plan_id:  str = "",
        status:   str = "",
        gender:   str = "",
        page:     int = 1,
        per_page: int = 15,
    ) -> dict:
        db = get_supabase()

        query = (
            db.table("members")
            .select(
                "*, "
                "memberships!memberships_member_id_fkey("
                "  id, plan_id, start_date, expiry_date, status,"
                "  plans(id, name, price)"
                ")"
            )
            .order("created_at", desc=True)
        )

        if search:
            query = query.or_(
                f"name.ilike.%{search}%,"
                f"cnic.ilike.%{search}%,"
                f"phone.ilike.%{search}%"
            )
        if gender and gender != "all":
            query = query.eq("gender", gender)
        if status == "active":
            query = query.eq("status", "active")
        elif status in ("inactive", "suspended"):
            query = query.eq("status", status)

        offset = (page - 1) * per_page
        query  = query.range(offset, offset + per_page - 1)

        result  = query.execute()
        members = [_enrich_member(m) for m in (result.data or [])]

        # Total count (re-query without range)
        count_q = db.table("members").select("id", count="exact")
        if search:
            count_q = count_q.or_(
                f"name.ilike.%{search}%,"
                f"cnic.ilike.%{search}%,"
                f"phone.ilike.%{search}%"
            )
        if gender and gender != "all":
            count_q = count_q.eq("gender", gender)
        if status == "active":
            count_q = count_q.eq("status", "active")
        elif status in ("inactive", "suspended"):
            count_q = count_q.eq("status", status)

        total       = count_q.execute().count or 0
        total_pages = max(1, (total + per_page - 1) // per_page)

        return {
            "members":     members,
            "total":       total,
            "page":        page,
            "per_page":    per_page,
            "total_pages": total_pages,
        }

    # ── Get Single ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_by_id(member_id: str) -> dict:
        db = get_supabase()
        result = (
            db.table("members")
            .select(
                "*, "
                "memberships!memberships_member_id_fkey("
                "  id, plan_id, start_date, expiry_date, status,"
                "  plans(id, name, price)"
                ")"
            )
            .eq("id", member_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Member not found.")

        member = _enrich_member(result.data)

        # Attach biometric enrollment status from biometric_enrollments table
        try:
            bio = (
                db.table("biometric_enrollments")
                .select("fingerprint_status, face_status")
                .eq("member_id", member_id)
                .limit(1)
                .execute()
            ).data
            if bio:
                member["biometric_enrolled"] = (
                    bio[0].get("fingerprint_status") == "enrolled"
                    or bio[0].get("face_status") == "enrolled"
                )
            else:
                member["biometric_enrolled"] = False
        except Exception:
            member["biometric_enrolled"] = False

        return member

    # ── Check CNIC duplicate ───────────────────────────────────────────────────

    @staticmethod
    def check_cnic(cnic: str, exclude_id: str = "", cnic_type: str = "member") -> bool:
        """Returns True if CNIC already used (excluding the given member id)."""
        db    = get_supabase()
        field = "cnic" if cnic_type == "member" else "guardian_cnic"
        q     = db.table("members").select("id").eq(field, cnic.strip())
        if exclude_id:
            q = q.neq("id", exclude_id)
        return bool(q.execute().data)

    # ── Create Member ──────────────────────────────────────────────────────────

    @staticmethod
    def create(data: dict) -> dict:
        db = get_supabase()

        raw_cnic   = (data.get("cnic") or "").strip()
        cnic_type  = (data.get("cnic_type") or "member").lower()

        # Duplicate CNIC check
        if raw_cnic and MemberService.check_cnic(raw_cnic, cnic_type=cnic_type):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A member with this CNIC already exists.",
            )

        # Health issues — ensure list
        health_issues = data.get("health_issues") or []
        if isinstance(health_issues, str):
            try:
                health_issues = json.loads(health_issues)
            except Exception:
                health_issues = [health_issues] if health_issues else []

        # Map CNIC into correct column based on type
        member_cnic   = raw_cnic if cnic_type == "member" else None
        guardian_cnic = raw_cnic if cnic_type == "guardian" else (data.get("guardian_cnic") or None)

        payload = {
            "name":             (data.get("full_name") or "").strip(),
            "father_name":      (data.get("father_name") or "").strip() or None,
            "age":              data.get("age") or None,
            "date_of_birth":    data.get("date_of_birth") or None,
            "cnic":             member_cnic,
            "guardian_cnic":    guardian_cnic,
            "phone":            (data.get("phone") or "").strip(),
            "email":            (data.get("email") or "").strip() or None,
            "gender":           data.get("gender") or None,
            "blood_group":      data.get("blood_group") or None,
            "joining_date":     data.get("joining_date") or date.today().isoformat(),
            "address":          data.get("address") or None,
            "health_issues":    health_issues,
            "photo_url":        data.get("photo_url") or None,
            "status":           "active",
            "registered_by":    data.get("registered_by") or None,
        }

        member_result = db.table("members").insert(payload).execute()
        member        = member_result.data[0]

        # Record admission fee as a payment
        try:
            admission_fee = float(data.get("admission_fee") or 0)
        except Exception:
            admission_fee = 0

        if admission_fee > 0:
            try:
                discount_pct    = float(data.get("discount_percent") or 0)
                discount_amount = round(admission_fee * discount_pct / 100, 2)
            except Exception:
                discount_amount = 0

            db.table("payments").insert({
                "member_id":      member["id"],
                "amount":         admission_fee,
                "discount":       discount_amount,
                "payment_method": data.get("payment_method") or "cash",
                "payment_date":   data.get("joining_date") or date.today().isoformat(),
                "notes":          "Admission fee",
                "status":         "paid",
            }).execute()

        # Create membership if plan selected
        plan_id = data.get("plan_id")
        if plan_id:
            start_iso  = data.get("membership_start") or date.today().isoformat()
            expiry_iso = data.get("membership_expiry")
            if not expiry_iso:
                # expiry_date is NOT NULL — calculate from plan duration_days
                try:
                    plan_row = get_supabase().table("plans").select("duration_days").eq("id", plan_id).single().execute()
                    dur_days = (plan_row.data or {}).get("duration_days") or 30
                except Exception:
                    dur_days = 30
                from datetime import timedelta
                start_d    = datetime.strptime(start_iso[:10], "%Y-%m-%d").date()
                expiry_iso = (start_d + timedelta(days=int(dur_days))).isoformat()

            db.table("memberships").insert({
                "member_id":   member["id"],
                "plan_id":     plan_id,
                "start_date":  start_iso,
                "expiry_date": expiry_iso,
                "status":      "active",
            }).execute()

        # Create note if provided
        note_title = (data.get("note_title") or "").strip()
        note_desc  = (data.get("note_description") or "").strip()
        if note_title or note_desc:
            db.table("member_notes").insert({
                "member_id":   member["id"],
                "note":        note_title,       # DB column: 'note' (not 'title')
                "description": note_desc,
            }).execute()

        return member

    # ── Update Member ──────────────────────────────────────────────────────────

    @staticmethod
    def update(member_id: str, data: dict) -> dict:
        db = get_supabase()

        raw_cnic  = (data.get("cnic") or "").strip()
        cnic_type = (data.get("cnic_type") or "member").lower()

        # Duplicate CNIC check (excluding self)
        if raw_cnic and MemberService.check_cnic(raw_cnic, exclude_id=member_id, cnic_type=cnic_type):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Another member with this CNIC already exists.",
            )

        # Health issues — ensure list
        health_issues = data.get("health_issues") or []
        if isinstance(health_issues, str):
            try:
                health_issues = json.loads(health_issues)
            except Exception:
                health_issues = [health_issues] if health_issues else []

        member_cnic   = raw_cnic if cnic_type == "member" else None
        guardian_cnic = raw_cnic if cnic_type == "guardian" else (data.get("guardian_cnic") or None)

        payload = {
            "name":          (data.get("full_name") or "").strip(),
            "father_name":   (data.get("father_name") or "").strip() or None,
            "age":           data.get("age") or None,
            "date_of_birth": data.get("date_of_birth") or None,
            "cnic":          member_cnic,
            "guardian_cnic": guardian_cnic,
            "phone":         (data.get("phone") or "").strip(),
            "email":         (data.get("email") or "").strip() or None,
            "gender":        data.get("gender") or None,
            "blood_group":   data.get("blood_group") or None,
            "joining_date":  data.get("joining_date") or None,
            "address":       data.get("address") or None,
            "health_issues": health_issues,
        }

        # Only update photo_url if a new one was uploaded
        if data.get("photo_url"):
            payload["photo_url"] = data["photo_url"]

        # Remove None values to avoid overwriting with nulls unintentionally
        payload = {k: v for k, v in payload.items() if v is not None}

        result = db.table("members").update(payload).eq("id", member_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Member not found.")

        # Update membership if plan provided
        plan_id = data.get("plan_id")
        if plan_id:
            start_iso  = data.get("membership_start") or date.today().isoformat()
            expiry_iso = data.get("membership_expiry")
            if not expiry_iso:
                try:
                    plan_row = get_supabase().table("plans").select("duration_days").eq("id", plan_id).single().execute()
                    dur_days = (plan_row.data or {}).get("duration_days") or 30
                except Exception:
                    dur_days = 30
                from datetime import timedelta
                start_d    = datetime.strptime(start_iso[:10], "%Y-%m-%d").date()
                expiry_iso = (start_d + timedelta(days=int(dur_days))).isoformat()

            existing = (
                db.table("memberships")
                .select("id, plan_id")
                .eq("member_id", member_id)
                .eq("status", "active")
                .execute()
            )
            membership_payload = {
                "plan_id":     plan_id,
                "start_date":  start_iso,
                "expiry_date": expiry_iso,
                "status":      "active",
            }
            if existing.data:
                old = existing.data[0]
                if old.get("plan_id") != plan_id:
                    db.table("memberships").update({"status": "expired"}).eq("id", old["id"]).execute()
                    db.table("memberships").insert({"member_id": member_id, **membership_payload}).execute()
                else:
                    db.table("memberships").update({
                        "start_date":  membership_payload["start_date"],
                        "expiry_date": membership_payload["expiry_date"],
                    }).eq("id", old["id"]).execute()
            else:
                db.table("memberships").insert({"member_id": member_id, **membership_payload}).execute()

        return result.data[0]

    # ── Toggle Active / Suspended ──────────────────────────────────────────────

    @staticmethod
    def toggle_active(member_id: str) -> str:
        db     = get_supabase()
        member = MemberService.get_by_id(member_id)
        cur    = member.get("status", "active")
        nxt    = "suspended" if cur == "active" else "active"
        db.table("members").update({"status": nxt}).eq("id", member_id).execute()
        return nxt

    # ── Delete Member ──────────────────────────────────────────────────────────

    @staticmethod
    def delete(member_id: str) -> None:
        db = get_supabase()
        # Delete all FK-dependent rows first (cascade may not be configured)
        db.table("member_notes").delete().eq("member_id", member_id).execute()
        db.table("biometric_enrollments").delete().eq("member_id", member_id).execute()
        db.table("attendance_logs").delete().eq("member_id", member_id).execute()
        db.table("payments").delete().eq("member_id", member_id).execute()
        db.table("memberships").delete().eq("member_id", member_id).execute()
        db.table("members").delete().eq("id", member_id).execute()

    # ── Add Note ───────────────────────────────────────────────────────────────

    @staticmethod
    def add_note(member_id: str, title: str, description: str) -> dict:
        db     = get_supabase()
        result = db.table("member_notes").insert({
            "member_id":   member_id,
            "note":        title.strip(),        # DB column is 'note', not 'title'
            "description": description.strip(),
        }).execute()
        return result.data[0] if result.data else {}

    # ── Profile: Days Active ───────────────────────────────────────────────────

    @staticmethod
    def get_days_active(member_id: str) -> int:
        db     = get_supabase()
        result = (
            db.table("members")
            .select("joining_date")
            .eq("id", member_id)
            .single()
            .execute()
        )
        joining = (result.data or {}).get("joining_date")
        if not joining:
            return 0
        try:
            join_date = datetime.strptime(str(joining)[:10], "%Y-%m-%d").date()
            return (date.today() - join_date).days
        except Exception:
            return 0

    # ── Profile: Attendance ────────────────────────────────────────────────────

    @staticmethod
    def get_attendance(member_id: str) -> dict:
        db   = get_supabase()
        # DB column: check_in_at (NOT check_in)
        logs = (
            db.table("attendance_logs")
            .select("check_in_at, check_out_at, access_granted")
            .eq("member_id", member_id)
            .eq("access_granted", True)          # only successful entries
            .order("check_in_at", desc=True)
            .execute()
        ).data or []

        total_visits = len(logs)

        # Days since joining
        member    = (
            db.table("members").select("joining_date").eq("id", member_id).single().execute()
        ).data or {}
        joining   = member.get("joining_date")
        days_rate = 1

        if joining:
            try:
                join_date = datetime.strptime(str(joining)[:10], "%Y-%m-%d").date()
                days_rate = (date.today() - join_date).days or 1
            except Exception:
                pass

        rate = round(min(total_visits / days_rate * 100, 100), 1)

        # Present date set + last check-in + avg check-in hour
        present_dates = set()
        last_entry    = None
        total_hour    = 0
        hour_count    = 0

        for log in logs:
            ci = log.get("check_in_at")          # DB column: check_in_at
            if ci:
                try:
                    dt = datetime.fromisoformat(str(ci).replace("Z", "+00:00"))
                    present_dates.add(dt.date().isoformat())
                    if last_entry is None:
                        last_entry = dt.strftime("%I:%M %p")
                    total_hour += dt.hour + dt.minute / 60
                    hour_count += 1
                except Exception:
                    pass

        # Average check-in time
        avg_checkin = "—"
        if hour_count:
            avg_h  = total_hour / hour_count
            hh     = int(avg_h)
            mm     = int((avg_h - hh) * 60)
            suffix = "AM" if hh < 12 else "PM"
            hh12   = hh % 12 or 12
            avg_checkin = f"{hh12:02d}:{mm:02d} {suffix}"

        return {
            "total_visits":    total_visits,
            "attendance_rate": rate,
            "last_entry":      last_entry or "—",
            "avg_checkin":     avg_checkin,
            "present_dates":   sorted(present_dates),
        }

    # ── Profile: Payments ──────────────────────────────────────────────────────

    @staticmethod
    def get_payments(member_id: str) -> list:
        db     = get_supabase()
        # Join memberships → plans to get plan name; DB column is receipt_no not receipt_number
        result = (
            db.table("payments")
            .select("id, receipt_no, payment_date, payment_method, amount, discount, status, notes, memberships(plans(name))")
            .eq("member_id", member_id)
            .order("payment_date", desc=True)
            .execute()
        )
        rows = result.data or []
        out  = []
        for i, r in enumerate(rows, start=1):
            # Resolve plan name from join: payments → memberships → plans
            membership = r.get("memberships") or {}
            if isinstance(membership, list):
                membership = membership[0] if membership else {}
            plan      = membership.get("plans") or {} if membership else {}
            plan_name = plan.get("name") or r.get("notes") or "—"

            out.append({
                "id":          r.get("id"),
                "receipt":     r.get("receipt_no") or f"RCP-{str(i).zfill(4)}",  # receipt_no
                "date":        _fmt_date(r.get("payment_date")),
                "plan":        plan_name.capitalize() if plan_name != "—" else "—",
                "method":      (r.get("payment_method") or "cash").replace("_", " ").title(),
                "amount":      f"PKR {int(float(r.get('amount') or 0)):,}",
                "amount_raw":  float(r.get("amount") or 0),
                "status":      r.get("status") or "paid",
            })
        return out

    # ── Profile: Memberships ───────────────────────────────────────────────────

    @staticmethod
    def get_memberships(member_id: str) -> dict:
        db     = get_supabase()
        result = (
            db.table("memberships")
            .select("*, plans(id, name, price)")
            .eq("member_id", member_id)
            .order("start_date", desc=True)
            .execute()
        )
        rows    = result.data or []
        current = None
        history = []

        for r in rows:
            plan  = r.get("plans") or {}
            entry = {
                "id":          r.get("id"),
                "plan_name":   plan.get("name") or "—",
                "price":       f"PKR {int(float(plan.get('price') or 0)):,}",
                "start_date":  _fmt_date(r.get("start_date")),
                "expiry_date": _fmt_date(r.get("expiry_date")),
                "status":      r.get("status") or "active",
            }
            if r.get("status") == "active" and current is None:
                current = entry
            else:
                history.append(entry)

        return {"current": current, "history": history}

    # ── Profile: Notes ─────────────────────────────────────────────────────────

    @staticmethod
    def get_notes(member_id: str) -> list:
        db     = get_supabase()
        result = (
            db.table("member_notes")
            .select("id, note, description, created_at")
            .eq("member_id", member_id)
            .order("created_at", desc=True)
            .execute()
        )
        rows = result.data or []
        out  = []
        for r in rows:
            out.append({
                "id":          r.get("id"),
                "title":       r.get("note") or "—",    # DB column: 'note' (not 'title')
                "description": r.get("description") or "",
                "created_at":  _fmt_date(r.get("created_at")),
            })
        return out
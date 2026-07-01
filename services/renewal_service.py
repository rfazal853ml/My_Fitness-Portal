"""
Renewal Service — Membership Renewals module business logic.
No raw DB calls outside this file; routers call these static methods only.

Design notes:
- No dedicated 'renewal_logs' table. History is DERIVED from `memberships`
  rows that have `previous_plan_id` set (i.e. created via a renewal action),
  joined with their corresponding `payments` row.
- "Dues" = sum of `payments.amount - payments.discount` where status='pending'
  for the member's CURRENT active membership.
- Status bucket:
    expired        -> expiry_date < today
    expiring_soon  -> 0 <= days_left <= 7
    active         -> days_left > 7
"""

from enum import member
import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status
from schemas import member

from services.supabase_client import get_supabase


# ── Private helpers ────────────────────────────────────────────────────────────

def _fmt_date(val: Optional[str]) -> str:
    if not val:
        return "—"
    try:
        d = datetime.strptime(str(val)[:10], "%Y-%m-%d")
        return d.strftime("%d/%m/%Y")
    except Exception:
        return str(val)


def _days_and_status(expiry_iso: Optional[str]) -> dict:
    """Returns {days, status, days_label} based on expiry date vs today."""
    if not expiry_iso:
        return {"days": 0, "status": "expired", "days_label": "—"}

    try:
        exp = datetime.strptime(str(expiry_iso)[:10], "%Y-%m-%d").date()
    except Exception:
        return {"days": 0, "status": "expired", "days_label": "—"}

    delta = (exp - date.today()).days

    if delta < 0:
        return {
            "days":       abs(delta),
            "status":     "expired",
            "days_label": f"{abs(delta)} days Expired",
        }
    elif delta <= 7:
        return {
            "days":       delta,
            "status":     "expiring_soon",
            "days_label": f"{delta} days left",
        }
    else:
        return {
            "days":       delta,
            "status":     "active",
            "days_label": f"{delta} days left",
        }


def _pkr(val) -> str:
    try:
        return f"PKR {int(round(float(val))):,}"
    except Exception:
        return "PKR 0"


# ── Renewal Service ────────────────────────────────────────────────────────────

class RenewalService:

    # ── Stats (for top cards, if used) ───────────────────────────────────────

    @staticmethod
    def get_stats() -> dict:
        db = get_supabase()
        rows = (
            db.table("memberships")
            .select("expiry_date, status")
            .eq("status", "active")
            .execute()
        ).data or []

        expired = expiring_soon = active = 0
        for r in rows:
            bucket = _days_and_status(r.get("expiry_date"))["status"]
            if bucket == "expired":
                expired += 1
            elif bucket == "expiring_soon":
                expiring_soon += 1
            else:
                active += 1

        return {
            "total":          len(rows),
            "expired":        expired,
            "expiring_soon":  expiring_soon,
            "active":         active,
        }

    # ── List: Renewals Members tab ───────────────────────────────────────────

    @staticmethod
    def get_renewal_members(
        search:    str = "",
        days:      str = "",   # "" | "7" | "15" | "30" (expiring within N days, includes expired)
        status_f:  str = "",   # "" | "active" | "expiring_soon" | "expired"
        page:      int = 1,
        per_page:  int = 15,
    ) -> dict:
        db = get_supabase()

        # Pull all active memberships joined to member + plan
        query = (
            db.table("memberships")
            .select(
                "id, plan_id, start_date, expiry_date, status, member_id, "
                "plans!memberships_plan_id_fkey(id, name, price), "
                "members!memberships_member_id_fkey(id, name, phone, photo_url, status, cnic, email)"
            )
            .eq("status", "active")
            .order("expiry_date", desc=False)
        )

        result = query.execute()
        rows   = result.data or []

        items = []
        for r in rows:
            member = r.get("members") or {}
            plan   = r.get("plans") or {}
            if not member:
                continue

            if search:
                s = search.lower()
                if s not in (member.get("name") or "").lower() \
                   and s not in str(member.get("id") or "") \
                   and s not in (member.get("phone") or "") \
                   and s not in (member.get("cnic") or "").lower().replace("-", "") \
                   and s not in (member.get("email") or "").lower():
                    continue

            ds = _days_and_status(r.get("expiry_date"))

            if status_f and ds["status"] != status_f:
                continue

            if days:
                try:
                    max_days = int(days)
                    # Include already-expired + within N days window
                    if ds["status"] != "expired" and ds["days"] > max_days:
                        continue
                except Exception:
                    pass

            # Dues — pending payments tied to this membership
            member_id_for_dues = member.get("id") 

            dues_rows = (
                db.table("payments")
                .select("amount, discount, membership_id, notes")
                .eq("member_id", member_id_for_dues)
                .eq("status", "pending")
                .execute()
            ).data or []
            # Include: pending plan payment for THIS membership + pending admission fee (membership_id is null)
            dues_rows = [
                p for p in dues_rows
                if p.get("membership_id") == r.get("id") or p.get("notes") == "Admission fee"
            ]
            dues_total = sum(
                max(0, float(p.get("amount") or 0) - float(p.get("discount") or 0))
                for p in dues_rows
            )

            items.append({
                "membership_id":  r.get("id"),
                "member_id":      member.get("id"),
                "name":           member.get("name"),
                "phone":          member.get("phone"),
                "cnic":           member.get("cnic"),
                "email":          member.get("email"),
                "photo_url":      member.get("photo_url"),
                "member_status":  member.get("status"),
                "plan_id":        plan.get("id"),
                "plan_name":      plan.get("name") or "—",
                "plan_price":     float(plan.get("price") or 0),
                "start_date":     _fmt_date(r.get("start_date")),
                "expiry_date":    _fmt_date(r.get("expiry_date")),
                "expiry_date_raw": r.get("expiry_date"),
                "days":           ds["days"],
                "days_label":     ds["days_label"],
                "status":         ds["status"],
                "dues":           dues_total,
                "dues_label":     _pkr(dues_total) if dues_total > 0 else "—",
            })

        total = len(items)
        offset = (page - 1) * per_page
        paged  = items[offset: offset + per_page]
        total_pages = max(1, (total + per_page - 1) // per_page)

        return {
            "items":       paged,
            "total":       total,
            "page":        page,
            "per_page":    per_page,
            "total_pages": total_pages,
        }

    # ── Renewal detail (for modal) ───────────────────────────────────────────

    @staticmethod
    def get_renewal_detail(membership_id: str) -> dict:
        db = get_supabase()

        ms = (
            db.table("memberships")
            .select(
                "id, plan_id, start_date, expiry_date, status, member_id, "
                "plans!memberships_plan_id_fkey(id, name, price, duration_days, discount_percent), "
                "members!memberships_member_id_fkey(id, name, phone, email, photo_url, status)"
            )
            .eq("id", membership_id)
            .single()
            .execute()
        )
        if not ms.data:
            raise HTTPException(status_code=404, detail="Membership not found.")

        r      = ms.data
        member = r.get("members") or {}
        plan   = r.get("plans") or {}
        ds     = _days_and_status(r.get("expiry_date"))

        member_id_for_dues = member.get("id")   # in get_renewal_members; in get_renewal_detail use member.get("id") too

        dues_rows = (
            db.table("payments")
            .select("amount, discount, membership_id, notes")
            .eq("member_id", member_id_for_dues)
            .eq("status", "pending")
            .execute()
        ).data or []
        # Include: pending plan payment for THIS membership + pending admission fee (membership_id is null)
        dues_rows = [
            p for p in dues_rows
            if p.get("membership_id") == r.get("id") or p.get("notes") == "Admission fee"
        ]
        dues_total = sum(
            max(0, float(p.get("amount") or 0) - float(p.get("discount") or 0))
            for p in dues_rows
        )

        return {
            "membership_id":   r.get("id"),
            "member_id":       member.get("id"),
            "name":            member.get("name"),
            "phone":           member.get("phone"),
            "email":           member.get("email"),
            "photo_url":       member.get("photo_url"),
            "member_status":   member.get("status"),
            "cnic":            member.get("cnic"),
            "current_plan_id":   plan.get("id"),
            "current_plan_name": plan.get("name") or "—",
            "current_plan_price": float(plan.get("price") or 0),
            "current_plan_discount": float(plan.get("discount_percent") or 0),
            "current_plan_duration_days": int(plan.get("duration_days") or 30),
            "start_date":      _fmt_date(r.get("start_date")),
            "expiry_date":     _fmt_date(r.get("expiry_date")),
            "expiry_date_raw": r.get("expiry_date"),
            "days":            ds["days"],
            "days_label":      ds["days_label"],
            "status":          ds["status"],
            "dues":            dues_total,
            "dues_label":      _pkr(dues_total),
        }

    # ── Process Renewal ───────────────────────────────────────────────────────

    @staticmethod
    def renew(membership_id: str, data: dict) -> dict:
        """
        Expires the old membership, creates a new one referencing
        previous_plan_id (so it shows up in derived history), and
        inserts a payment row for the new period.
        """
        db = get_supabase()

        old = (
            db.table("memberships")
            .select("id, member_id, plan_id, status")
            .eq("id", membership_id)
            .single()
            .execute()
        )
        if not old.data:
            raise HTTPException(status_code=404, detail="Membership not found.")

        old_row       = old.data
        member_id     = old_row["member_id"]
        old_plan_id   = old_row["plan_id"]

        new_plan_id = data.get("new_plan_id") or old_plan_id
        plan_row = (
            db.table("plans")
            .select("id, name, price, duration_days, discount_percent")
            .eq("id", new_plan_id)
            .single()
            .execute()
        ).data or {}

        plan_price        = float(plan_row.get("price") or 0)
        plan_disc_pct     = float(plan_row.get("discount_percent") or 0)
        plan_duration     = int(plan_row.get("duration_days") or 30)

        # Duration override (e.g. renew Monthly plan for 3 months)
        duration_months = data.get("duration_months")
        if duration_months:
            try:
                duration_months = int(duration_months)
                multiplier = duration_months / max(1, round(plan_duration / 30))
                total_days = int(plan_duration * multiplier)
            except Exception:
                total_days = plan_duration
        else:
            total_days = plan_duration

        start_iso = data.get("start_date") or date.today().isoformat()
        try:
            start_d = datetime.strptime(start_iso[:10], "%Y-%m-%d").date()
        except Exception:
            start_d = date.today()
        expiry_iso = data.get("expiry_date") or (start_d + timedelta(days=total_days)).isoformat()

        # Pricing — scale by duration, apply plan discount then extra discount
        scale          = total_days / max(1, plan_duration)
        scaled_price   = plan_price * scale
        after_plan_disc = scaled_price * (1 - plan_disc_pct / 100)

        extra_disc_pct = float(data.get("extra_discount_percent") or 0)
        final_amount   = round(after_plan_disc * (1 - extra_disc_pct / 100), 2)
        discount_amt   = round(scaled_price - final_amount, 2)

        skip_dues = bool(data.get("skip_dues"))

        # 1) Expire old membership
        db.table("memberships").update({"status": "expired"}).eq("id", membership_id).execute()

        # 2) Archive to past_memberships (existing table)
        try:
            db.table("past_memberships").insert({
                "plan_id":     old_plan_id,
                "start_date":  old_row.get("start_date") if "start_date" in old_row else None,
                "expiry_date": old_row.get("expiry_date") if "expiry_date" in old_row else None,
                "status":      "expired",
                "member_id":   member_id,
            }).execute()
        except Exception:
            pass  # non-critical archival

        # 3) Create new membership row, tagging previous_plan_id for history derivation
        new_ms = db.table("memberships").insert({
            "member_id":        member_id,
            "plan_id":          new_plan_id,
            "previous_plan_id": old_plan_id,
            "start_date":       start_iso,
            "expiry_date":      expiry_iso,
            "status":           "active",
        }).execute()
        new_membership_id = new_ms.data[0]["id"] if new_ms.data else None

        # 4) Mark old dues resolved if skipping
        if skip_dues:
            db.table("payments").update({"status": "paid"}).eq(
                "membership_id", membership_id
            ).eq("status", "pending").execute()

        # 5) Insert renewal payment record (this row IS the renewal log entry)
        if new_membership_id:
            db.table("payments").insert({
                "member_id":      member_id,
                "membership_id":  new_membership_id,
                "amount":         scaled_price,
                "discount":       discount_amt,
                "payment_method": data.get("payment_method") or "cash",
                "payment_date":   start_iso,
                "notes":          "Renewal payment",
                "status":         data.get("payment_status") or "pending",
            }).execute()

        return {
            "new_membership_id": new_membership_id,
            "final_amount":      final_amount,
            "discount_amount":   discount_amt,
        }

    # ── List: Renewals History tab (derived) ─────────────────────────────────

    @staticmethod
    def get_renewal_history(search: str = "", page: int = 1, per_page: int = 15) -> dict:
        db = get_supabase()

        # Memberships created via a renewal action = previous_plan_id IS NOT NULL
        rows = (
            db.table("memberships")
            .select(
                "id, plan_id, previous_plan_id, start_date, expiry_date, created_at, member_id, "
                "plans!memberships_plan_id_fkey(id, name), "
                "members!memberships_member_id_fkey(id, name, phone, photo_url)"
            )
            .not_.is_("previous_plan_id", "null")
            .order("created_at", desc=True)
            .execute()
        ).data or []

        # Resolve previous plan names in one query
        prev_ids = list({r["previous_plan_id"] for r in rows if r.get("previous_plan_id")})
        prev_map = {}
        if prev_ids:
            prev_rows = db.table("plans").select("id, name").in_("id", prev_ids).execute().data or []
            prev_map  = {p["id"]: p["name"] for p in prev_rows}

        items = []
        for r in rows:
            member = r.get("members") or {}
            plan   = r.get("plans") or {}
            if not member:
                continue

            if search:
                s = search.lower()
                if s not in (member.get("name") or "").lower() and s not in str(member.get("id") or ""):
                    continue

            # Find the payment tied to this membership (the renewal payment)
            pay_rows = (
                db.table("payments")
                .select("amount, discount, payment_method, status")
                .eq("membership_id", r.get("id"))
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            ).data or []
            pay = pay_rows[0] if pay_rows else {}

            amount   = float(pay.get("amount") or 0)
            discount = float(pay.get("discount") or 0)
            final    = max(0, amount - discount)
            disc_pct = round((discount / amount) * 100) if amount > 0 else 0

            items.append({
                "membership_id":   r.get("id"),
                "member_id":       member.get("id"),
                "name":            member.get("name"),
                "phone":           member.get("phone"),
                "photo_url":       member.get("photo_url"),
                "previous_plan":   prev_map.get(r.get("previous_plan_id"), "—"),
                "new_plan":        plan.get("name") or "—",
                "expiry_date":     _fmt_date(r.get("expiry_date")),
                "amount":          amount,
                "amount_label":    _pkr(amount),
                "discount_pct":    disc_pct,
                "total_amount":    final,
                "total_label":     _pkr(final),
                "method":          (pay.get("payment_method") or "cash").replace("_", " ").title(),
                "payment_status":  pay.get("status") or "pending",
            })

        total       = len(items)
        offset      = (page - 1) * per_page
        paged       = items[offset: offset + per_page]
        total_pages = max(1, (total + per_page - 1) // per_page)

        return {
            "items":       paged,
            "total":       total,
            "page":        page,
            "per_page":    per_page,
            "total_pages": total_pages,
        }
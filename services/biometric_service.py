"""
Biometric Service — ZKTeco device management and biometric enrollment logic.

Architecture:
  - ZKTeco devices communicate via ADMS HTTP push protocol (same as server.py)
  - Device commands (add user, delete user) are queued in-memory
  - Incoming punches update biometric_enrollments + attendance_logs in Supabase
  - Verified=1  → fingerprint enrolled
  - Verified=15 → face enrolled
"""

from datetime import datetime
from typing import Optional

from fastapi import HTTPException

from services.supabase_client import get_supabase


# ── In-memory command queue ────────────────────────────────────────────────────
# { serial_number: ["C:101:DATA UPDATE user...", ...] }
# Populated by push_member / delete_member; consumed by /iclock/getrequest
_command_queue: dict[str, list[str]] = {}
_cmd_counter: int = 100

# ZKTeco Verified field → enrollment type
VERIFY_FINGERPRINT = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}  # 1–10 = fingerprint slots
VERIFY_FACE        = {"15"}
VERIFY_CARD        = {"20"}
VERIFY_PASSWORD    = {"0"}


def _next_cmd_id() -> int:
    global _cmd_counter
    _cmd_counter += 1
    return _cmd_counter


def _fmt_date(val: Optional[str]) -> str:
    if not val:
        return "—"
    try:
        d = datetime.strptime(str(val)[:10], "%Y-%m-%d")
        return d.strftime("%d/%m/%Y")
    except Exception:
        return str(val)


# ── Biometric Service ──────────────────────────────────────────────────────────

class BiometricService:

    # ── Device CRUD ───────────────────────────────────────────────────────────

    @staticmethod
    def get_all_devices() -> list:
        db   = get_supabase()
        rows = (
            db.table("zkteco_devices")
            .select("*")
            .order("created_at", desc=False)
            .execute()
        ).data or []

        out = []
        for r in rows:
            # Enrich with queue length so UI can show "X commands pending"
            sn            = r.get("serial_number") or ""
            pending_cmds  = len(_command_queue.get(sn, []))
            out.append({**r, "pending_commands": pending_cmds})
        return out

    @staticmethod
    def get_device(device_id: str) -> dict:
        db  = get_supabase()
        res = (
            db.table("zkteco_devices")
            .select("*")
            .eq("id", device_id)
            .single()
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Device not found.")
        return res.data

    @staticmethod
    def add_device(data: dict) -> dict:
        db  = get_supabase()
        res = db.table("zkteco_devices").insert({
            "name":          data["name"],
            "serial_number": (data.get("serial_number") or "").strip() or None,
            "ip_address":    data["ip_address"],
            "port":          int(data.get("port") or 4370),
            "location":      data.get("location") or None,
            "status":        "unknown",
        }).execute()
        return res.data[0] if res.data else {}

    @staticmethod
    def update_device(device_id: str, data: dict) -> dict:
        db  = get_supabase()
        res = db.table("zkteco_devices").update({
            "name":          data.get("name"),
            "serial_number": (data.get("serial_number") or "").strip() or None,
            "ip_address":    data.get("ip_address"),
            "port":          int(data.get("port") or 4370),
            "location":      data.get("location") or None,
        }).eq("id", device_id).execute()
        return res.data[0] if res.data else {}

    @staticmethod
    def delete_device(device_id: str) -> None:
        db = get_supabase()
        db.table("zkteco_devices").delete().eq("id", device_id).execute()

    @staticmethod
    def update_device_status(serial_number: str, status: str) -> None:
        """Called when device handshakes — mark it online."""
        db = get_supabase()
        db.table("zkteco_devices").update({
            "status":    status,
            "last_ping": datetime.utcnow().isoformat(),
        }).eq("serial_number", serial_number).execute()

    # ── Command Queue ─────────────────────────────────────────────────────────

    @staticmethod
    def get_all_serial_numbers() -> list[str]:
        db   = get_supabase()
        rows = (
            db.table("zkteco_devices")
            .select("serial_number")
            .not_.is_("serial_number", "null")
            .execute()
        ).data or []
        return [r["serial_number"] for r in rows if r.get("serial_number")]

    @staticmethod
    def push_member_to_all_devices(member_id: int, member_name: str) -> int:
        """
        Queue DATA UPDATE user command to every registered device.
        The device picks it up on its next /iclock/getrequest poll.
        Returns number of devices queued.
        """
        sns   = BiometricService.get_all_serial_numbers()
        count = 0
        for sn in sns:
            BiometricService._queue_add_user(sn, member_id, member_name)
            count += 1
        return count

    @staticmethod
    def push_member_to_device(serial_number: str, member_id: int, member_name: str) -> None:
        BiometricService._queue_add_user(serial_number, member_id, member_name)

    @staticmethod
    def _queue_add_user(sn: str, member_id: int, member_name: str) -> None:
        if sn not in _command_queue:
            _command_queue[sn] = []
        cid = _next_cmd_id()
        # Add user record so staff can enroll fingerprint/face on device directly
        _command_queue[sn].append(
            f"C:{cid}:DATA UPDATE user Pin={member_id}\tName={member_name}\tPri=0"
        )
        cid2 = _next_cmd_id()
        # Grant access on timezone 1, door 1
        _command_queue[sn].append(
            f"C:{cid2}:DATA UPDATE userauthorize Pin={member_id}\tAuthorizeTimezoneId=1\tAuthorizeDoorId=1"
        )

    @staticmethod
    def delete_member_from_all_devices(member_id: int) -> int:
        sns   = BiometricService.get_all_serial_numbers()
        count = 0
        for sn in sns:
            BiometricService._queue_delete_user(sn, member_id)
            count += 1
        return count

    @staticmethod
    def _queue_delete_user(sn: str, member_id: int) -> None:
        if sn not in _command_queue:
            _command_queue[sn] = []
        cid = _next_cmd_id()
        _command_queue[sn].append(f"C:{cid}:DATA DELETE user Pin={member_id}")

    @staticmethod
    def pop_next_command(serial_number: str) -> Optional[str]:
        """Called by /iclock/getrequest — dequeues and returns next command or None."""
        queue = _command_queue.get(serial_number, [])
        return queue.pop(0) if queue else None

    # ── Punch Processing (called from /iclock/cdata rtlog) ───────────────────

    @staticmethod
    def process_punch(serial_number: str, punch_data: dict) -> dict:
        """
        Parse a single rtlog punch event, update:
          - attendance_logs
          - biometric_enrollments (set enrolled on first successful scan)
        Returns enriched punch dict for WebSocket broadcast.
        """
        db = get_supabase()

        # ZKTeco sends Pin (uppercase P) or pin depending on firmware
        raw_pin   = punch_data.get("Pin") or punch_data.get("pin") or ""
        raw_time  = punch_data.get("DateTime") or punch_data.get("time") or ""
        raw_ver   = str(punch_data.get("Verified") or punch_data.get("verified") or "0").strip()

        # Determine verification type
        if raw_ver in VERIFY_FACE:
            verify_type = "face"
        elif raw_ver in VERIFY_CARD:
            verify_type = "card"
        elif raw_ver in VERIFY_PASSWORD:
            verify_type = "password"
        else:
            verify_type = "fingerprint"   # covers slots 1-10 + default

        # Try to match member by id (PIN = member_id integer)
        member    = None
        member_id = None
        try:
            mid_int = int(raw_pin)
            res = (
                db.table("members")
                .select("id, name, photo_url, status")
                .eq("id", mid_int)
                .single()
                .execute()
            )
            if res.data:
                member    = res.data
                member_id = mid_int
        except Exception:
            pass

        access_granted  = member is not None and (member.get("status") == "active")
        denial_reason   = None
        if member is None:
            denial_reason = "unknown_pin"
        elif member.get("status") != "active":
            denial_reason = "member_inactive"

        # Parse punch timestamp
        punch_dt = None
        try:
            punch_dt = datetime.strptime(raw_time[:19], "%Y-%m-%d %H:%M:%S") if raw_time else datetime.utcnow()
        except Exception:
            punch_dt = datetime.utcnow()

        # Resolve device_id from serial_number
        device_id = None
        try:
            dev_res = (
                db.table("zkteco_devices")
                .select("id")
                .eq("serial_number", serial_number)
                .single()
                .execute()
            )
            if dev_res.data:
                device_id = dev_res.data["id"]
        except Exception:
            pass

        # Log to attendance_logs
        try:
            db.table("attendance_logs").insert({
                "member_id":     member_id,
                "device_id":     device_id,
                "check_in_at":   punch_dt.isoformat(),
                "access_granted": access_granted,
                "denial_reason": denial_reason,
                "raw_event":     punch_data,
            }).execute()
        except Exception:
            pass

        # Update biometric_enrollments on first successful scan
        if member_id and access_granted and verify_type in ("fingerprint", "face"):
            BiometricService._mark_enrolled(member_id, verify_type)

        member_name = (member or {}).get("name") or f"PIN {raw_pin}"

        return {
            "type":          "scan",
            "pin":           raw_pin,
            "member_id":     member_id,
            "name":          member_name,
            "photo_url":     (member or {}).get("photo_url"),
            "sn":            serial_number,
            "time":          raw_time or punch_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "verify_type":   verify_type,
            "access_granted": access_granted,
            "denial_reason": denial_reason,
        }

    @staticmethod
    def _mark_enrolled(member_id: int, verify_type: str) -> None:
        """Update biometric_enrollments for the member."""
        db = get_supabase()

        existing = (
            db.table("biometric_enrollments")
            .select("id, fingerprint_status, face_status")
            .eq("member_id", member_id)
            .limit(1)
            .execute()
        ).data

        if verify_type == "fingerprint":
            payload = {
                "fingerprint_status": "enrolled",
                "last_synced_at":     datetime.utcnow().isoformat(),
                "updated_at":         datetime.utcnow().isoformat(),
            }
        else:
            payload = {
                "face_status":    "enrolled",
                "last_synced_at": datetime.utcnow().isoformat(),
                "updated_at":     datetime.utcnow().isoformat(),
            }

        if existing:
            db.table("biometric_enrollments").update(payload).eq("id", existing[0]["id"]).execute()
        else:
            db.table("biometric_enrollments").insert({
                "member_id":         member_id,
                "fingerprint_status": "enrolled" if verify_type == "fingerprint" else "not_enrolled",
                "face_status":        "enrolled" if verify_type == "face"        else "not_enrolled",
                "last_synced_at":     datetime.utcnow().isoformat(),
            }).execute()

    # ── Enrollment Status ─────────────────────────────────────────────────────

    @staticmethod
    def get_enrollment(member_id: int) -> dict:
        db  = get_supabase()
        res = (
            db.table("biometric_enrollments")
            .select("*")
            .eq("member_id", member_id)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
        return {
            "member_id":          member_id,
            "fingerprint_status": "not_enrolled",
            "face_status":        "not_enrolled",
        }

    # ── Sync all active members to a device ──────────────────────────────────

    @staticmethod
    def sync_all_members_to_device(serial_number: str) -> int:
        """
        Queue DATA UPDATE user commands for every active member
        to the given device. Used by 'Sync Members' button in UI.
        """
        db  = get_supabase()
        rows = (
            db.table("members")
            .select("id, name")
            .eq("status", "active")
            .execute()
        ).data or []

        if serial_number not in _command_queue:
            _command_queue[serial_number] = []

        for m in rows:
            BiometricService._queue_add_user(serial_number, m["id"], m["name"])

        return len(rows)

    # ── Recent scan logs (for monitor page) ──────────────────────────────────

    @staticmethod
    def get_recent_logs(limit: int = 50) -> list:
        db   = get_supabase()
        rows = (
            db.table("attendance_logs")
            .select(
                "id, check_in_at, access_granted, denial_reason, raw_event, member_id, device_id,"
                "members!attendance_logs_member_id_fkey(name, photo_url),"
                "zkteco_devices!attendance_logs_device_id_fkey(name, serial_number)"
            )
            .order("check_in_at", desc=True)
            .limit(limit)
            .execute()
        ).data or []

        out = []
        for r in rows:
            member = r.get("members") or {}
            device = r.get("zkteco_devices") or {}
            raw    = r.get("raw_event") or {}
            ver    = str(raw.get("Verified") or raw.get("verified") or "0").strip()
            if ver in VERIFY_FACE:
                vtype = "Face"
            elif ver in VERIFY_CARD:
                vtype = "Card"
            elif ver in VERIFY_PASSWORD:
                vtype = "Password"
            else:
                vtype = "Fingerprint"

            out.append({
                "id":            r.get("id"),
                "member_id":     r.get("member_id"),
                "name":          member.get("name") or f"Unknown PIN",
                "photo_url":     member.get("photo_url"),
                "device_name":   device.get("name") or "Unknown Device",
                "check_in_at":   r.get("check_in_at", ""),
                "check_in_fmt":  _fmt_date(r.get("check_in_at")),
                "access_granted": r.get("access_granted"),
                "denial_reason": r.get("denial_reason"),
                "verify_type":   vtype,
            })
        return out
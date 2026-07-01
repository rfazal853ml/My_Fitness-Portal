"""
Biometric router — two separate route groups in one file:

1. iclock_router  (prefix /iclock)  — ZKTeco ADMS device protocol
   The ZKTeco device contacts these endpoints directly over HTTP.
   No auth required (device doesn't support JWT).

2. router         (prefix /biometric) — Admin UI + JSON APIs
   Protected by get_current_user like every other module.

WebSocket at /biometric/ws  — real-time scan monitor.
"""

import json
import re
import asyncio
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from utils.dependencies import get_current_user
from services.biometric_service import BiometricService
from services.supabase_client import get_supabase

# ── Two routers ────────────────────────────────────────────────────────────────
router        = APIRouter(prefix="/biomatric-devices", tags=["biometric"])   # Admin UI
iclock_router = APIRouter(prefix="/iclock",    tags=["iclock"])       # ZKTeco protocol

templates = Jinja2Templates(directory="templates")

# ── ZKTeco log line parser ─────────────────────────────────────────────────────
LOG_PATTERN = re.compile(r'([a-zA-Z_]+)=(.+?)(?=\s+[a-zA-Z_]+=|\s*$)')

# ── WebSocket connection pool ──────────────────────────────────────────────────
_ws_clients: list[WebSocket] = []


async def _broadcast(data: dict) -> None:
    """Safely send JSON to every connected monitor client."""
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(json.dumps(data))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


# ── Private helpers ────────────────────────────────────────────────────────────

def _gym_name() -> str:
    try:
        db = get_supabase()
        r  = db.table("settings").select("value").eq("key", "gym_name").single().execute()
        return r.data["value"] if r.data else "Gym25"
    except Exception:
        return "Gym25"


# ══════════════════════════════════════════════════════════════════════════════
#  ZKTECO ICLOCK PROTOCOL  —  /iclock/*
#  Device calls these; no user auth, plain text responses.
# ══════════════════════════════════════════════════════════════════════════════

@iclock_router.get("/cdata")
def iclock_handshake(SN: str = Query(...)):
    """
    Device connects for the first time — respond with server config.
    Also mark device as online in DB.
    """
    try:
        BiometricService.update_device_status(SN, "online")
    except Exception:
        pass
    payload = (
        "OK\n"
        "RegistryCode=1\n"
        "ServerVersion=3.1.2\n"
        "UpdateFlag=0\n"
    )
    return Response(content=payload, media_type="text/plain")


@iclock_router.post("/registry")
def iclock_registry(SN: str = Query(...)):
    """Device self-registration confirmation."""
    try:
        BiometricService.update_device_status(SN, "online")
    except Exception:
        pass
    return Response(content="RegistryCode=12345678\n", media_type="text/plain")


@iclock_router.post("/push")
def iclock_push(SN: str = Query(...)):
    return Response(content="OK\n", media_type="text/plain")


@iclock_router.get("/ping")
def iclock_ping(SN: str = Query(...)):
    """Heartbeat from device — keep it marked online."""
    try:
        BiometricService.update_device_status(SN, "online")
    except Exception:
        pass
    return Response(content="OK\n", media_type="text/plain")


@iclock_router.get("/getrequest")
def iclock_getrequest(SN: str = Query(...)):
    """
    Device polls for pending commands (add user, delete user, etc.).
    Returns the next queued command or 'OK' if nothing pending.
    """
    cmd = BiometricService.pop_next_command(SN)
    if cmd:
        return Response(content=f"{cmd}\n", media_type="text/plain")
    return Response(content="OK\n", media_type="text/plain")


@iclock_router.post("/devicecmd")
async def iclock_devicecmd(request: Request, SN: str = Query(...)):
    """Device reports the result of a command we sent — acknowledge."""
    return Response(content="OK\n", media_type="text/plain")


@iclock_router.post("/cdata")
async def iclock_cdata(
    request: Request,
    SN:      str           = Query(...),
    table:   Optional[str] = Query(None),
):
    """
    Main data endpoint — device pushes attendance logs (rtlog),
    user data, and template uploads here.
    We care about table=rtlog (punch events).
    """
    raw_body = await request.body()
    body     = raw_body.decode("utf-8", errors="ignore")

    if table == "rtlog":
        lines = body.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Parse key=value pairs from the log line
            matches    = LOG_PATTERN.findall(line)
            punch_data = {k: v.strip() for k, v in matches}

            if not punch_data:
                continue

            # Process in the service — logs to DB + updates enrollment
            try:
                result = BiometricService.process_punch(SN, punch_data)
                # Broadcast to WebSocket monitor clients (fire-and-forget)
                asyncio.create_task(_broadcast({
                    "type":          "scan",
                    "pin":           result["pin"],
                    "member_id":     result["member_id"],
                    "name":          result["name"],
                    "photo_url":     result["photo_url"],
                    "sn":            SN,
                    "time":          result["time"],
                    "verify_type":   result["verify_type"],
                    "access_granted": result["access_granted"],
                    "denial_reason": result["denial_reason"],
                }))
            except Exception as e:
                print(f"[biometric] punch processing error: {e}")

    return Response(content="OK\n", media_type="text/plain")


# ══════════════════════════════════════════════════════════════════════════════
#  WEBSOCKET  —  /biometric/ws
#  Real-time scan monitor — browser connects here to receive punch events.
# ══════════════════════════════════════════════════════════════════════════════

@router.websocket("/ws")
async def biometric_ws(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            # Keep alive — we only push TO clients, never receive
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN UI  —  /biometric/*
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
async def biometric_page(
    request:      Request,
    success:      str  = "",
    error:        str  = "",
    current_user: dict = Depends(get_current_user),
):
    devices = BiometricService.get_all_devices()
    logs    = BiometricService.get_recent_logs(50)

    return templates.TemplateResponse(request, "biometric/biometric.html", {
        "gym_name":    _gym_name(),
        "page_title":  "Biometric Devices",
        "active_page": "biometric",
        "user":        current_user,
        "devices":     devices,
        "logs":        logs,
        "success":     success,
        "error":       error,
    })


# ── Device CRUD ───────────────────────────────────────────────────────────────

@router.post("/devices/add")
async def add_device(
    name:          str = Form(...),
    ip_address:    str = Form(...),
    serial_number: str = Form(""),
    port:          str = Form("4370"),
    location:      str = Form(""),
    current_user:  dict = Depends(get_current_user),
):
    try:
        BiometricService.add_device({
            "name":          name,
            "ip_address":    ip_address,
            "serial_number": serial_number,
            "port":          port,
            "location":      location,
        })
        return RedirectResponse(
            url="/biometric/?success=Device+added+successfully",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/biometric/?error={str(e)}",
            status_code=302,
        )


@router.post("/devices/update/{device_id}")
async def update_device(
    device_id:     str,
    name:          str = Form(...),
    ip_address:    str = Form(...),
    serial_number: str = Form(""),
    port:          str = Form("4370"),
    location:      str = Form(""),
    current_user:  dict = Depends(get_current_user),
):
    try:
        BiometricService.update_device(device_id, {
            "name":          name,
            "ip_address":    ip_address,
            "serial_number": serial_number,
            "port":          port,
            "location":      location,
        })
        return RedirectResponse(
            url="/biometric/?success=Device+updated+successfully",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/biometric/?error={str(e)}",
            status_code=302,
        )


@router.post("/devices/delete/{device_id}")
async def delete_device(
    device_id:    str,
    current_user: dict = Depends(get_current_user),
):
    try:
        BiometricService.delete_device(device_id)
        return RedirectResponse(
            url="/biometric/?success=Device+removed+successfully",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/biometric/?error={str(e)}",
            status_code=302,
        )


# ── Sync all members to a device ─────────────────────────────────────────────

@router.post("/devices/sync/{device_id}")
async def sync_device(
    device_id:    str,
    current_user: dict = Depends(get_current_user),
):
    """Push all active members to a single device."""
    try:
        device = BiometricService.get_device(device_id)
        sn     = device.get("serial_number")
        if not sn:
            return JSONResponse(
                {"success": False, "error": "Device has no serial number configured."},
                status_code=400,
            )
        count = BiometricService.sync_all_members_to_device(sn)
        return JSONResponse({
            "success": True,
            "message": f"{count} members queued for sync. Commands will be sent on next device poll.",
            "count":   count,
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ── Push single member to all devices (called from member_service on add) ─────

@router.post("/members/push/{member_id}")
async def push_member(
    member_id:    int,
    current_user: dict = Depends(get_current_user),
):
    """Manually push a specific member to all registered devices."""
    try:
        db     = get_supabase()
        member = db.table("members").select("id, name").eq("id", member_id).single().execute()
        if not member.data:
            return JSONResponse({"success": False, "error": "Member not found."}, status_code=404)
        count = BiometricService.push_member_to_all_devices(member_id, member.data["name"])
        return JSONResponse({
            "success": True,
            "message": f"Member queued for {count} device(s).",
            "count":   count,
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ── Recent scan logs JSON (for live reload in UI) ─────────────────────────────

@router.get("/logs")
async def get_logs(
    limit:        int  = 50,
    current_user: dict = Depends(get_current_user),
):
    try:
        return JSONResponse(BiometricService.get_recent_logs(limit))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Enrollment status for a member ───────────────────────────────────────────

@router.get("/enrollment/{member_id}")
async def get_enrollment(
    member_id:    int,
    current_user: dict = Depends(get_current_user),
):
    return JSONResponse(BiometricService.get_enrollment(member_id))
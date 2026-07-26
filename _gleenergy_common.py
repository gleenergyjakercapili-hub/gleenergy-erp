"""
Shared code for the Gleenergy backends (app.py = SQLite, app_postgres.py = Postgres)
====================================================================================

Both backends implement the SAME four storage methods over different databases.
Everything that is NOT database-specific lives here so there is ONE copy to fix:

  - request body shapes (Pydantic models)
  - API-key protection for the /api/* routes
  - email sending  (/api/send-email)
  - SMS sending    (/api/send-sms)
  - serving the app (index + static files in public/)

Each backend just defines its own `_conn()` + the four storage routes, then calls
`install_shared(app)` to attach all of the above.

-----------------------------------------------------------------------
SECURITY: turning on the API key (do this BEFORE exposing the server)
-----------------------------------------------------------------------
By default the server runs open (fine on your own PC / trusted office LAN).
Before you expose it to the internet (e.g. through ngrok), set a secret key:

    Windows:   set GLEENERGY_API_KEY=some-long-random-secret
    Mac/Linux: export GLEENERGY_API_KEY=some-long-random-secret

When that variable is set:
  - Every /api/* call must send it in the `X-API-Key` header, OR it is rejected
    with 401. Random internet scanners and other websites won't have the key.
  - The server injects the key into the page it serves, so the app in YOUR
    browser keeps working automatically (nothing to configure in the browser).
  - Cross-origin (other-website) access is turned off unless you explicitly list
    allowed origins in GLEENERGY_CORS_ORIGINS (comma-separated).
  - /api/health stays open so uptime checks keep working.

If GLEENERGY_API_KEY is NOT set, behaviour is exactly as before (open server,
permissive CORS) and a warning is printed at startup.
"""

import os
import json
import ssl
import smtplib
import urllib.request
import urllib.parse
import urllib.error
from email.message import EmailMessage

from pydantic import BaseModel
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

BASE_DIR = os.path.dirname(__file__)
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
INDEX_FILE = os.path.join(PUBLIC_DIR, "index.html")
EMAIL_CONFIG_FILE = os.path.join(BASE_DIR, "config", "email_config.json")
SMS_CONFIG_FILE = os.path.join(BASE_DIR, "config", "sms_config.json")

# Secret that guards the /api/* routes. Empty string = protection off.
API_KEY = os.environ.get("GLEENERGY_API_KEY", "").strip()

# Paths that are still reachable without the key even when protection is on.
_OPEN_API_PATHS = {"/api/health"}


# ----------------------------------------------------------------------
# Request body shapes. Declaring these lets the route handlers be plain
# `def` functions (see note in the backends): FastAPI parses + validates
# the JSON body for us and runs sync handlers in a worker thread, so the
# blocking database / SMTP / HTTP calls never freeze the event loop.
# ----------------------------------------------------------------------
class KeyBody(BaseModel):
    key: str = ""


class SetBody(BaseModel):
    key: str = ""
    value: str = ""


class ListBody(BaseModel):
    prefix: str = ""


class EmailBody(BaseModel):
    to: str = ""
    subject: str = ""
    body: str = ""


class SmsBody(BaseModel):
    to: str = ""
    body: str = ""


class XlsxBody(BaseModel):
    name: str = ""
    b64: str = ""          # base64 of the .xlsx/.xlsm (data: URL prefix tolerated)
    max_rows: int = 500
    max_cols: int = 50


# ----------------------------------------------------------------------
# Config loaders
# ----------------------------------------------------------------------
def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ----------------------------------------------------------------------
# Email + SMS senders (plain functions; the routes below just wrap them)
# ----------------------------------------------------------------------
def _send_email(body: EmailBody):
    to = (body.to or "").strip()
    subject = body.subject or "(no subject)"
    text = body.body or ""

    cfg = _load_json(EMAIL_CONFIG_FILE)
    if not cfg.get("enabled"):
        return JSONResponse(
            {"ok": False, "error": "Email is not set up yet. Open email_config.json, fill in your details, and set enabled to true."},
            status_code=400,
        )
    if not to:
        return JSONResponse({"ok": False, "error": "This client has no email address."}, status_code=400)

    from_email = cfg.get("from_email") or cfg.get("smtp_user") or ""
    from_name = cfg.get("from_name") or "Gleenergy Renewables Company"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to
    reply_to = (cfg.get("reply_to") or "").strip()
    cc = (cfg.get("cc") or "").strip()
    bcc = (cfg.get("bcc") or "").strip()
    if reply_to:
        msg["Reply-To"] = reply_to     # where the client's reply goes
    if cc:
        msg["Cc"] = cc                 # visible copy
    if bcc:
        msg["Bcc"] = bcc               # private copy (stripped before sending, but still delivered)
    msg.set_content(text)

    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user", "")
    password = cfg.get("smtp_password", "")
    try:
        context = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=25) as s:
                s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=25) as s:
                s.ehlo()
                s.starttls(context=context)
                s.login(user, password)
                s.send_message(msg)
        return {"ok": True, "to": to}
    except Exception as e:
        # Don't leak internal SMTP detail to the caller; log it server-side.
        print(f"[send-email] failed: {e!r}")
        return JSONResponse(
            {"ok": False, "error": "Could not send the email. Check the server log and your email_config.json."},
            status_code=500,
        )


def _send_sms(body: SmsBody):
    number = (body.to or "").strip()
    message = body.body or ""

    cfg = _load_json(SMS_CONFIG_FILE)
    if not cfg.get("enabled"):
        return JSONResponse(
            {"ok": False, "error": "SMS is not set up yet. Open sms_config.json, add your Semaphore API key, and set enabled to true."},
            status_code=400,
        )
    if not number:
        return JSONResponse({"ok": False, "error": "This client has no mobile number."}, status_code=400)
    if not cfg.get("api_key"):
        return JSONResponse({"ok": False, "error": "Missing Semaphore api_key in sms_config.json."}, status_code=400)

    data = {"apikey": cfg.get("api_key", ""), "number": number, "message": message}
    sender = (cfg.get("sender_name") or "").strip()
    if sender:
        if len(sender) > 11:
            return JSONResponse(
                {"ok": False, "error": f'Sender name "{sender}" is {len(sender)} characters. Semaphore sender names must be 11 characters or fewer. Try "GLEENERGY".'},
                status_code=400,
            )
        data["sendername"] = sender

    endpoint = cfg.get("endpoint") or "https://api.semaphore.co/api/v4/messages"
    try:
        encoded = urllib.parse.urlencode(data).encode()
        request_obj = urllib.request.Request(endpoint, data=encoded, method="POST")
        with urllib.request.urlopen(request_obj, timeout=25) as resp:
            raw = resp.read().decode("utf-8", "ignore")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw
        # Success: Semaphore returns a list of message objects with a message_id.
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) and parsed[0].get("message_id"):
            return {"ok": True, "to": number, "status": parsed[0].get("status"), "id": parsed[0].get("message_id")}
        # Otherwise it's an error description (dict or text) from Semaphore — this
        # one is safe (and useful) to surface: invalid number, no credit, etc.
        err = parsed if isinstance(parsed, str) else json.dumps(parsed)
        return JSONResponse({"ok": False, "error": err}, status_code=502)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "ignore")
        except Exception:
            detail = str(e)
        return JSONResponse({"ok": False, "error": f"HTTP {e.code}: {detail}"}, status_code=502)
    except Exception as e:
        print(f"[send-sms] failed: {e!r}")
        return JSONResponse({"ok": False, "error": "Could not send the SMS. Check the server log."}, status_code=500)


# ----------------------------------------------------------------------
# Excel (.xlsx / .xlsm) reader — returns each sheet (tab) as rows of text
# so the browser app can show an attached workbook read-only, tab by tab.
# Excel stays the source of truth: cached formula values are read, macros
# are NOT run.
# ----------------------------------------------------------------------
def _cell_to_str(v):
    import datetime
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, datetime.datetime):
        if v.hour == 0 and v.minute == 0 and v.second == 0:
            return v.strftime("%Y-%m-%d")
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, datetime.date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, datetime.time):
        return v.strftime("%H:%M")
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return str(round(v, 4))
    return str(v)


def _parse_xlsx(body: XlsxBody):
    import base64, io
    try:
        import openpyxl
    except Exception:
        return JSONResponse(
            {"ok": False, "error": "openpyxl is not installed on the server. Run: pip install openpyxl"},
            status_code=500,
        )
    raw = (body.b64 or "").strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw)
    except Exception:
        return JSONResponse({"ok": False, "error": "Could not decode the uploaded file."}, status_code=400)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Not a readable Excel workbook: {e}"}, status_code=400)

    max_rows = max(1, min(int(body.max_rows or 500), 3000))
    max_cols = max(1, min(int(body.max_cols or 50), 120))
    sheets = []
    try:
        for ws in wb.worksheets:
            full_r = ws.max_row or 0
            full_c = ws.max_column or 0
            rmax, cmax = min(full_r, max_rows), min(full_c, max_cols)
            rows = []
            if rmax and cmax:
                for row in ws.iter_rows(min_row=1, max_row=rmax, max_col=cmax, values_only=True):
                    rows.append([_cell_to_str(c) for c in row])
            # trim trailing empty rows
            while rows and not any(rows[-1]):
                rows.pop()
            # trim trailing empty columns
            last = 0
            for x in rows:
                for ci in range(len(x) - 1, -1, -1):
                    if x[ci]:
                        if ci + 1 > last:
                            last = ci + 1
                        break
            rows = [x[:last] for x in rows]
            sheets.append({
                "name": ws.title,
                "hidden": ws.sheet_state != "visible",
                "rows": rows,
                "nrows": len(rows),
                "ncols": last,
                "truncated": full_r > max_rows or full_c > max_cols,
            })
    finally:
        try:
            wb.close()
        except Exception:
            pass
    return {"ok": True, "name": body.name, "sheetCount": len(sheets), "sheets": sheets}


# ----------------------------------------------------------------------
# App-serving helpers
# ----------------------------------------------------------------------
def _serve_index():
    if not os.path.isfile(INDEX_FILE):
        return JSONResponse({"error": "index.html not found"}, status_code=404)
    if not API_KEY:
        return FileResponse(INDEX_FILE)
    # Protection is on: hand the browser the key so the same-origin app can
    # authenticate. Other websites can't read this response (CORS is locked
    # down when a key is set), so the key stays out of their reach.
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        html = f.read()
    inject = f"<script>window.GLEENERGY_API_KEY={json.dumps(API_KEY)};</script>"
    if "</head>" in html:
        html = html.replace("</head>", inject + "</head>", 1)
    else:
        html = inject + html
    return HTMLResponse(html)


def _serve_static(path: str):
    if not path or path.startswith("api/"):
        return JSONResponse({"error": "not found"}, status_code=404)
    pub = os.path.abspath(PUBLIC_DIR)
    safe = os.path.abspath(os.path.join(pub, path))
    # block path traversal outside the public folder
    if not (safe == pub or safe.startswith(pub + os.sep)):
        return JSONResponse({"error": "not found"}, status_code=404)
    if os.path.isfile(safe):
        return FileResponse(safe)
    return JSONResponse({"error": "not found"}, status_code=404)


# ----------------------------------------------------------------------
# install_shared: attach CORS, the API-key guard, and all shared routes
# ----------------------------------------------------------------------
def install_shared(app):
    """Attach everything that is common to both backends onto `app`."""

    # --- CORS --------------------------------------------------------------
    if API_KEY:
        # Locked down: only origins you explicitly allow (usually none — the
        # app is served from the same origin, which never needs CORS).
        origins_env = os.environ.get("GLEENERGY_CORS_ORIGINS", "").strip()
        origins = [o.strip() for o in origins_env.split(",") if o.strip()]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        # Open dev mode: permissive, same as the original starter.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        print("[gleenergy] WARNING: GLEENERGY_API_KEY is not set — the /api endpoints "
              "are UNPROTECTED. Fine on your own PC, but set it before exposing the "
              "server to the internet (e.g. through ngrok).")

    # --- API-key guard for /api/* -----------------------------------------
    @app.middleware("http")
    async def _api_key_guard(request: Request, call_next):
        if API_KEY and request.method != "OPTIONS":  # let CORS preflight through
            path = request.url.path
            if path.startswith("/api/") and path not in _OPEN_API_PATHS:
                if request.headers.get("x-api-key", "") != API_KEY:
                    return JSONResponse(
                        {"ok": False, "error": "Invalid or missing API key."},
                        status_code=401,
                    )
        return await call_next(request)

    # --- Shared routes -----------------------------------------------------
    @app.post("/api/send-email")
    def send_email(body: EmailBody):
        return _send_email(body)

    @app.post("/api/send-sms")
    def send_sms(body: SmsBody):
        return _send_sms(body)

    @app.post("/api/xlsx/parse")
    def xlsx_parse(body: XlsxBody):
        return _parse_xlsx(body)

    @app.get("/api/health")
    def health():
        return {"ok": True, "protected": bool(API_KEY)}

    @app.get("/")
    def index():
        return _serve_index()

    @app.get("/{path:path}")
    def static_files(path: str):
        return _serve_static(path)

    return app

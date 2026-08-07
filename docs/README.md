# Connecting the Gleenergy System to Python

Your app already saves **all** of its data through two helpers in the HTML
(`saveKey` / `loadKey`). Those call a small object named `window.storage`
with four methods: **get, set, delete, list**.

- Inside Claude, `window.storage` is provided for you (saves to the browser).
- Standalone, the app falls back to temporary memory (lost on refresh).

This Python backend simply provides those same four methods over the web and
stores the data in a real database. **No other part of the app changes.**

```
  Browser (index.html)              Python server (app.py)         Database
  ───────────────────               ──────────────────────         ────────
  saveKey("p2:clients", …)  ──POST /api/storage/set──►   INSERT/UPDATE kv  ► gleenergy.db
  loadKey("p2:clients")     ──POST /api/storage/get──►   SELECT value      ◄ gleenergy.db
```

---

## What's in this folder

| File | What it is |
|------|------------|
| `app.py` | The server. Uses **SQLite** (a single file, zero setup). Start here. |
| `app_postgres.py` | Same server but uses **PostgreSQL** (for production / many users). |
| `requirements.txt` | The Python packages to install. |
| `public/index.html` | **Your app, already wired** to talk to this server. |
| `gleenergy.db` | Created automatically the first time you run it. **This is your data — back it up.** |

---

## Run it (SQLite — recommended to start)

1. **Install Python 3.10+** — https://www.python.org/downloads/
   (On Windows, tick *"Add Python to PATH"* during install.)

2. Open a terminal **in this folder** and install the packages:
   ```
   pip install -r requirements.txt
   ```

3. Start the server:
   ```
   uvicorn app:app --host 0.0.0.0 --port 8000
   ```

4. Open your browser at **http://localhost:8000**

That's it. Add a client, refresh the page — it's still there, because it's now
in `gleenergy.db` instead of browser memory.

### Let other people on the same Wi-Fi use it
Find this computer's local IP (e.g. `192.168.1.10`), keep the server running,
and have them open **http://192.168.1.10:8000** in their browser.

### Back up your data
Just copy the file **`gleenergy.db`** somewhere safe. To move to another
computer, copy `gleenergy.db` next to `app.py` there.

---

## How the wiring works (the only change made to your HTML)

Near the top of `public/index.html`, the old in-memory fallback was replaced
with a connector that points at this server:

```js
if (typeof window.storage === "undefined") {
  const API = (window.GLEENERGY_API || "/api/storage");
  async function call(path, body) {
    const r = await fetch(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error("storage " + path + " failed: " + r.status);
    return r.json();
  }
  window.storage = {
    get:    async (k)    => { const d = await call("/get",    { key: k });            return (d && d.value != null) ? { key: k, value: d.value } : null; },
    set:    async (k, v) => { await call("/set",    { key: k, value: String(v) });    return { key: k, value: v }; },
    delete: async (k)    => { await call("/delete", { key: k });                      return { key: k, deleted: true }; },
    list:   async (p)    => { const d = await call("/list",   { prefix: p || "" });   return { keys: (d && d.keys) || [] }; },
  };
}
```

Because it's guarded by `if (window.storage === undefined)`, the **same file
still works inside Claude** (it uses the native storage there) and **uses
Python when served from this server**. You can keep editing the app exactly
as before.

> If your API ever lives on a different address, set it before the app loads:
> `<script>window.GLEENERGY_API = "https://your-server.com/api/storage";</script>`

---

## Moving to PostgreSQL later (production)

When more than a couple of people use it at once, switch to PostgreSQL:

1. Install PostgreSQL, create a database named `gleenergy`.
2. Install the driver: `pip install "psycopg[binary]>=3.1"`
3. Set your connection string and run the Postgres server instead:
   ```
   # Mac/Linux
   export DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/gleenergy
   # Windows
   set DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/gleenergy

   uvicorn app_postgres:app --host 0.0.0.0 --port 8000
   ```

### Copy your existing data across
Your SQLite data is portable. With the SQLite server running, visit
**http://localhost:8000/api/export** to download a JSON file of every key.
(If you'd like a ready-made import script for PostgreSQL, ask and I'll add one.)

---

## Important notes & next steps

- **Security:** This starter has no API password, which is fine on your own
  computer or a trusted office network. Before exposing it to the internet,
  put it behind HTTPS (e.g. a reverse proxy like Caddy or Nginx) and add an
  API key or proper login check. The app's own user logins are checked in the
  browser only — they are **not** a substitute for securing the server.
- **One source of truth:** Once you're on the server, everyone shares the same
  database. Avoid running both the artifact version and the server version for
  real data, or they'll drift apart.
- **Photos & documents** (survey photos, uploaded files) are stored as text
  under their own keys, so they work too — but they're large. PostgreSQL
  handles many of them better than SQLite.
- **The "proper" relational schema** (separate tables for clients, projects,
  POs, etc.) is the eventual end-state for reporting and integrations. This
  key-value bridge is the fast, safe first step that gets you on Python today
  without rewriting the app; we can migrate table-by-table afterwards.

-----------------------------------------------------------------------
SENDING REAL FOLLOW-UP EMAILS (optional)
-----------------------------------------------------------------------
By default the Follow-ups "Send" button only logs the message. To make it
send a REAL email to the client, set up email once:

  1. Open the file  email_config.json  in this folder.
  2. Fill in your sending account and set  "enabled": true.

     For a Gmail account:
       - "smtp_host": "smtp.gmail.com"
       - "smtp_port": 587
       - "smtp_user": your full Gmail address
       - "smtp_password": a Gmail **App Password** (NOT your normal password)
       - "from_name":  Gleenergy Renewables Company
       - "from_email": your full Gmail address

     How to get a Gmail App Password:
       a. Turn on 2-Step Verification on the Google account.
       b. Go to  https://myaccount.google.com/apppasswords
       c. Create a password named "Gleenergy", copy the 16 characters,
          and paste them into "smtp_password" (spaces are fine to remove).

  3. Save the file and restart the server (close the window, run start.bat).
  4. In Follow-ups, click Send on a due item. The client gets a real email,
     and you'll see "Email sent to ..." confirmation.

Notes:
  - The client must have an email address saved in Clients / CRM.
  - Keep email_config.json private (it holds your app password). Anyone
    with the file can send mail as you.
  - Other SMTP providers work too (Outlook/Office365, Zoho, your host's
    mail server) — just use their host/port and your mailbox login.
  - If Gmail cuts off sends from the cloud server (SMTPServerDisconnected),
    the system automatically retries once over SSL port 465; setting
    "smtp_port": 465 makes that route the default.

-----------------------------------------------------------------------
OPTION B — SENDING VIA BREVO (HTTPS, recommended for the cloud)
-----------------------------------------------------------------------
Brevo (https://brevo.com, free tier 300 emails/day) sends over HTTPS
port 443, which no hosting provider throttles — the durable choice for
automated outreach. To switch the system to Brevo:

  1. In Brevo: check that your sender address is verified
     (Senders, Domains & Dedicated IPs → Senders — the signup email is
     verified automatically).
  2. In Brevo: profile menu → SMTP & API → "API Keys" tab → Generate a
     new API key (name it "Gleenergy ERP") and copy the xkeysib-... value
     — it is shown only once.
  3. Add TWO lines to email_config.json (keep everything else; on the
     cloud this is the Render Secret File):
       "provider": "brevo",
       "brevo_api_key": "xkeysib-PASTE-YOURS-HERE",
     from_email must be the verified Brevo sender.
  4. Save (Render redeploys ~1 min) and send a test proposal.

  - To go back to Gmail SMTP: remove the two lines (or set
    "provider": "smtp").
  - Until you verify a custom company DOMAIN in Brevo, recipients may see
    "via brevo.com" next to the sender — verifying the domain (once you
    have one) removes that and improves deliverability.

-----------------------------------------------------------------------
META LEAD ADS → AUTOMATIC LEAD CAPTURE (no manual effort)
-----------------------------------------------------------------------
Leads from Facebook/Instagram Lead Ads flow straight into Clients / CRM:
each submission creates a client (stage "Lead", source "Meta Ads — <ad>"),
custom form answers land in the client's notes, repeat inquiries annotate
the existing person instead of duplicating them, the lead is auto-enrolled
in the "New Lead Nurture" email sequence (so Follow-ups flags it at once),
and live sync shows the new prospect on every staff screen in ~10 seconds.

ONE-TIME SETUP

  A. Turn the endpoint on (Render dashboard, ~1 minute):
     1. dashboard.render.com → gleenergy-erp (web service) → Environment.
     2. Add environment variable:  GLEENERGY_LEADS_KEY
        Click "Generate" for a strong value (or invent a long random one).
        Save — the service redeploys. Keep this value private: anyone who
        has it can create leads in your CRM (nothing more).

  B. Bridge Meta to the system with Make.com (free tier covers ~1,000
     leads/month; Zapier works the same way):
     1. make.com → Create scenario.
     2. First module: "Facebook Lead Ads → Watch Leads" — connect the
        company Facebook account, pick the Page and the lead form.
     3. Second module: "HTTP → Make a request":
          URL:     https://gleenergy-erp.onrender.com/api/leads/inbound
          Method:  POST
          Headers: X-Leads-Key = the GLEENERGY_LEADS_KEY value
          Body type: JSON, with fields mapped from module 1, e.g.:
            { "name": {{full_name}}, "phone": {{phone_number}},
              "email": {{email}}, "campaign": {{ad_name}} }
          Any EXTRA fields you map (budget, roof type, questions) are
          saved into the client's notes automatically.
     4. Run once with Meta's "Send test lead" tool, then turn the
        scenario ON.

  The endpoint answers:
    503 "not enabled"  → the env variable isn't set yet
    401 "invalid key"  → the header value doesn't match
    400                → the mapped lead had no name, phone or email
    {"ok":true,...}    → captured (deduped:true = repeat inquiry noted)

-----------------------------------------------------------------------
SMS — REMOVED (2026-08)
-----------------------------------------------------------------------
Follow-up outreach is EMAIL-ONLY. SMS shifted into the Meta Ads /
Messenger space, so the Semaphore SMS integration was removed from the
system entirely — there is no /api/send-sms endpoint and nothing reads
sms_config.json anymore. Any Semaphore subscription/credit can be
cancelled; if you kept a config/sms_config.json file, it is unused and
can be deleted. Old SMS sends remain visible in the Follow-ups Send
history for the record.

-----------------------------------------------------------------------
RECEIVING CLIENT REPLIES (Reply-To + company copy)
-----------------------------------------------------------------------
The app SENDS email but does not have an inbox, so a client's REPLY does
not come back into the app — it goes to a real mailbox you control. Three
settings in email_config.json let you control where replies land and keep
your team in the loop:

  "reply_to": "sales@gleenergy..."   When the client clicks Reply, their
                                     response goes here (instead of the
                                     Gmail you send from). Use your shared
                                     sales inbox so the whole team sees it.

  "bcc": "records@gleenergy..."      A PRIVATE copy of every follow-up is
                                     sent here. The client does NOT see
                                     this address. Great for a sales
                                     archive / shared inbox record.

  "cc": "manager@gleenergy..."       A VISIBLE copy — the client CAN see
                                     this address on the email. Usually
                                     leave this blank; use bcc instead.

For more than one address, separate them with commas, e.g.
  "bcc": "records@gleenergy.com, sales@gleenergy.com"

Typical setup for a sales team:
  - reply_to = your shared sales inbox  (so replies are seen by everyone)
  - bcc      = the same or an archive inbox  (so every sent message is
               recorded even before the client replies)

Reading replies: just open the reply_to mailbox like normal email and
answer from there. (A full two-way inbox inside the app — reading and
threading client replies automatically — is a larger feature that can be
added later if you want it.)

-----------------------------------------------------------------------
CUSTOM LOGIN BACKGROUND VIDEO (optional — use YOUR OWN footage)
-----------------------------------------------------------------------
The login screen has an animated solar-farm background by default. You can
replace it with a real video — but ONLY use footage you own or are licensed
to use (e.g. Gleenergy's own drone footage of your installations). Do NOT
use videos copied from other companies' websites.

To use your own video:
  1. Prepare a short MP4 (H.264). A 10-30 second silent loop works best.
     Keep it small (ideally under ~15 MB) so the login loads quickly.
  2. Name the file exactly:  bg-video.mp4
  3. Put it inside the  public  folder (next to index.html).
  4. Refresh the login page. Your video plays full-screen behind the card,
     with the dark overlay on top so the form stays readable.

If bg-video.mp4 is not present, the original animated solar-farm scene is
shown instead — so nothing breaks if you don't add a video.

Tip: record landscape (16:9), steady, daytime; the overlay darkens it
automatically so it won't clash with the purple card.

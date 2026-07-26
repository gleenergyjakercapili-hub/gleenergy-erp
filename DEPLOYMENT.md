# Gleenergy ERP — Cloud Deployment Runbook

Goal: the system on the internet with **HTTPS**, reachable by crew phones on mobile
data at job sites, with the database on managed PostgreSQL. Recommended host:
**Render.com** (simple, auto-HTTPS, Singapore region, ~US$14/mo for always-on
app + database).

The repository is already prepared: `render.yaml` (one-click blueprint),
`requirements.txt`, `app_postgres.py`, and `.gitignore` that keeps the live
database out of the repo.

---

## Part 1 — Your 10 minutes (accounts; must be done by you)

1. **GitHub** (free): create an account at github.com if you don't have one,
   then create a new **private** repository named `gleenergy-erp`.
2. **Push the code** (from this folder — Claude can run these for you once the
   repo exists):
   ```
   git remote add origin https://github.com/YOUR-USERNAME/gleenergy-erp.git
   git push -u origin main
   ```
3. **Render** (render.com): sign up **with your GitHub account**, add a payment
   method, then: **New → Blueprint → select `gleenergy-erp`** → Apply.
   Render reads `render.yaml` and creates the web service + PostgreSQL database,
   wires them together, and issues the HTTPS certificate.
4. Wait for the first deploy (~3 min). Your URL will look like:
   `https://gleenergy-erp.onrender.com`

## Part 2 — Data migration (Claude drives this with you)

The cloud database starts empty. Migration uses the app's own Backup & Restore:
1. On the office PC (old system): download a **Full Backup** (JSON).
2. On the cloud URL: **Restore** that file. Staff accounts, roles, and all
   records arrive intact — password hashes migrate as-is, everyone keeps
   their login.
3. Verify with the audit checklist (dashboards, P&L, one login per role).

## Part 3 — Crew rollout

- Phones now use `https://gleenergy-erp.onrender.com` — **anywhere, on mobile
  data**, no Wi-Fi needed.
- "Add to Home Screen" now installs the **full PWA**: standalone window, no
  address bar, faster native crypto (no more slow phone logins).
- The old LAN address keeps working during the transition; retire it when
  everyone has moved.

## Ongoing: how updates work after hosting

Nothing about editing changes. The loop is:
1. Edit `public/index.html` (or backend files) locally, exactly as before.
2. Test on the office PC.
3. `git add -A && git commit -m "..." && git push`
4. Render redeploys automatically (~2 min). Every device gets the update on
   its next refresh — no phone-by-phone action, no app store.

Rolling back = redeploy any previous commit from the Render dashboard.

## Part 4 — Custom domain (GoDaddy or any registrar)

1. Deploy first, so `https://gleenergy-erp.onrender.com` works.
2. Buy the domain (e.g. at GoDaddy). Recommended: use a subdomain such as
   `erp.yourdomain.com` — it connects with one CNAME and leaves the root
   domain free for a future company website.
3. In **Render**: web service → Settings → **Custom Domains** → Add →
   `erp.yourdomain.com`. Render shows the DNS target to use.
4. In **GoDaddy**: My Products → the domain → **DNS** → Add record:
   - Type: `CNAME` · Name: `erp` · Value: `gleenergy-erp.onrender.com` · TTL: default
   (For a bare/root domain, Render will show an A-record value instead —
   enter it in GoDaddy the same way.)
5. Wait for DNS propagation (minutes to a day). Render verifies the record and
   **issues the HTTPS certificate automatically** — nothing to buy or renew.
6. Crew re-add their home-screen icon from the new address.

## Database & SQL notes

There is no manual SQL in this stack. The app is a key-value store with two
interchangeable backends: SQLite locally, PostgreSQL in the cloud
(`app_postgres.py` creates its own tables on first startup). Data migrates via
the app's Full Backup → Restore, not a SQL dump. Render backs up PostgreSQL
daily; additionally download an in-app Full Backup monthly as an offline copy.

## Security notes

- HTTPS is automatic and enforced by Render.
- **Login is verified on the server.** `POST /api/auth/login` checks the
  password against the stored PBKDF2 hash and answers with an HttpOnly
  session cookie (7 days, sliding; `Secure` on HTTPS). Every other `/api/*`
  call requires that cookie — without signing in, the storage API returns
  401\. Failed sign-ins are rate-limited (8 per account, 30 per IP, per
  10 minutes). Sessions live in a `sessions` table (only the SHA-256 of the
  token is stored) and are revoked on logout.
- `GLEENERGY_API_KEY` is now **only** for server-to-server scripts and
  backups (`X-API-Key` header). It is no longer injected into the served
  page. Because older builds did publish it in the page, **regenerate the
  key once in Render** (service → Environment → `GLEENERGY_API_KEY` →
  generate a new value) after this version deploys.
- Remaining honest limitation: any signed-in employee's browser talks to a
  shared key-value store, so per-module permissions are still enforced by
  the app UI, not per-key by the server. Server-side per-key authorization
  is the next hardening milestone.
- The `data/` folder (SQLite + backups with real staff records) is git-ignored
  and never leaves the office PC.

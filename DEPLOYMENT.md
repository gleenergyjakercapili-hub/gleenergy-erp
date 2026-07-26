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

## Security notes

- HTTPS is automatic and enforced by Render.
- `GLEENERGY_API_KEY` is generated on Render and required by the storage API,
  which blocks random internet scanners from reading/writing data directly.
- **Honest limitation:** application login remains client-verified (as on the
  LAN). The API key + HTTPS raise the bar substantially, but true server-side
  session auth is the next hardening milestone once hosting is live. Until
  then, treat the URL itself as semi-confidential — don't publish it.
- The `data/` folder (SQLite + backups with real staff records) is git-ignored
  and never leaves the office PC.

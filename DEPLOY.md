# Deploying ragbox

Total cost to run: **$5-10/month.** Follow this in order.

---

## ⚠️ The one thing that will destroy your business if you get it wrong

ragbox stores the account database **and every customer's uploaded documents** on disk.
Container platforms (Railway, Render, Fly, Heroku) give you an **ephemeral filesystem** - it is
wiped on every redeploy, restart and crash.

**Without a persistent volume, your first redeploy silently deletes every customer's documents.**

Two protections are built in:
- `RAGBOX_HOME=/data` is set in the Dockerfile, so all state lives in one directory you can mount.
- `GET /health` returns `"data_persistent": true/false`. **Check it right after deploying.**
  If it says false, stop and mount the volume before letting anyone sign up.

---

## Option A - Railway (easiest, recommended to start)

1. Go to **railway.app** → sign in with GitHub → **New Project → Deploy from GitHub repo** →
   pick `junaidshahid-dev/ragbox`. It detects the Dockerfile automatically.
2. **Add the volume (do this before anything else):**
   Project → your service → **Variables/Settings → Volumes → New Volume**
   → **Mount path: `/data`** → Save. This is the step that keeps customer data alive.
3. **Environment variables** (Settings → Variables):
   | Key | Value |
   |---|---|
   | `RAGBOX_HOME` | `/data` |
   | `ANTHROPIC_API_KEY` | your key *(only needed for AI-written answers)* |
4. Railway gives you a URL like `ragbox-production.up.railway.app`. Open
   `https://<your-url>/health` and confirm **`"data_persistent": true`**.
5. Visit `/welcome` - your landing page. Sign up, upload a file, ask a question.

## Option B - A small VPS (cheapest, most control)

A $4-5/month box (Hetzner CX22, DigitalOcean, Vultr) has a **real filesystem**, so persistence
is automatic - a natural fit for a SQLite + local-files app.

```bash
# on a fresh Ubuntu box
apt update && apt install -y docker.io git
git clone https://github.com/junaidshahid-dev/ragbox && cd ragbox
docker build -t ragbox .
docker run -d --name ragbox --restart=always \
  -p 80:8000 \
  -v /srv/ragbox-data:/data \          # <-- persistence
  -e RAGBOX_HOME=/data \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  ragbox
```
Then put Caddy or nginx in front for HTTPS (Caddy does certificates automatically).

---

## Domain (~$10/year)

1. Buy a domain (Namecheap, Cloudflare, Porkbun). Ideas: `askyourdocs.io`, `citedocs.com`.
2. Point it at your host:
   - **Railway:** Settings → Networking → Custom Domain → add it → copy the CNAME into your DNS.
   - **VPS:** an `A` record to the server IP.
3. HTTPS is automatic on Railway; use Caddy on a VPS. **Never take signups over plain HTTP** -
   session cookies would travel in clear text.

---

## Before you accept a single signup

- [ ] `/health` shows `"data_persistent": true`
- [ ] Site is on **HTTPS**
- [ ] You can sign up, upload, ask, and get a cited answer on the live URL
- [ ] Redeploy once **on purpose**, then confirm your test account and its documents survived
- [ ] Set `ANTHROPIC_API_KEY` (or leave AI answers off and sell cited passages only)
- [ ] Back up `/data` - `tar czf backup.tgz /srv/ragbox-data` on a cron is enough at this stage

---

## Known limits at this stage (honest)

- **SQLite allows one writer at a time.** Fine for early customers; move to Postgres when
  concurrent signups/uploads start blocking (you'll see it as slow requests, not corruption).
- **Indexes live in memory**, capped at 50 tenants (LRU). Idle tenants are rebuilt from disk on
  demand - correct, just a slower first query for them.
- **A full re-index is O(all chunks per tenant)** because TF-IDF needs a global vocabulary. At
  ~0.5s per upload for a 500-document tenant this is fine; revisit if a tenant grows much larger.
- **One process.** Don't run multiple workers against the same SQLite file until you migrate to
  Postgres.

None of these block your first paying customers. All of them are the right problems to have.

---

## Billing (after the app is live)

1. Sign up at **Dodo Payments** (4% + $0.40, built for indie founders) - or Lemon Squeezy.
2. Create two monthly products: **Starter $19** and **Business $49**.
3. Set your payout destination to **Wise**.
4. Add a webhook to your deployment that calls, on successful payment/renewal:
   `TENANCY.activate_subscription(account_id, plan, period_end, provider_ref)`
   and on failure: `TENANCY.mark_past_due(account_id)`.
   The subscription lifecycle these plug into is already written and tested in `ragbox/saas.py`.

Until the webhook exists you can still take money manually: get paid via Wise, then upgrade the
account yourself with `TENANCY.set_plan(account_id, "starter")`. **Do not delay your first
customer for want of automated billing.**

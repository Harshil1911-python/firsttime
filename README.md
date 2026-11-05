# CF Learn — tiny Flask app for free Cloudflare

Learn the pattern for running a **Python Flask + HTML** app on **Cloudflare Free**:

| Concern | Local | Cloudflare Free |
|--------|--------|------------------|
| App code | Flask | **Python Workers** (WSGI) |
| Data | SQLite file | **D1** |
| Photos | `data/uploads/` | **R2** |

This is intentionally small (notes + optional photo) so you can understand the full Estacle port later.

---

## 1. Run locally (no Cloudflare)

```bash
cd cf-flask-learn
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000**

- Add a note + photo  
- Data → `data/learn.db`  
- Photos → `data/uploads/`

---

## 2. Deploy on Cloudflare Free

### Prerequisites

- Cloudflare account (free)
- Node.js + npm  
- [uv](https://github.com/astral-sh/uv) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

### Create D1 + R2

```bash
npx wrangler login

# D1 database
npx wrangler d1 create cf-flask-learn-db
# Copy the database_id into wrangler.toml → database_id

# Apply schema
npx wrangler d1 execute cf-flask-learn-db --remote --file=./schema/schema.sql

# R2 bucket
npx wrangler r2 bucket create cf-flask-learn-uploads
```

Edit `wrangler.toml` and set `database_id` (and `preview_database_id` if you use one).

### Deploy Python Worker

```bash
uv tool install workers-py
uv sync
uv run pywrangler deploy
```

Or follow current Cloudflare docs for **Python Workers + Flask WSGI** if CLI names change slightly.

### Secrets

```bash
npx wrangler secret put SECRET_KEY
```

---

## 3. Mental model (for full Estacle later)

```text
Browser
   → Cloudflare Worker (Flask via WSGI)
        → D1  (rows: title, body, photo_key)
        → R2  (image bytes)
```

Estacle needs the same idea:

- every `sqlite3` table → **D1**
- every file in `static/uploads` → **R2**
- `gunicorn` → **Workers entrypoint**

---

## 4. Project layout

```text
cf-flask-learn/
  app.py              # Flask routes + local/CF storage helpers
  worker_entry.py     # Cloudflare Python Workers entry
  schema/schema.sql   # D1 / SQLite schema
  templates/          # HTML
  static/style.css
  wrangler.toml       # D1 + R2 bindings
  pyproject.toml
```

---

## 5. Troubleshooting

| Issue | What to check |
|--------|----------------|
| Deploy tools differ | Use latest [Python Workers](https://developers.cloudflare.com/workers/languages/python/) docs |
| D1 binding missing | `database_id` in `wrangler.toml` |
| Photos on CF | R2 bucket name + `UPLOADS` binding; may need a small route to stream R2 objects |
| Free limits | D1/R2/Workers free quotas apply |

Local mode always works for learning UI/logic without an account.

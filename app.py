"""
CF Learn — tiny Flask app (notes + photo).
Local: SQLite + disk uploads.
Cloudflare: D1 + R2 via Workers bindings (see worker_entry.py).
"""
from __future__ import annotations

import os
import uuid
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, g, request, redirect, url_for, render_template,
    flash, send_from_directory, abort,
)

BASE = Path(__file__).resolve().parent
LOCAL_DB = BASE / "data" / "learn.db"
LOCAL_UPLOADS = BASE / "data" / "uploads"


def create_app(cf_env=None) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-learn-secret-change-me")
    app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024  # 3 MB
    app.config["CF_ENV"] = cf_env  # Workers env (D1/R2) when on Cloudflare

    LOCAL_UPLOADS.mkdir(parents=True, exist_ok=True)
    LOCAL_DB.parent.mkdir(parents=True, exist_ok=True)

    def is_cf() -> bool:
        return app.config.get("CF_ENV") is not None

    def get_local_db():
        if "db" not in g:
            g.db = sqlite3.connect(str(LOCAL_DB))
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_err=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_local():
        db = get_local_db()
        db.executescript((BASE / "schema" / "schema.sql").read_text())
        db.commit()

    @app.before_request
    def ensure_local_schema():
        if not is_cf():
            init_local()

    # ----- data helpers (local) -----
    def list_items_local():
        rows = get_local_db().execute(
            "SELECT * FROM items ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_item_local(title, body, photo_key):
        db = get_local_db()
        db.execute(
            "INSERT INTO items (title, body, photo_key) VALUES (?, ?, ?)",
            (title, body, photo_key),
        )
        db.commit()

    def get_item_local(item_id):
        row = get_local_db().execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_item_local(item_id):
        db = get_local_db()
        row = get_item_local(item_id)
        if row and row.get("photo_key"):
            p = LOCAL_UPLOADS / row["photo_key"]
            if p.exists():
                p.unlink()
        db.execute("DELETE FROM items WHERE id = ?", (item_id,))
        db.commit()

    def save_photo_local(file_storage):
        if not file_storage or not file_storage.filename:
            return None
        ext = Path(file_storage.filename).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            return None
        key = f"{uuid.uuid4().hex}{ext}"
        file_storage.save(LOCAL_UPLOADS / key)
        return key

    # ----- routes -----
    @app.route("/")
    def index():
        if is_cf():
            items = list_items_cf(app.config["CF_ENV"])
        else:
            items = list_items_local()
        return render_template("index.html", items=items, mode="cloudflare" if is_cf() else "local")

    @app.route("/add", methods=["GET", "POST"])
    def add():
        if request.method == "POST":
            title = (request.form.get("title") or "").strip()
            body = (request.form.get("body") or "").strip()
            if not title:
                flash("Title is required.", "error")
                return redirect(url_for("add"))
            photo = request.files.get("photo")
            if is_cf():
                key = save_photo_cf(app.config["CF_ENV"], photo)
                add_item_cf(app.config["CF_ENV"], title, body, key)
            else:
                key = save_photo_local(photo)
                add_item_local(title, body, key)
            flash("Saved.", "ok")
            return redirect(url_for("index"))
        return render_template("add.html", mode="cloudflare" if is_cf() else "local")

    @app.route("/item/<int:item_id>")
    def detail(item_id):
        if is_cf():
            item = get_item_cf(app.config["CF_ENV"], item_id)
        else:
            item = get_item_local(item_id)
        if not item:
            abort(404)
        return render_template("detail.html", item=item, mode="cloudflare" if is_cf() else "local")

    @app.route("/item/<int:item_id>/delete", methods=["POST"])
    def delete(item_id):
        if is_cf():
            delete_item_cf(app.config["CF_ENV"], item_id)
        else:
            delete_item_local(item_id)
        flash("Deleted.", "ok")
        return redirect(url_for("index"))

    @app.route("/media/<path:key>")
    def media(key):
        """Serve local uploads."""
        if is_cf():
            abort(404)
        return send_from_directory(LOCAL_UPLOADS, key)

    @app.route("/files/<path:key>")
    def files(key):
        """Stream object from R2 when running on Cloudflare."""
        if not is_cf():
            return send_from_directory(LOCAL_UPLOADS, key)
        env = app.config["CF_ENV"]
        obj = env.UPLOADS.get(key)
        if obj is None:
            abort(404)
        # Python Workers R2 object — body as bytes
        data = obj
        if hasattr(obj, "read"):
            data = obj.read()
        from flask import Response
        return Response(data, mimetype="image/jpeg")

    @app.route("/health")
    def health():
        return {"ok": True, "mode": "cloudflare" if is_cf() else "local"}

    return app


# ----- Cloudflare D1 / R2 helpers (sync wrappers used when env is injected) -----
# On Python Workers these use bindings. Locally they are unused.

def list_items_cf(env):
    # env.DB is D1; API is async in JS — Python Workers expose prepare().all()
    try:
        result = env.DB.prepare(
            "SELECT id, title, body, photo_key, created_at FROM items ORDER BY id DESC"
        ).all()
        # Normalize to list[dict]
        rows = getattr(result, "results", None) or result
        out = []
        for r in rows:
            if hasattr(r, "get"):
                out.append(dict(r))
            else:
                out.append({
                    "id": r[0] if not hasattr(r, "id") else r.id,
                    "title": getattr(r, "title", r[1] if len(r) > 1 else ""),
                    "body": getattr(r, "body", r[2] if len(r) > 2 else ""),
                    "photo_key": getattr(r, "photo_key", r[3] if len(r) > 3 else None),
                    "created_at": getattr(r, "created_at", r[4] if len(r) > 4 else ""),
                })
        return out
    except Exception:
        return []


def add_item_cf(env, title, body, photo_key):
    env.DB.prepare(
        "INSERT INTO items (title, body, photo_key) VALUES (?, ?, ?)"
    ).bind(title, body, photo_key).run()


def get_item_cf(env, item_id):
    result = env.DB.prepare("SELECT * FROM items WHERE id = ?").bind(item_id).first()
    if result is None:
        return None
    if hasattr(result, "get"):
        return dict(result)
    return {
        "id": getattr(result, "id", item_id),
        "title": getattr(result, "title", ""),
        "body": getattr(result, "body", ""),
        "photo_key": getattr(result, "photo_key", None),
        "created_at": getattr(result, "created_at", ""),
    }


def delete_item_cf(env, item_id):
    item = get_item_cf(env, item_id)
    if item and item.get("photo_key"):
        try:
            env.UPLOADS.delete(item["photo_key"])
        except Exception:
            pass
    env.DB.prepare("DELETE FROM items WHERE id = ?").bind(item_id).run()


def save_photo_cf(env, file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = Path(file_storage.filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return None
    key = f"{uuid.uuid4().hex}{ext}"
    data = file_storage.read()
    # R2 put
    env.UPLOADS.put(key, data, httpMetadata={"contentType": file_storage.mimetype or "application/octet-stream"})
    return key


# Local dev entry
app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)

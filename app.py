"""
Embroidery Opportunity Finder — local web dashboard.

Run:  python3 app.py
Then open http://localhost:5000 in your browser.
"""
import sys
import os
import subprocess
import threading
import json

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, request, send_from_directory, session, redirect, Response
from engine.config import load_env
load_env()
from engine.db import (init_db, ensure_status_column, get_opportunities_full,
                       set_status, get_contacts, stats, get_settings, save_settings,
                       ensure_settings_table, ensure_outreach_table, save_outreach,
                       get_outreach, set_outreach_status)
from engine.urlfix import ensure_columns
from engine.sdr import draft_email
import datetime

app = Flask(__name__, static_folder="ui", static_url_path="")
app.secret_key = os.environ.get("APP_SECRET", "embro-" + os.urandom(8).hex())

# Dashboard password (change via APP_PASSWORD env or settings). Empty = no login required.
def _dashboard_password():
    return os.environ.get("APP_PASSWORD", "") or get_settings().get("dashboard_password", "")


@app.before_request
def _require_login():
    pw = _dashboard_password()
    if not pw:
        return  # no password set → open access
    if request.path in ("/login", "/api/login") or request.path.startswith("/favicon"):
        return
    if session.get("authed"):
        return
    if request.path.startswith("/api/"):
        return jsonify({"error": "auth required"}), 401
    return redirect("/login")


@app.route("/login", methods=["GET"])
def login_page():
    return """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
    <body style="font-family:-apple-system,sans-serif;background:#f5f5f2;display:flex;
    align-items:center;justify-content:center;height:100vh;margin:0">
    <form onsubmit="event.preventDefault();fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({password:document.getElementById('p').value})}).then(r=>r.json()).then(d=>{
    if(d.ok)location.href='/';else document.getElementById('e').textContent='Wrong password'})"
    style="background:#fff;padding:32px;border-radius:12px;border:1px solid #e3e3dd;width:280px">
    <h2 style="margin:0 0 16px;font-weight:500">Embroidery Finder</h2>
    <input id=p type=password placeholder=Password autofocus
    style="width:100%;height:38px;border:1px solid #ccc;border-radius:8px;padding:0 12px;margin-bottom:12px;box-sizing:border-box">
    <button style="width:100%;height:38px;border:none;border-radius:8px;background:#185FA5;color:#fff;font-size:14px;cursor:pointer">Open dashboard</button>
    <div id=e style="color:#c00;font-size:13px;margin-top:10px"></div></form></body>"""


@app.route("/api/login", methods=["POST"])
def api_login():
    if (request.get_json() or {}).get("password") == _dashboard_password():
        session["authed"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 403


# Track background engine jobs
JOB_STATE = {"running": False, "task": "", "log": []}


def _run_engine(task_args, task_name):
    JOB_STATE.update(running=True, task=task_name, log=[f"Starting {task_name}..."])
    try:
        proc = subprocess.Popen(
            [sys.executable, os.path.join(os.path.dirname(__file__), "search.py")] + task_args,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line and "NotOpenSSL" not in line and "warnings.warn" not in line:
                JOB_STATE["log"].append(line)
                JOB_STATE["log"] = JOB_STATE["log"][-200:]  # keep last 200 lines
        proc.wait()
        JOB_STATE["log"].append(f"✓ {task_name} finished.")
    except Exception as e:
        JOB_STATE["log"].append(f"✗ Error: {e}")
    finally:
        JOB_STATE["running"] = False


# ── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/opportunities")
def api_opportunities():
    rows = get_opportunities_full()
    # hide dead links from the UI
    rows = [r for r in rows if r.get("url_status") != "dead"]
    return jsonify(rows)


@app.route("/api/contacts")
def api_contacts():
    return jsonify(get_contacts())


@app.route("/api/stats")
def api_stats():
    return jsonify(stats())


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        save_settings(request.get_json() or {})
        return jsonify({"ok": True})
    return jsonify(get_settings())


@app.route("/api/outreach")
def api_outreach():
    return jsonify(get_outreach())


@app.route("/api/outreach/draft", methods=["POST"])
def api_outreach_draft():
    data = request.get_json() or {}
    s = get_settings()
    profile = {"company": s.get("company_name", ""), "sender_name": s.get("sender_name", ""),
               "phone": s.get("sender_phone", ""), "location": s.get("location", "")}
    drafted = draft_email(
        target_company=data.get("company", ""),
        role=data.get("role", ""),
        context=data.get("context", ""),
        profile_overrides=profile,
    )
    row = {
        "id": data.get("id"),
        "company": data.get("company", ""), "role": data.get("role", ""),
        "email": data.get("email", ""), "subject": drafted["subject"],
        "body": drafted["body"], "status": "draft",
        "ref_type": data.get("ref_type", ""), "ref_id": data.get("ref_id"),
        "updated_at": datetime.datetime.utcnow().isoformat(),
    }
    rid = save_outreach(row)
    row["id"] = rid
    return jsonify(row)


@app.route("/api/outreach/status", methods=["POST"])
def api_outreach_status():
    d = request.get_json() or {}
    set_outreach_status(int(d["id"]), d["status"])
    return jsonify({"ok": True})


@app.route("/api/outreach/save", methods=["POST"])
def api_outreach_save():
    d = request.get_json() or {}
    d["updated_at"] = datetime.datetime.utcnow().isoformat()
    rid = save_outreach(d)
    return jsonify({"ok": True, "id": rid})


@app.route("/api/export-markets")
def api_export_markets():
    from engine.exportmarkets import get_cached_export_markets
    return jsonify(get_cached_export_markets())


@app.route("/api/find-buyers", methods=["POST"])
def api_find_buyers():
    if JOB_STATE["running"]:
        return jsonify({"ok": False, "error": "A job is already running."}), 409
    data = request.get_json() or {}
    country = data.get("country", "")
    product = data.get("product", "garments")
    if not country:
        return jsonify({"ok": False, "error": "country required"}), 400

    def _job():
        JOB_STATE.update(running=True, task=f"Finding buyers in {country}",
                         log=[f"Searching {product} importers in {country}..."])
        try:
            from engine.buyers import find_and_store_buyers
            n = find_and_store_buyers(country, product)
            JOB_STATE["log"].append(f"✓ Found & saved {n} buyer companies in {country}. See Contacts tab.")
        except Exception as e:
            JOB_STATE["log"].append(f"✗ Error: {e}")
        finally:
            JOB_STATE["running"] = False

    threading.Thread(target=_job, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/export-markets/refresh", methods=["POST"])
def api_export_markets_refresh():
    if JOB_STATE["running"]:
        return jsonify({"ok": False, "error": "A job is already running."}), 409

    def _job():
        JOB_STATE.update(running=True, task="Export markets (UN Comtrade)",
                         log=["Fetching India export data from UN Comtrade..."])
        try:
            from engine.exportmarkets import cache_export_markets
            data = cache_export_markets()
            for p in data.get("products", []):
                JOB_STATE["log"].append(
                    f"  {p['label']}: {len(p.get('top',[]))} countries, "
                    f"${p.get('total_usd',0):,} total")
            JOB_STATE["log"].append("✓ Export markets updated.")
        except Exception as e:
            JOB_STATE["log"].append(f"✗ Error: {e}")
        finally:
            JOB_STATE["running"] = False

    threading.Thread(target=_job, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/export")
def api_export():
    """Export opportunities as CSV."""
    import csv, io
    rows = get_opportunities_full()
    rows = [r for r in rows if r.get("url_status") != "dead"]
    buf = io.StringIO()
    cols = ["relevance", "category", "source", "title", "summary", "action",
            "deadline", "location", "quantity", "value_inr", "status", "url"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    from flask import Response
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=embroidery_opportunities.csv"})


@app.route("/api/status", methods=["POST"])
def api_set_status():
    data = request.get_json()
    set_status(int(data["id"]), data["status"])
    return jsonify({"ok": True})


@app.route("/api/run", methods=["POST"])
def api_run():
    if JOB_STATE["running"]:
        return jsonify({"ok": False, "error": "A job is already running."}), 409
    task = request.get_json().get("task", "")
    task_map = {
        "scrape":   (["--scrape"],   "Scrape (DuckDuckGo + GeM)"),
        "analyse":  (["--analyse"],  "AI analysis"),
        "discover": (["--discover"], "Directory discovery (dirhunt)"),
        "enrich":   (["--enrich"],   "Extract PDF details"),
        "contacts": (["--contacts"], "Find procurement contacts"),
        "fix-urls": (["--fix-urls"], "Validate URLs"),
        "full":     ([],             "Full run (scrape + analyse)"),
    }
    if task not in task_map:
        return jsonify({"ok": False, "error": "Unknown task"}), 400
    args, name = task_map[task]
    threading.Thread(target=_run_engine, args=(args, name), daemon=True).start()
    return jsonify({"ok": True, "task": name})


@app.route("/api/job")
def api_job():
    return jsonify(JOB_STATE)


@app.route("/")
def index():
    return send_from_directory("ui", "index.html")


if __name__ == "__main__":
    init_db()
    ensure_status_column()
    ensure_columns()
    ensure_settings_table()
    ensure_outreach_table()
    port = int(os.environ.get("PORT", 5050))
    print("\n  Embroidery Opportunity Finder dashboard")
    print(f"  Open → http://localhost:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)

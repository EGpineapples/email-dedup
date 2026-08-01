#!/usr/bin/env python3
"""
Email Toolkit — Flask UI
  Tab 1: Email Deduplication
  Tab 2: Password Generator
  Tab 3: TCGplayer Order Dashboard
"""

import re, os, io, secrets, string, json
import pandas as pd
from flask import Flask, render_template_string, request, send_file, jsonify

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

ICLOUD_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@icloud\.com", re.IGNORECASE)

# ── Email ────────────────────────────────────────────────────────────────────
def extract_from_text(text): return {m.lower() for m in ICLOUD_REGEX.findall(text)}
def extract_from_csv(fs):
    e = set()
    try:
        df = pd.read_csv(fs, dtype=str, on_bad_lines="skip")
        for c in df.columns: e.update(extract_from_text(df[c].dropna().str.cat(sep=" ")))
    except: pass
    return e
def extract_from_upload(fs):
    if fs.filename.lower().endswith(".csv"): return extract_from_csv(fs)
    return extract_from_text(fs.read().decode("utf-8", errors="replace"))
def compare(n, m): return n & m, n - m

# ── Passwords ────────────────────────────────────────────────────────────────
def generate_passwords(count, length=12, symbols=False):
    a = string.ascii_letters + string.digits + ("!@#$%&*_+-=" if symbols else "")
    return [''.join(secrets.choice(a) for _ in range(length)) for _ in range(count)]

# ── Game Detection ───────────────────────────────────────────────────────────
def detect_game(name):
    n = name.lower()
    if 'magic' in n or 'mtg' in n: return 'Magic'
    if 'pokémon' in n or 'pokemon' in n or 'pokmon' in n or 'pok ' in n: return 'Pokemon'
    if 'yu-gi-oh' in n or 'yugioh' in n or 'konami' in n: return 'YuGiOh'
    if 'one piece' in n: return 'One Piece'
    if 'gundam' in n: return 'Gundam'
    if 'riftbound' in n: return 'Riftbound'
    if 'kpop' in n or 'demon hunter' in n: return 'Kpop DH'
    return 'Other'

# ── TCGplayer Logic ──────────────────────────────────────────────────────────
def process_tcg_orders(pull_file, ship_file):
    ps = pd.read_csv(pull_file, dtype=str)
    se = pd.read_csv(ship_file)
    ps = ps[ps['Product Line'] != 'Orders Contained in Pull Sheet:'].copy()
    ps['Quantity'] = pd.to_numeric(ps['Quantity'], errors='coerce').fillna(0).astype(int)
    ov = dict(zip(se['Order #'].astype(str), se['Value Of Products'].astype(float)))
    products = []
    for _, row in ps.iterrows():
        oq = str(row.get('Order Quantity', ''))
        if oq == 'nan' or not oq.strip(): continue
        rev = 0.0
        for part in oq.split(' | '):
            if ':' not in part: continue
            oid = part.rsplit(':', 1)[0].strip()
            if oid in ov: rev += ov[oid]
        pl = str(row.get('Product Line', '')).strip()
        sn = str(row.get('Set', '')).strip()
        if sn == 'nan': sn = ''
        rd = str(row.get('Set Release Date', '')).strip()
        release = ''
        if rd and rd != 'nan':
            try:
                from datetime import datetime
                release = datetime.strptime(rd.split(' ')[0], '%m/%d/%Y').strftime('%Y-%m-%d')
            except: release = rd
        products.append(dict(product_line=pl, set=sn, product_name=str(row.get('Product Name','')).strip(),
                             quantity=int(row['Quantity']), revenue=round(rev,2), release_date=release))
    return products

def process_order_tracker(order_file):
    df = pd.read_csv(order_file)
    df['Qty'] = pd.to_numeric(df['Qty'], errors='coerce').fillna(0).astype(int)
    df['Total'] = pd.to_numeric(df['Total'], errors='coerce').fillna(0)
    groups = []
    for item, grp in df.groupby('Item'):
        tq = int(grp['Qty'].sum()); tc = round(float(grp['Total'].sum()), 2)
        ac = round(tc / tq, 2) if tq > 0 else 0
        groups.append(dict(item=str(item), qty=tq, total_cost=tc, avg_cost=ac,
                           retailers=grp['Retailer'].unique().tolist(), num_orders=len(grp),
                           game=detect_game(str(item))))
    groups.sort(key=lambda x: x['total_cost'], reverse=True)
    return groups

# ── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def index(): return render_template_string(HTML_TEMPLATE)

@app.route("/process", methods=["POST"])
def process():
    nf = request.files.get("new_batch")
    if not nf or not nf.filename: return jsonify(error="Upload a batch file."), 400
    ne = extract_from_upload(nf)
    hfs = request.files.getlist("history_files"); master = set()
    for f in hfs:
        if f and f.filename: master.update(extract_from_upload(f))
    if not any(f.filename for f in hfs): return jsonify(error="Upload history."), 400
    u, un = compare(ne, master)
    return jsonify(master_count=len(master), used=sorted(u), unused=sorted(un))

@app.route("/download/<kind>", methods=["POST"])
def download(kind):
    buf = io.BytesIO(("\n".join(request.json.get("emails",[])) + "\n").encode())
    return send_file(buf, as_attachment=True, download_name=f"{kind}_emails.txt", mimetype="text/plain")

@app.route("/generate-passwords", methods=["POST"])
def gen_pw():
    d = request.json
    return jsonify(passwords=generate_passwords(min(int(d.get("count",10)),10000), min(int(d.get("length",12)),128), bool(d.get("symbols"))))

@app.route("/download-passwords", methods=["POST"])
def dl_pw():
    buf = io.BytesIO(("\n".join(request.json.get("passwords",[])) + "\n").encode())
    return send_file(buf, as_attachment=True, download_name="passwords.txt", mimetype="text/plain")

@app.route("/process-orders", methods=["POST"])
def process_orders():
    pf, sf = request.files.get("pull_sheet"), request.files.get("shipping_export")
    if not pf or not pf.filename: return jsonify(error="Upload Pull Sheet."), 400
    if not sf or not sf.filename: return jsonify(error="Upload Shipping Export."), 400
    try: return jsonify(products=process_tcg_orders(pf, sf))
    except Exception as e: return jsonify(error=str(e)), 400

@app.route("/process-order-tracker", methods=["POST"])
def process_tracker():
    of = request.files.get("order_tracker")
    if not of or not of.filename: return jsonify(error="Upload tracker."), 400
    try: return jsonify(groups=process_order_tracker(of))
    except Exception as e: return jsonify(error=str(e)), 400

# ── HTML ─────────────────────────────────────────────────────────────────────
with open(os.path.join(os.path.dirname(__file__) or '.', 'template.html'), 'r') as _f:
    _html = _f.read()
HTML_TEMPLATE = _html if os.path.exists(os.path.join(os.path.dirname(__file__) or '.', 'template.html')) else "<!-- template missing -->"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    if not os.environ.get("RENDER") and not os.environ.get("RAILWAY_ENVIRONMENT"):
        import webbrowser, threading
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    print(f"\n  ✦  Email Toolkit running on port {port}")
    print(f"  ✦  Press Ctrl+C to quit\n")
    app.run(host="0.0.0.0", debug=False, port=port)
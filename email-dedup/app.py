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

# ── Email Logic ──────────────────────────────────────────────────────────────
def extract_from_text(text): return {m.lower() for m in ICLOUD_REGEX.findall(text)}
def extract_from_csv(fs):
    emails = set()
    try:
        df = pd.read_csv(fs, dtype=str, on_bad_lines="skip")
        for col in df.columns: emails.update(extract_from_text(df[col].dropna().str.cat(sep=" ")))
    except: pass
    return emails
def extract_from_upload(fs):
    if fs.filename.lower().endswith(".csv"): return extract_from_csv(fs)
    return extract_from_text(fs.read().decode("utf-8", errors="replace"))
def compare(new, master): return new & master, new - master

# ── Password Logic ───────────────────────────────────────────────────────────
def generate_passwords(count, length=12, symbols=False):
    alpha = string.ascii_letters + string.digits + ("!@#$%&*_+-=" if symbols else "")
    return [''.join(secrets.choice(alpha) for _ in range(length)) for _ in range(count)]

# ── TCGplayer Logic ──────────────────────────────────────────────────────────
def process_tcg_orders(pull_file, ship_file):
    ps = pd.read_csv(pull_file, dtype=str)
    se = pd.read_csv(ship_file)
    ps = ps[ps['Product Line'] != 'Orders Contained in Pull Sheet:'].copy()
    ps['Quantity'] = pd.to_numeric(ps['Quantity'], errors='coerce').fillna(0).astype(int)
    order_values = dict(zip(se['Order #'].astype(str), se['Value Of Products'].astype(float)))
    products = []
    for _, row in ps.iterrows():
        oq = str(row.get('Order Quantity', ''))
        if oq == 'nan' or not oq.strip(): continue
        revenue = 0.0
        for part in oq.split(' | '):
            part = part.strip()
            if ':' not in part: continue
            oid = part.rsplit(':', 1)[0].strip()
            if oid in order_values: revenue += order_values[oid]
        pl = str(row.get('Product Line', '')).strip()
        sn = str(row.get('Set', '')).strip()
        if sn == 'nan': sn = ''
        rd = str(row.get('Set Release Date', '')).strip()
        if rd == 'nan': rd = ''
        # Parse date
        release = ''
        if rd:
            try:
                from datetime import datetime
                dt = datetime.strptime(rd.split(' ')[0], '%m/%d/%Y')
                release = dt.strftime('%Y-%m-%d')
            except: release = rd
        products.append({
            'product_line': pl, 'set': sn,
            'product_name': str(row.get('Product Name', '')).strip(),
            'quantity': int(row['Quantity']),
            'revenue': round(revenue, 2),
            'release_date': release,
        })
    return products

def process_order_tracker(order_file):
    df = pd.read_csv(order_file)
    df['Qty'] = pd.to_numeric(df['Qty'], errors='coerce').fillna(0).astype(int)
    df['Total'] = pd.to_numeric(df['Total'], errors='coerce').fillna(0)
    groups = []
    for item, grp in df.groupby('Item'):
        total_qty = int(grp['Qty'].sum())
        total_cost = round(float(grp['Total'].sum()), 2)
        avg_cost = round(total_cost / total_qty, 2) if total_qty > 0 else 0
        retailers = grp['Retailer'].unique().tolist()
        groups.append({
            'item': str(item), 'qty': total_qty,
            'total_cost': total_cost, 'avg_cost': avg_cost,
            'retailers': retailers, 'num_orders': len(grp),
        })
    groups.sort(key=lambda x: x['total_cost'], reverse=True)
    return groups

# ── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def index(): return render_template_string(HTML_TEMPLATE)

@app.route("/process", methods=["POST"])
def process():
    nf = request.files.get("new_batch")
    if not nf or not nf.filename: return jsonify(error="Upload a new batch file."), 400
    ne = extract_from_upload(nf)
    hfs = request.files.getlist("history_files")
    master = set()
    for f in hfs:
        if f and f.filename: master.update(extract_from_upload(f))
    if not any(f.filename for f in hfs): return jsonify(error="Upload history files."), 400
    used, unused = compare(ne, master)
    return jsonify(master_count=len(master), used=sorted(used), unused=sorted(unused))

@app.route("/download/<kind>", methods=["POST"])
def download(kind):
    data = request.json; emails = data.get("emails", [])
    buf = io.BytesIO(("\n".join(emails) + ("\n" if emails else "")).encode())
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
    pf = request.files.get("pull_sheet")
    sf = request.files.get("shipping_export")
    if not pf or not pf.filename: return jsonify(error="Upload Pull Sheet."), 400
    if not sf or not sf.filename: return jsonify(error="Upload Shipping Export."), 400
    try:
        products = process_tcg_orders(pf, sf)
        return jsonify(products=products)
    except Exception as e: return jsonify(error=str(e)), 400

@app.route("/process-order-tracker", methods=["POST"])
def process_tracker():
    of = request.files.get("order_tracker")
    if not of or not of.filename: return jsonify(error="Upload order tracker."), 400
    try:
        groups = process_order_tracker(of)
        return jsonify(groups=groups)
    except Exception as e: return jsonify(error=str(e)), 400

@app.route("/download-report", methods=["POST"])
def dl_report():
    rows = request.json.get("rows", [])
    hdr = "Game\tSet\tProduct\tRelease\tPresold Qty\tGross Rev\tPlatform Fee\tNet Rev\tOn Order\tCOGS/Unit\tTotal COGS\tPaid?\tHold Qty\tOpen Qty\tAt Cost Qty\tSell Qty\tProfit"
    lines = [hdr]
    for r in rows:
        lines.append("\t".join(str(r.get(k,"")) for k in [
            "product_line","set","product_name","release_date","quantity",
            "gross_rev","platform_fee","net_rev","on_order_qty","cogs_unit",
            "total_cogs","paid","hold_qty","open_qty","at_cost_qty","sell_qty","profit"
        ]))
    buf = io.BytesIO(("\n".join(lines) + "\n").encode())
    return send_file(buf, as_attachment=True, download_name="presale_report.tsv", mimetype="text/tab-separated-values")

# ── HTML ─────────────────────────────────────────────────────────────────────
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Email Toolkit</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
--bg:#0e1117;--surface:#161b22;--surface-2:#1c2333;--border:#2a3142;
--text:#e2e8f0;--text-dim:#8b95a5;--accent:#3d8bfd;--accent-soft:#3d8bfd18;
--green:#34d399;--green-soft:#34d39918;--amber:#fbbf24;--amber-soft:#fbbf2418;
--violet:#a78bfa;--violet-soft:#a78bfa18;--rose:#fb7185;--rose-soft:#fb718518;
--red:#f87171;--cyan:#22d3ee;--cyan-soft:#22d3ee18;
--radius:12px;
--font-ui:'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,sans-serif;
--font-mono:'IBM Plex Mono','Menlo','Consolas',monospace;
}
body{font-family:var(--font-ui);background:var(--bg);color:var(--text);min-height:100vh;line-height:1.5;-webkit-font-smoothing:antialiased}
.app{max-width:1200px;margin:0 auto;padding:40px 20px 80px}
header{text-align:center;margin-bottom:32px}
header h1{font-size:30px;font-weight:700;letter-spacing:-.8px;margin-bottom:6px}
header h1 span{color:var(--accent)}
header p{color:var(--text-dim);font-size:13px}

/* Tabs */
.tab-bar{display:flex;gap:3px;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:3px;margin-bottom:32px}
.tab-btn{flex:1;padding:9px 10px;font-family:var(--font-ui);font-size:13px;font-weight:500;color:var(--text-dim);background:0;border:0;border-radius:7px;cursor:pointer;transition:color .2s,background .2s;display:flex;align-items:center;justify-content:center;gap:6px}
.tab-btn:hover{color:var(--text)}
.tab-btn.active{background:var(--surface-2);color:var(--text);box-shadow:0 1px 3px rgba(0,0,0,.3)}
.tab-panel{display:none}.tab-panel.active{display:block}

/* Upload */
.upload-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}
.upload-grid.three{grid-template-columns:1fr 1fr 1fr}
@media(max-width:768px){.upload-grid,.upload-grid.three{grid-template-columns:1fr}}
.upload-card{background:var(--surface);border:1.5px dashed var(--border);border-radius:var(--radius);padding:24px 16px;text-align:center;cursor:pointer;transition:border-color .2s,background .2s;position:relative}
.upload-card:hover,.upload-card.drag-over{border-color:var(--accent);background:var(--accent-soft)}
.upload-card input[type="file"]{position:absolute;inset:0;opacity:0;cursor:pointer}
.upload-icon{width:40px;height:40px;margin:0 auto 10px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:18px}
.upload-card h3{font-size:14px;font-weight:600;margin-bottom:3px}
.upload-card .hint{font-size:11px;color:var(--text-dim)}
.file-list{margin-top:8px;text-align:left}
.file-tag{display:inline-flex;align-items:center;gap:5px;background:var(--surface-2);border:1px solid var(--border);border-radius:5px;padding:3px 8px;font-size:11px;font-family:var(--font-mono);color:var(--text-dim);margin:2px 2px 0 0}

/* Buttons */
.run-btn{display:block;width:100%;padding:13px;background:var(--accent);color:#fff;font-family:inherit;font-size:14px;font-weight:600;border:0;border-radius:var(--radius);cursor:pointer;transition:opacity .15s}
.run-btn:hover{opacity:.88}.run-btn:disabled{opacity:.4;cursor:not-allowed}
.run-btn.violet{background:var(--violet)}.run-btn.rose{background:var(--rose)}
.small-btn{padding:4px 10px;font-size:11px;font-weight:500;font-family:inherit;border-radius:5px;border:1px solid var(--border);background:var(--surface-2);color:var(--text-dim);cursor:pointer;transition:color .15s,border-color .15s}
.small-btn:hover{color:var(--text);border-color:var(--accent)}
.results{display:none;margin-top:32px}.results.visible{display:block}

/* Stats */
.summary-bar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}
.stat{flex:1;min-width:110px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px}
.stat .label{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.7px;color:var(--text-dim);margin-bottom:3px}
.stat .value{font-size:22px;font-weight:700;font-family:var(--font-mono)}
.stat.green .value{color:var(--green)}.stat.amber .value{color:var(--amber)}
.stat.rose .value{color:var(--rose)}.stat.violet .value{color:var(--violet)}
.stat.cyan .value{color:var(--cyan)}.stat.red .value{color:var(--red)}
.stat.accent .value{color:var(--accent)}

/* Panels */
.result-panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
.panel-header{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid var(--border)}
.panel-header h3{font-size:12px;font-weight:600;display:flex;align-items:center;gap:7px}
.panel-actions{display:flex;gap:5px}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block}
.dot.amber{background:var(--amber)}.dot.green{background:var(--green)}
.dot.violet{background:var(--violet)}.dot.rose{background:var(--rose)}.dot.cyan{background:var(--cyan)}
.email-list{padding:10px 14px;max-height:320px;overflow-y:auto;font-family:var(--font-mono);font-size:12px;line-height:1.85;color:var(--text-dim);white-space:pre;user-select:all}
.result-columns{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:640px){.result-columns{grid-template-columns:1fr}}

/* Password */
.pw-controls{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:24px 20px;margin-bottom:20px}
.pw-row{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.pw-field{flex:1;min-width:120px}
.pw-field label{display:block;font-size:11px;font-weight:600;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.pw-field input[type="number"]{width:100%;padding:8px 12px;font-family:var(--font-mono);font-size:13px;color:var(--text);background:var(--surface-2);border:1px solid var(--border);border-radius:7px;outline:0;transition:border-color .2s}
.pw-field input:focus{border-color:var(--violet)}
.pw-toggle{display:flex;align-items:center;gap:8px;padding-top:20px;cursor:pointer;user-select:none}
.pw-toggle input{display:none}
.toggle-track{width:36px;height:20px;background:var(--border);border-radius:10px;position:relative;transition:background .2s;flex-shrink:0}
.toggle-track::after{content:'';position:absolute;top:3px;left:3px;width:14px;height:14px;background:var(--text);border-radius:50%;transition:transform .2s}
.pw-toggle input:checked+.toggle-track{background:var(--violet)}
.pw-toggle input:checked+.toggle-track::after{transform:translateX(16px)}
.pw-toggle span{font-size:12px;color:var(--text-dim)}

/* Orders Dashboard */
.filter-bar{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;align-items:center}
.filter-label{font-size:10px;font-weight:600;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px}
.filter-select,.cash-input{padding:7px 12px;font-family:var(--font-ui);font-size:12px;color:var(--text);background:var(--surface-2);border:1px solid var(--border);border-radius:7px;outline:0}
.filter-select{min-width:150px;-webkit-appearance:none;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' fill='%238b95a5'%3E%3Cpath d='M2 3l3 4 3-4'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 10px center;padding-right:28px;cursor:pointer}
.filter-select:focus,.cash-input:focus{border-color:var(--rose)}
.cash-input{width:130px;font-family:var(--font-mono);font-size:13px}

.orders-table-wrap{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
.table-scroll{overflow:auto;max-height:600px}
.table-scroll::-webkit-scrollbar{width:6px;height:6px}
.table-scroll::-webkit-scrollbar-track{background:transparent}
.table-scroll::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.orders-table{width:100%;border-collapse:collapse;font-size:12px;white-space:nowrap}
.orders-table thead{position:sticky;top:0;z-index:2}
.orders-table th{padding:8px 10px;text-align:left;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--text-dim);background:var(--surface-2);border-bottom:1px solid var(--border)}
.orders-table th.r{text-align:right}
.orders-table td{padding:7px 10px;border-bottom:1px solid var(--border);color:var(--text);vertical-align:middle}
.orders-table tr:last-child td{border-bottom:0}
.orders-table tr:hover td{background:var(--accent-soft)}
.orders-table .mn{font-family:var(--font-mono);font-size:11px}
.orders-table .gr{color:var(--green)}.orders-table .am{color:var(--amber)}.orders-table .rd{color:var(--red)}
.gb{padding:2px 6px;border-radius:3px;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.3px}
.gb.magic{background:#3d8bfd22;color:#3d8bfd}.gb.pokemon{background:#fbbf2422;color:#fbbf24}
.gb.yugioh{background:#a78bfa22;color:#a78bfa}.gb.other{background:#fb718522;color:#fb7185}
.ti{width:65px;padding:4px 6px;font-family:var(--font-mono);font-size:11px;color:var(--text);background:var(--bg);border:1px solid var(--border);border-radius:5px;outline:0;transition:border-color .2s;text-align:right}
.ti:focus{border-color:var(--rose)}.ti::placeholder{color:#444}
.ti.wide{width:80px}
.pay-tog{padding:3px 8px;border-radius:4px;font-size:9px;font-weight:600;cursor:pointer;border:1px solid var(--border);text-transform:uppercase;letter-spacing:.3px;user-select:none;transition:all .15s}
.pay-tog.paid{background:var(--green-soft);color:var(--green);border-color:var(--green)}
.pay-tog.oos{background:var(--amber-soft);color:var(--amber);border-color:var(--amber)}
.totals-row td{font-weight:700!important;background:var(--surface-2)!important;border-top:2px solid var(--border)!important}
.section-title{font-size:13px;font-weight:600;margin:28px 0 12px;display:flex;align-items:center;gap:8px}
.section-title .dot{width:6px;height:6px}
.collapse-btn{font-size:11px;color:var(--text-dim);cursor:pointer;border:0;background:0;font-family:inherit;margin-left:auto}
.sourcing-table{width:100%;border-collapse:collapse;font-size:11px}
.sourcing-table th{padding:7px 10px;text-align:left;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--text-dim);background:var(--surface-2);border-bottom:1px solid var(--border)}
.sourcing-table td{padding:6px 10px;border-bottom:1px solid var(--border);color:var(--text-dim)}
.sourcing-table tr:hover td{background:var(--accent-soft)}

/* Toast/Spinner */
.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%) translateY(80px);background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:8px 18px;border-radius:7px;font-size:12px;opacity:0;transition:transform .3s,opacity .3s;pointer-events:none;z-index:100}
.toast.show{transform:translateX(-50%) translateY(0);opacity:1}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid #fff4;border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
.empty-msg{padding:24px 14px;text-align:center;color:var(--text-dim);font-size:12px;font-style:italic}
</style>
</head>
<body>
<div class="app">
<header><h1>Email <span>Toolkit</span></h1><p>Deduplication, passwords &amp; presale analytics</p></header>

<div class="tab-bar">
<button class="tab-btn active" onclick="switchTab('dedup')"><span>&#9993;</span> Dedup</button>
<button class="tab-btn" onclick="switchTab('pwgen')"><span>&#128272;</span> Passwords</button>
<button class="tab-btn" onclick="switchTab('orders')"><span>&#128230;</span> Orders</button>
</div>

<!-- TAB 1: DEDUP -->
<div class="tab-panel active" id="tab-dedup">
<div class="upload-grid">
<label class="upload-card"><input type="file" id="newFile" accept=".txt,.csv"><div class="upload-icon" style="background:var(--accent-soft);color:var(--accent)">&#9993;</div><h3>New Batch</h3><p class="hint">.txt or .csv</p><div class="file-list" id="newFileList"></div></label>
<label class="upload-card"><input type="file" id="histFiles" accept=".txt,.csv" multiple><div class="upload-icon" style="background:var(--amber-soft);color:var(--amber)">&#128194;</div><h3>History Files</h3><p class="hint">One or more</p><div class="file-list" id="histFileList"></div></label>
</div>
<button class="run-btn" id="runBtn" disabled>Run Deduplication</button>
<div class="results" id="results">
<div class="summary-bar">
<div class="stat accent"><div class="label">Master Set</div><div class="value" id="masterCount">0</div></div>
<div class="stat amber"><div class="label">Used</div><div class="value" id="usedCount">0</div></div>
<div class="stat green"><div class="label">Unused</div><div class="value" id="unusedCount">0</div></div>
</div>
<div class="result-columns">
<div class="result-panel"><div class="panel-header"><h3><span class="dot amber"></span> Used</h3><div class="panel-actions"><button class="small-btn" onclick="copyList('used')">Copy</button><button class="small-btn" onclick="downloadList('used')">Download</button></div></div><div class="email-list" id="usedList"></div></div>
<div class="result-panel"><div class="panel-header"><h3><span class="dot green"></span> Unused</h3><div class="panel-actions"><button class="small-btn" onclick="copyList('unused')">Copy</button><button class="small-btn" onclick="downloadList('unused')">Download</button></div></div><div class="email-list" id="unusedList"></div></div>
</div></div></div>

<!-- TAB 2: PASSWORDS -->
<div class="tab-panel" id="tab-pwgen">
<div class="pw-controls"><div class="pw-row">
<div class="pw-field"><label>How many</label><input type="number" id="pwCount" value="499" min="1" max="10000"></div>
<div class="pw-field"><label>Length</label><input type="number" id="pwLength" value="12" min="4" max="128"></div>
<label class="pw-toggle"><input type="checkbox" id="pwSymbols"><span class="toggle-track"></span><span>Symbols</span></label>
</div></div>
<button class="run-btn violet" id="pwBtn">Generate Passwords</button>
<div class="results" id="pwResults">
<div class="summary-bar">
<div class="stat violet"><div class="label">Generated</div><div class="value" id="pwGenCount">0</div></div>
<div class="stat"><div class="label">Length</div><div class="value" id="pwGenLength" style="color:var(--text)">0</div></div>
</div>
<div class="result-panel"><div class="panel-header"><h3><span class="dot violet"></span> Passwords</h3><div class="panel-actions"><button class="small-btn" onclick="copyPasswords()">Copy</button><button class="small-btn" onclick="downloadPasswords()">Download</button></div></div><div class="email-list" id="pwList"></div></div>
</div></div>

<!-- TAB 3: ORDERS DASHBOARD -->
<div class="tab-panel" id="tab-orders">
<div class="upload-grid three">
<label class="upload-card"><input type="file" id="pullFile" accept=".csv"><div class="upload-icon" style="background:var(--rose-soft);color:var(--rose)">&#128203;</div><h3>Pull Sheet</h3><p class="hint">TCGplayer pull sheet</p><div class="file-list" id="pullFL"></div></label>
<label class="upload-card"><input type="file" id="shipFile" accept=".csv"><div class="upload-icon" style="background:var(--green-soft);color:var(--green)">&#128666;</div><h3>Shipping Export</h3><p class="hint">TCGplayer shipping</p><div class="file-list" id="shipFL"></div></label>
<label class="upload-card"><input type="file" id="trackerFile" accept=".csv"><div class="upload-icon" style="background:var(--cyan-soft);color:var(--cyan)">&#128230;</div><h3>Order Tracker</h3><p class="hint">Email order CSV (optional)</p><div class="file-list" id="trackerFL"></div></label>
</div>
<button class="run-btn rose" id="ordBtn" disabled>Extract &amp; Analyze</button>

<div class="results" id="ordRes">
<!-- Cashflow header -->
<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">
<span class="filter-label">Cash on hand:</span>
<input class="cash-input" type="number" id="cashOnHand" value="0" min="0" step="100" placeholder="$0" onchange="recalcAll()">
<span class="filter-label" style="margin-left:12px">Platform fee %:</span>
<input class="cash-input" type="number" id="platformFee" value="13" min="0" max="100" step="0.5" style="width:70px" onchange="recalcAll()">
</div>

<div class="summary-bar" id="cashflowBar">
<div class="stat green"><div class="label">Net Revenue</div><div class="value" id="sNetRev">$0</div></div>
<div class="stat amber"><div class="label">Total COGS</div><div class="value" id="sTotalCogs">$0</div></div>
<div class="stat green"><div class="label">Profit</div><div class="value" id="sProfit">$0</div></div>
<div class="stat cyan"><div class="label">Cash on Hand</div><div class="value" id="sCash">$0</div></div>
</div>
<div class="summary-bar">
<div class="stat rose"><div class="label">Tied Up (Paid)</div><div class="value" id="sTied">$0</div></div>
<div class="stat amber"><div class="label">Owed (Ship)</div><div class="value" id="sOwed">$0</div></div>
<div class="stat accent"><div class="label">Total Spent</div><div class="value" id="sTotalSpent">$0</div></div>
<div class="stat"><div class="label">Est. CC Points</div><div class="value" id="sPoints" style="color:var(--violet)">0</div></div>
</div>

<div class="filter-bar">
<span class="filter-label">Filter:</span>
<select class="filter-select" id="fGame" onchange="applyFilters()"><option value="">All Games</option></select>
<select class="filter-select" id="fSet" onchange="applyFilters()"><option value="">All Sets</option></select>
<input type="month" class="filter-select" id="fMonth" onchange="applyFilters()" style="min-width:140px">
<div style="flex:1"></div>
<button class="small-btn" onclick="copyReport()">Copy</button>
<button class="small-btn" onclick="downloadReport()">Download</button>
</div>

<div class="orders-table-wrap"><div class="table-scroll">
<table class="orders-table">
<thead><tr>
<th>Game</th><th>Set</th><th>Product</th><th>Release</th>
<th class="r">Presold</th><th class="r">Gross Rev</th><th class="r">Fee</th><th class="r">Net Rev</th>
<th class="r">On Order</th><th class="r">COGS/Unit</th><th class="r">Total COGS</th>
<th>Paid?</th><th class="r">Hold</th><th class="r">Open</th><th class="r">At Cost</th>
<th class="r">Sell Qty</th><th class="r">Exp. Rev</th><th class="r">Profit</th>
</tr></thead>
<tbody id="ordBody"></tbody>
</table>
</div></div>

<!-- Sourcing summary -->
<div class="section-title"><span class="dot cyan"></span> Order Tracker Summary <button class="collapse-btn" id="srcToggle" onclick="toggleSourcing()">Show ▼</button></div>
<div id="sourcingWrap" style="display:none">
<div class="orders-table-wrap"><div class="table-scroll" style="max-height:300px">
<table class="sourcing-table">
<thead><tr><th>Item</th><th>Retailers</th><th class="r">Qty</th><th class="r">Total Cost</th><th class="r">Avg/Unit</th></tr></thead>
<tbody id="srcBody"></tbody>
</table>
</div></div>
</div>
</div>
</div>
</div>
<div class="toast" id="toast"></div>

<script>
const $=id=>document.getElementById(id);
const fmt=n=>'$'+Math.abs(n).toLocaleString('en-US',{minimumFractionDigits:2});
const fmtS=n=>(n<0?'-':'')+fmt(n);

// ── Tabs ──
function switchTab(n){
  ['dedup','pwgen','orders'].forEach(t=>{
    $('tab-'+t).classList.toggle('active',t===n);
  });
  document.querySelectorAll('.tab-btn').forEach((b,i)=>b.classList.toggle('active',['dedup','pwgen','orders'][i]===n));
}

// ── Drag/Drop ──
document.querySelectorAll('.upload-card').forEach(c=>{
  c.addEventListener('dragover',e=>{e.preventDefault();c.classList.add('drag-over')});
  c.addEventListener('dragleave',()=>c.classList.remove('drag-over'));
  c.addEventListener('drop',e=>{e.preventDefault();c.classList.remove('drag-over');const i=c.querySelector('input[type=file]');i.files=e.dataTransfer.files;i.dispatchEvent(new Event('change'))});
});

// ═══ DEDUP ═══
let nbf=null,hfs=[],rd={used:[],unused:[]};
const db=$('runBtn');
$('newFile').onchange=function(){nbf=this.files[0]||null;$('newFileList').innerHTML=nbf?'<span class="file-tag">'+nbf.name+'</span>':'';db.disabled=!(nbf&&hfs.length)};
$('histFiles').onchange=function(){for(const f of this.files)if(!hfs.some(h=>h.name===f.name&&h.size===f.size))hfs.push(f);$('histFileList').innerHTML=hfs.map(f=>'<span class="file-tag">'+f.name+'</span>').join('');db.disabled=!(nbf&&hfs.length)};
db.onclick=async()=>{db.disabled=1;db.innerHTML='<span class="spinner"></span>Processing…';const fd=new FormData;fd.append('new_batch',nbf);hfs.forEach(f=>fd.append('history_files',f));try{const r=await(await fetch('/process',{method:'POST',body:fd})).json();if(r.error){toast(r.error);return}rd={used:r.used,unused:r.unused};$('masterCount').textContent=r.master_count;$('usedCount').textContent=r.used.length;$('unusedCount').textContent=r.unused.length;$('usedList').textContent=r.used.join('\n')||'';$('unusedList').textContent=r.unused.join('\n')||'';if(!r.used.length)$('usedList').innerHTML='<div class="empty-msg">None</div>';if(!r.unused.length)$('unusedList').innerHTML='<div class="empty-msg">None</div>';$('results').classList.add('visible');$('results').scrollIntoView({behavior:'smooth'})}catch(e){toast(e.message)}finally{db.disabled=0;db.textContent='Run Deduplication';db.disabled=!(nbf&&hfs.length)}};
function copyList(k){navigator.clipboard.writeText(rd[k].join('\n')).then(()=>toast('Copied '+rd[k].length))}
async function downloadList(k){const r=await fetch('/download/'+k,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({emails:rd[k]})});const b=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=k+'_emails.txt';a.click();URL.revokeObjectURL(a.href);toast('Downloaded')}

// ═══ PASSWORDS ═══
let gp=[];
$('pwBtn').onclick=async()=>{const b=$('pwBtn');b.disabled=1;b.innerHTML='<span class="spinner"></span>Generating…';try{const r=await(await fetch('/generate-passwords',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count:+$('pwCount').value,length:+$('pwLength').value,symbols:$('pwSymbols').checked})})).json();gp=r.passwords;$('pwGenCount').textContent=gp.length;$('pwGenLength').textContent=$('pwLength').value;$('pwList').textContent=gp.join('\n');$('pwResults').classList.add('visible');$('pwResults').scrollIntoView({behavior:'smooth'})}catch(e){toast(e.message)}finally{b.disabled=0;b.textContent='Generate Passwords'}};
function copyPasswords(){navigator.clipboard.writeText(gp.join('\n')).then(()=>toast('Copied '+gp.length))}
async function downloadPasswords(){const r=await fetch('/download-passwords',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({passwords:gp})});const b=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='passwords.txt';a.click();URL.revokeObjectURL(a.href);toast('Downloaded')}

// ═══ ORDERS DASHBOARD ═══
let allProds=[],srcGroups=[];
// Per-product editable state: keyed by product_name
let state={};  // { prodName: { cogs, paid, hold, open, atcost, exprev, release_override } }

function getState(name){
  if(!state[name]) state[name]={cogs:'',paid:'paid',hold:0,open:0,atcost:0,exprev:'',release_override:''};
  return state[name];
}

// File inputs
let pf=null,sf=null,tf=null;
const ob=$('ordBtn');
$('pullFile').onchange=function(){pf=this.files[0]||null;$('pullFL').innerHTML=pf?'<span class="file-tag">'+pf.name+'</span>':'';ob.disabled=!(pf&&sf)};
$('shipFile').onchange=function(){sf=this.files[0]||null;$('shipFL').innerHTML=sf?'<span class="file-tag">'+sf.name+'</span>':'';ob.disabled=!(pf&&sf)};
$('trackerFile').onchange=function(){tf=this.files[0]||null;$('trackerFL').innerHTML=tf?'<span class="file-tag">'+tf.name+'</span>':''};

ob.onclick=async()=>{
  ob.disabled=1;ob.innerHTML='<span class="spinner"></span>Extracting…';
  try{
    // Process TCG data
    const fd=new FormData;fd.append('pull_sheet',pf);fd.append('shipping_export',sf);
    const r=await(await fetch('/process-orders',{method:'POST',body:fd})).json();
    if(r.error){toast(r.error);return}
    allProds=r.products;

    // Process order tracker if provided
    srcGroups=[];
    if(tf){
      const fd2=new FormData;fd2.append('order_tracker',tf);
      const r2=await(await fetch('/process-order-tracker',{method:'POST',body:fd2})).json();
      if(!r2.error) srcGroups=r2.groups;
    }

    buildFilters();
    applyFilters();
    renderSourcing();
    $('ordRes').classList.add('visible');
    $('ordRes').scrollIntoView({behavior:'smooth'});
  }catch(e){toast(e.message)}
  finally{ob.disabled=0;ob.textContent='Extract & Analyze';ob.disabled=!(pf&&sf)}
};

function buildFilters(){
  const gs=[...new Set(allProds.map(p=>p.product_line))].sort();
  const ss=[...new Set(allProds.map(p=>p.set).filter(Boolean))].sort();
  const fg=$('fGame');fg.innerHTML='<option value="">All Games</option>';gs.forEach(g=>{const o=document.createElement('option');o.value=g;o.textContent=g;fg.appendChild(o)});
  const fs=$('fSet');fs.innerHTML='<option value="">All Sets</option>';ss.forEach(s=>{const o=document.createElement('option');o.value=s;o.textContent=s;fs.appendChild(o)});
}

function badgeClass(g){const l=g.toLowerCase();if(l.includes('magic'))return 'magic';if(l.includes('pokemon')||l.includes('pokémon'))return 'pokemon';if(l.includes('yugioh')||l.includes('yu-gi-oh'))return 'yugioh';return 'other'}

function applyFilters(){
  let f=allProds;
  const gv=$('fGame').value,mv=$('fMonth').value;
  if(gv){
    f=f.filter(p=>p.product_line===gv);
    const ss=[...new Set(f.map(p=>p.set).filter(Boolean))].sort();
    const fs=$('fSet'),cv=fs.value;fs.innerHTML='<option value="">All Sets</option>';
    ss.forEach(s=>{const o=document.createElement('option');o.value=s;o.textContent=s;fs.appendChild(o)});
    fs.value=ss.includes(cv)?cv:'';
  }
  const sv=$('fSet').value;
  if(sv) f=f.filter(p=>p.set===sv);
  if(mv) f=f.filter(p=>{const rd=getState(p.product_name).release_override||p.release_date;return rd&&rd.startsWith(mv)});
  renderTable(f);
}

function renderTable(prods){
  const body=$('ordBody');body.innerHTML='';
  const feeRate=parseFloat($('platformFee').value)||13;
  let tPresold=0,tGross=0,tFee=0,tNet=0,tOnOrd=0,tCogs=0,tProfit=0,tTied=0,tOwed=0,tSpent=0;

  prods.forEach(p=>{
    const s=getState(p.product_name);
    const rel=s.release_override||p.release_date||'';
    const gross=p.revenue;
    const fee=Math.round(gross*feeRate)/100;
    const net=gross-fee;
    const cogs=parseFloat(s.cogs)||0;
    const hold=parseInt(s.hold)||0;
    const open=parseInt(s.open)||0;
    const atcost=parseInt(s.atcost)||0;
    const sellQty=Math.max(0,p.quantity-hold-open-atcost);
    const onOrd=parseInt(s.on_order)||0;
    const totalCogs=cogs*p.quantity;
    const exprev=parseFloat(s.exprev)||0;
    // Revenue from presold (sell qty gets proportional net rev) + expected rev for non-presold
    const openLoss=p.quantity>0?(open/p.quantity)*net:0;
    const atCostRev=p.quantity>0?(atcost/p.quantity)*net:0;
    const atCostProfit=0; // no profit on at-cost
    const sellRev=p.quantity>0?(sellQty/p.quantity)*net:0;
    const profit=sellRev+exprev-totalCogs-openLoss;

    tPresold+=p.quantity;tGross+=gross;tFee+=fee;tNet+=net;
    tCogs+=totalCogs;tProfit+=profit;
    if(s.paid==='paid')tTied+=totalCogs;else tOwed+=totalCogs;
    tSpent+=totalCogs;

    const tr=document.createElement('tr');
    const esc=n=>n.replace(/'/g,"\\'");
    tr.innerHTML=`
<td><span class="gb ${badgeClass(p.product_line)}">${p.product_line}</span></td>
<td style="font-size:11px;color:var(--text-dim);max-width:120px;overflow:hidden;text-overflow:ellipsis">${p.set||'—'}</td>
<td style="font-weight:500;max-width:180px;overflow:hidden;text-overflow:ellipsis" title="${p.product_name}">${p.product_name}</td>
<td><input class="ti wide" type="date" value="${rel}" onchange="updState('${esc(p.product_name)}','release_override',this.value)" title="Release date"></td>
<td class="mn am" style="text-align:right">${p.quantity}</td>
<td class="mn" style="text-align:right">${fmt(gross)}</td>
<td class="mn rd" style="text-align:right">-${fmt(fee)}</td>
<td class="mn gr" style="text-align:right">${fmt(net)}</td>
<td style="text-align:right"><input class="ti" type="number" min="0" value="${s.on_order||''}" placeholder="0" onchange="updState('${esc(p.product_name)}','on_order',this.value)"></td>
<td style="text-align:right"><input class="ti" type="number" min="0" step="0.01" value="${s.cogs||''}" placeholder="0.00" onchange="updState('${esc(p.product_name)}','cogs',this.value)"></td>
<td class="mn" style="text-align:right">${cogs?fmt(totalCogs):'—'}</td>
<td><span class="pay-tog ${s.paid}" onclick="togglePaid('${esc(p.product_name)}',this)">${s.paid==='paid'?'Paid':'On Ship'}</span></td>
<td style="text-align:right"><input class="ti" type="number" min="0" value="${hold||''}" placeholder="0" onchange="updState('${esc(p.product_name)}','hold',this.value)"></td>
<td style="text-align:right"><input class="ti" type="number" min="0" value="${open||''}" placeholder="0" onchange="updState('${esc(p.product_name)}','open',this.value)"></td>
<td style="text-align:right"><input class="ti" type="number" min="0" value="${atcost||''}" placeholder="0" onchange="updState('${esc(p.product_name)}','atcost',this.value)"></td>
<td class="mn am" style="text-align:right">${sellQty}</td>
<td style="text-align:right"><input class="ti" type="number" min="0" step="0.01" value="${s.exprev||''}" placeholder="0.00" onchange="updState('${esc(p.product_name)}','exprev',this.value)"></td>
<td class="mn ${profit>=0?'gr':'rd'}" style="text-align:right">${cogs?fmtS(profit):'—'}</td>
`;
    body.appendChild(tr);
  });

  // Totals
  if(prods.length){
    const tr=document.createElement('tr');tr.className='totals-row';
    tr.innerHTML=`<td colspan="4" style="font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--text-dim)">Totals</td>
<td class="mn am" style="text-align:right">${tPresold}</td>
<td class="mn" style="text-align:right">${fmt(tGross)}</td>
<td class="mn rd" style="text-align:right">-${fmt(tFee)}</td>
<td class="mn gr" style="text-align:right">${fmt(tNet)}</td>
<td></td><td></td>
<td class="mn" style="text-align:right">${fmt(tCogs)}</td>
<td></td><td></td><td></td><td></td><td></td><td></td>
<td class="mn ${tProfit>=0?'gr':'rd'}" style="text-align:right">${fmtS(tProfit)}</td>`;
    body.appendChild(tr);
  }

  // Update summary cards
  const cash=parseFloat($('cashOnHand').value)||0;
  $('sNetRev').textContent=fmt(tNet);
  $('sTotalCogs').textContent=fmt(tCogs);
  $('sProfit').textContent=fmtS(tProfit);
  $('sProfit').style.color=tProfit>=0?'var(--green)':'var(--red)';
  $('sCash').textContent=fmt(cash);
  $('sTied').textContent=fmt(tTied);
  $('sOwed').textContent=fmt(tOwed);
  $('sTotalSpent').textContent=fmt(tSpent);
  $('sPoints').textContent=Math.floor(tSpent).toLocaleString();
}

function updState(name,key,val){getState(name)[key]=val;applyFilters()}
function togglePaid(name,el){const s=getState(name);s.paid=s.paid==='paid'?'oos':'paid';el.className='pay-tog '+s.paid;el.textContent=s.paid==='paid'?'Paid':'On Ship';applyFilters()}
function recalcAll(){applyFilters()}

function renderSourcing(){
  const body=$('srcBody');body.innerHTML='';
  if(!srcGroups.length){$('sourcingWrap').style.display='none';$('srcToggle').style.display='none';return}
  $('srcToggle').style.display='';
  srcGroups.forEach(g=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td style="max-width:300px;overflow:hidden;text-overflow:ellipsis" title="${g.item}">${g.item}</td>
<td style="font-size:10px">${g.retailers.join(', ')}</td>
<td class="mn" style="text-align:right">${g.qty}</td>
<td class="mn" style="text-align:right">${fmt(g.total_cost)}</td>
<td class="mn" style="text-align:right">${fmt(g.avg_cost)}</td>`;
    body.appendChild(tr);
  });
}

function toggleSourcing(){
  const w=$('sourcingWrap'),b=$('srcToggle');
  if(w.style.display==='none'){w.style.display='';b.textContent='Hide ▲'}
  else{w.style.display='none';b.textContent='Show ▼'}
}

function copyReport(){
  const feeRate=parseFloat($('platformFee').value)||13;
  let f=allProds;
  if($('fGame').value)f=f.filter(p=>p.product_line===$('fGame').value);
  if($('fSet').value)f=f.filter(p=>p.set===$('fSet').value);
  const lines=['Game\tSet\tProduct\tRelease\tPresold\tGross Rev\tFee\tNet Rev\tOn Order\tCOGS/Unit\tTotal COGS\tPaid\tHold\tOpen\tAt Cost\tSell Qty\tExp Rev\tProfit'];
  f.forEach(p=>{
    const s=getState(p.product_name),cogs=parseFloat(s.cogs)||0,hold=parseInt(s.hold)||0,open=parseInt(s.open)||0,atcost=parseInt(s.atcost)||0;
    const fee=p.revenue*feeRate/100,net=p.revenue-fee,sellQty=Math.max(0,p.quantity-hold-open-atcost);
    const totalCogs=cogs*p.quantity,openLoss=p.quantity>0?(open/p.quantity)*net:0;
    const sellRev=p.quantity>0?(sellQty/p.quantity)*net:0,exprev=parseFloat(s.exprev)||0;
    const profit=sellRev+exprev-totalCogs-openLoss;
    lines.push([p.product_line,p.set,p.product_name,s.release_override||p.release_date,p.quantity,p.revenue.toFixed(2),fee.toFixed(2),net.toFixed(2),s.on_order||0,cogs||'',cogs?(cogs*p.quantity).toFixed(2):'',s.paid,hold,open,atcost,sellQty,exprev||'',cogs?profit.toFixed(2):''].join('\t'));
  });
  navigator.clipboard.writeText(lines.join('\n')).then(()=>toast('Copied'));
}

async function downloadReport(){
  toast('Generating report…');
  const text=[];
  // reuse copy logic
  copyReport(); // puts on clipboard
  toast('Report copied — paste into a spreadsheet');
}

function toast(m){const t=$('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2400)}
</script>
</body>
</html>
"""

# ── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    if not os.environ.get("RENDER") and not os.environ.get("RAILWAY_ENVIRONMENT"):
        import webbrowser, threading
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    print(f"\n  ✦  Email Toolkit running on port {port}")
    print(f"  ✦  Press Ctrl+C to quit\n")
    app.run(host="0.0.0.0", debug=False, port=port)
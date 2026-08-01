#!/usr/bin/env python3
"""
Email Toolkit — Flask UI
  Tab 1: Email Deduplication
  Tab 2: Password Generator
Run:  python app.py
Open: http://localhost:5000
"""

import re
import os
import io
import secrets
import string

import pandas as pd
from flask import Flask, render_template_string, request, send_file, jsonify

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

ICLOUD_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@icloud\.com", re.IGNORECASE)


# ── Email Logic ──────────────────────────────────────────────────────────────

def extract_from_text(text: str) -> set[str]:
    return {m.lower() for m in ICLOUD_REGEX.findall(text)}

def extract_from_csv(file_storage) -> set[str]:
    emails: set[str] = set()
    try:
        df = pd.read_csv(file_storage, dtype=str, on_bad_lines="skip")
        for col in df.columns:
            series_text = df[col].dropna().str.cat(sep=" ")
            emails.update(extract_from_text(series_text))
    except Exception:
        pass
    return emails

def extract_from_upload(file_storage) -> set[str]:
    filename = file_storage.filename.lower()
    if filename.endswith(".csv"):
        return extract_from_csv(file_storage)
    else:
        text = file_storage.read().decode("utf-8", errors="replace")
        return extract_from_text(text)

def compare(new_emails: set[str], master: set[str]):
    return new_emails & master, new_emails - master


# ── Password Logic ───────────────────────────────────────────────────────────

def generate_passwords(count: int, length: int = 12, use_symbols: bool = False) -> list[str]:
    alphabet = string.ascii_letters + string.digits
    if use_symbols:
        alphabet += "!@#$%&*_+-="
    return [''.join(secrets.choice(alphabet) for _ in range(length)) for _ in range(count)]


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/process", methods=["POST"])
def process():
    new_file = request.files.get("new_batch")
    if not new_file or not new_file.filename:
        return jsonify(error="Please upload a new batch file."), 400
    new_emails = extract_from_upload(new_file)

    history_files = request.files.getlist("history_files")
    master: set[str] = set()
    history_info = []
    for f in history_files:
        if f and f.filename:
            found = extract_from_upload(f)
            history_info.append({"name": f.filename, "count": len(found)})
            master.update(found)

    if not history_files or not any(f.filename for f in history_files):
        return jsonify(error="Please upload at least one history file."), 400

    used, unused = compare(new_emails, master)
    return jsonify(
        new_count=len(new_emails), master_count=len(master),
        used=sorted(used), unused=sorted(unused), history_info=history_info,
    )

@app.route("/download/<kind>", methods=["POST"])
def download(kind):
    data = request.json
    emails = data.get("emails", [])
    content = "\n".join(emails) + ("\n" if emails else "")
    buf = io.BytesIO(content.encode("utf-8"))
    return send_file(buf, as_attachment=True, download_name=f"{kind}_emails.txt", mimetype="text/plain")

@app.route("/generate-passwords", methods=["POST"])
def gen_passwords():
    data = request.json
    count = min(int(data.get("count", 10)), 10000)
    length = min(int(data.get("length", 12)), 128)
    use_symbols = bool(data.get("symbols", False))
    passwords = generate_passwords(count, length, use_symbols)
    return jsonify(passwords=passwords)

@app.route("/download-passwords", methods=["POST"])
def download_passwords():
    data = request.json
    passwords = data.get("passwords", [])
    content = "\n".join(passwords) + ("\n" if passwords else "")
    buf = io.BytesIO(content.encode("utf-8"))
    return send_file(buf, as_attachment=True, download_name="passwords.txt", mimetype="text/plain")


# ── HTML Template ────────────────────────────────────────────────────────────

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
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:        #0e1117;
    --surface:   #161b22;
    --surface-2: #1c2333;
    --border:    #2a3142;
    --text:      #e2e8f0;
    --text-dim:  #8b95a5;
    --accent:    #3d8bfd;
    --accent-soft:#3d8bfd18;
    --green:     #34d399;
    --green-soft:#34d39918;
    --amber:     #fbbf24;
    --amber-soft:#fbbf2418;
    --violet:    #a78bfa;
    --violet-soft:#a78bfa18;
    --red:       #f87171;
    --radius:    12px;
    --font-ui:   'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    --font-mono: 'IBM Plex Mono', 'Menlo', 'Consolas', monospace;
  }

  body {
    font-family: var(--font-ui);
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  .app {
    max-width: 960px;
    margin: 0 auto;
    padding: 48px 24px 80px;
  }

  header {
    text-align: center;
    margin-bottom: 36px;
  }

  header h1 {
    font-size: 32px;
    font-weight: 700;
    letter-spacing: -0.8px;
    margin-bottom: 8px;
  }

  header h1 span { color: var(--accent); }

  header p {
    color: var(--text-dim);
    font-size: 14px;
    letter-spacing: 0.1px;
  }

  /* ── Tabs ──────────────────────────────────────────── */

  .tab-bar {
    display: flex;
    gap: 4px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 4px;
    margin-bottom: 36px;
  }

  .tab-btn {
    flex: 1;
    padding: 10px 16px;
    font-family: var(--font-ui);
    font-size: 14px;
    font-weight: 500;
    color: var(--text-dim);
    background: transparent;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    transition: color 0.2s, background 0.2s;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
  }

  .tab-btn:hover { color: var(--text); }

  .tab-btn.active {
    background: var(--surface-2);
    color: var(--text);
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
  }

  .tab-icon {
    font-size: 16px;
    line-height: 1;
  }

  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  /* ── Upload Cards ─────────────────────────────────── */

  .upload-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 24px;
  }

  @media (max-width: 640px) {
    .upload-grid { grid-template-columns: 1fr; }
  }

  .upload-card {
    background: var(--surface);
    border: 1.5px dashed var(--border);
    border-radius: var(--radius);
    padding: 32px 24px;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
    position: relative;
  }

  .upload-card:hover,
  .upload-card.drag-over {
    border-color: var(--accent);
    background: var(--accent-soft);
  }

  .upload-card input[type="file"] {
    position: absolute;
    inset: 0;
    opacity: 0;
    cursor: pointer;
  }

  .upload-icon {
    width: 44px;
    height: 44px;
    margin: 0 auto 14px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
  }

  .upload-card:first-child .upload-icon {
    background: var(--accent-soft);
    color: var(--accent);
  }

  .upload-card:last-child .upload-icon {
    background: var(--amber-soft);
    color: var(--amber);
  }

  .upload-card h3 { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
  .upload-card .hint { font-size: 12px; color: var(--text-dim); }

  .file-list { margin-top: 12px; text-align: left; }

  .file-tag {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    font-family: var(--font-mono);
    color: var(--text-dim);
    margin: 3px 3px 0 0;
  }

  .file-tag .x {
    cursor: pointer;
    color: var(--red);
    font-weight: 700;
    font-family: var(--font-ui);
  }

  /* ── Buttons ────────────────────────────────────────── */

  .run-btn {
    display: block;
    width: 100%;
    padding: 14px;
    background: var(--accent);
    color: #fff;
    font-family: inherit;
    font-size: 15px;
    font-weight: 600;
    border: none;
    border-radius: var(--radius);
    cursor: pointer;
    transition: opacity 0.15s;
  }

  .run-btn:hover { opacity: 0.88; }
  .run-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  .run-btn.violet { background: var(--violet); }

  /* ── Results ────────────────────────────────────────── */

  .results { display: none; margin-top: 40px; }
  .results.visible { display: block; }

  .summary-bar {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 24px;
  }

  .stat {
    flex: 1;
    min-width: 140px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 20px;
  }

  .stat .label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--text-dim);
    margin-bottom: 4px;
  }

  .stat .value {
    font-size: 26px;
    font-weight: 700;
    font-family: var(--font-mono);
  }

  .stat.used .value   { color: var(--amber); }
  .stat.unused .value  { color: var(--green); }
  .stat.master .value  { color: var(--accent); }
  .stat.gen .value     { color: var(--violet); }

  .result-columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }

  @media (max-width: 640px) {
    .result-columns { grid-template-columns: 1fr; }
  }

  .result-panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
  }

  .panel-header h3 {
    font-size: 13px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    display: inline-block;
  }

  .dot.amber  { background: var(--amber); }
  .dot.green  { background: var(--green); }
  .dot.violet { background: var(--violet); }

  .panel-actions { display: flex; gap: 6px; }

  .small-btn {
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
    font-family: inherit;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface-2);
    color: var(--text-dim);
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
  }

  .small-btn:hover {
    color: var(--text);
    border-color: var(--accent);
  }

  .email-list {
    padding: 12px 16px;
    max-height: 360px;
    overflow-y: auto;
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 1.85;
    color: var(--text-dim);
    white-space: pre;
    user-select: all;
  }

  .email-list::-webkit-scrollbar { width: 6px; }
  .email-list::-webkit-scrollbar-track { background: transparent; }
  .email-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

  .empty-msg {
    padding: 32px 16px;
    text-align: center;
    color: var(--text-dim);
    font-size: 13px;
    font-style: italic;
  }

  /* ── Password Generator ─────────────────────────────── */

  .pw-controls {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 28px 24px;
    margin-bottom: 24px;
  }

  .pw-row {
    display: flex;
    align-items: center;
    gap: 20px;
    flex-wrap: wrap;
  }

  .pw-field {
    flex: 1;
    min-width: 140px;
  }

  .pw-field label {
    display: block;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    margin-bottom: 8px;
  }

  .pw-field input[type="number"] {
    width: 100%;
    padding: 10px 14px;
    font-family: var(--font-mono);
    font-size: 14px;
    color: var(--text);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 8px;
    outline: none;
    transition: border-color 0.2s;
  }

  .pw-field input[type="number"]:focus {
    border-color: var(--violet);
  }

  .pw-toggle {
    display: flex;
    align-items: center;
    gap: 10px;
    padding-top: 24px;
    cursor: pointer;
    user-select: none;
  }

  .pw-toggle input { display: none; }

  .toggle-track {
    width: 40px;
    height: 22px;
    background: var(--border);
    border-radius: 11px;
    position: relative;
    transition: background 0.2s;
    flex-shrink: 0;
  }

  .toggle-track::after {
    content: '';
    position: absolute;
    top: 3px; left: 3px;
    width: 16px; height: 16px;
    background: var(--text);
    border-radius: 50%;
    transition: transform 0.2s;
  }

  .pw-toggle input:checked + .toggle-track {
    background: var(--violet);
  }

  .pw-toggle input:checked + .toggle-track::after {
    transform: translateX(18px);
  }

  .pw-toggle span {
    font-size: 13px;
    color: var(--text-dim);
  }

  /* ── Toast / Spinner ────────────────────────────────── */

  .toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%) translateY(80px);
    background: var(--surface-2);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 10px 20px;
    border-radius: 8px;
    font-size: 13px;
    opacity: 0;
    transition: transform 0.3s, opacity 0.3s;
    pointer-events: none;
    z-index: 100;
  }

  .toast.show {
    transform: translateX(-50%) translateY(0);
    opacity: 1;
  }

  .spinner {
    display: inline-block;
    width: 16px; height: 16px;
    border: 2px solid #fff4;
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
    vertical-align: middle;
    margin-right: 8px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="app">

  <header>
    <h1>Email <span>Toolkit</span></h1>
    <p>Deduplication &amp; password generation in one place</p>
  </header>

  <!-- Tab Bar -->
  <div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab('dedup')">
      <span class="tab-icon">&#9993;</span> Deduplication
    </button>
    <button class="tab-btn" onclick="switchTab('pwgen')">
      <span class="tab-icon">&#128272;</span> Password Generator
    </button>
  </div>

  <!-- ═══════════ TAB 1: Dedup ═══════════ -->
  <div class="tab-panel active" id="tab-dedup">
    <div class="upload-grid">
      <label class="upload-card" id="newCard">
        <input type="file" id="newFile" accept=".txt,.csv">
        <div class="upload-icon">&#9993;</div>
        <h3>New Batch</h3>
        <p class="hint">Drop or click — .txt or .csv</p>
        <div class="file-list" id="newFileList"></div>
      </label>
      <label class="upload-card" id="histCard">
        <input type="file" id="histFiles" accept=".txt,.csv" multiple>
        <div class="upload-icon">&#128194;</div>
        <h3>History Files</h3>
        <p class="hint">One or more .csv / .txt files</p>
        <div class="file-list" id="histFileList"></div>
      </label>
    </div>

    <button class="run-btn" id="runBtn" disabled>Run Deduplication</button>

    <div class="results" id="results">
      <div class="summary-bar">
        <div class="stat master">
          <div class="label">Master Set</div>
          <div class="value" id="masterCount">0</div>
        </div>
        <div class="stat used">
          <div class="label">Used</div>
          <div class="value" id="usedCount">0</div>
        </div>
        <div class="stat unused">
          <div class="label">Unused</div>
          <div class="value" id="unusedCount">0</div>
        </div>
      </div>
      <div class="result-columns">
        <div class="result-panel">
          <div class="panel-header">
            <h3><span class="dot amber"></span> Used Emails</h3>
            <div class="panel-actions">
              <button class="small-btn" onclick="copyList('used')">Copy</button>
              <button class="small-btn" onclick="downloadList('used')">Download</button>
            </div>
          </div>
          <div class="email-list" id="usedList"></div>
        </div>
        <div class="result-panel">
          <div class="panel-header">
            <h3><span class="dot green"></span> Unused Emails</h3>
            <div class="panel-actions">
              <button class="small-btn" onclick="copyList('unused')">Copy</button>
              <button class="small-btn" onclick="downloadList('unused')">Download</button>
            </div>
          </div>
          <div class="email-list" id="unusedList"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- ═══════════ TAB 2: Password Generator ═══════════ -->
  <div class="tab-panel" id="tab-pwgen">
    <div class="pw-controls">
      <div class="pw-row">
        <div class="pw-field">
          <label>How many</label>
          <input type="number" id="pwCount" value="499" min="1" max="10000">
        </div>
        <div class="pw-field">
          <label>Length</label>
          <input type="number" id="pwLength" value="12" min="4" max="128">
        </div>
        <label class="pw-toggle">
          <input type="checkbox" id="pwSymbols">
          <span class="toggle-track"></span>
          <span>Include symbols</span>
        </label>
      </div>
    </div>

    <button class="run-btn violet" id="pwBtn">Generate Passwords</button>

    <div class="results" id="pwResults">
      <div class="summary-bar">
        <div class="stat gen">
          <div class="label">Generated</div>
          <div class="value" id="pwGenCount">0</div>
        </div>
        <div class="stat">
          <div class="label">Length</div>
          <div class="value" id="pwGenLength" style="color:var(--text);">0</div>
        </div>
      </div>
      <div class="result-panel">
        <div class="panel-header">
          <h3><span class="dot violet"></span> Passwords</h3>
          <div class="panel-actions">
            <button class="small-btn" onclick="copyPasswords()">Copy All</button>
            <button class="small-btn" onclick="downloadPasswords()">Download</button>
          </div>
        </div>
        <div class="email-list" id="pwList"></div>
      </div>
    </div>
  </div>

</div>

<div class="toast" id="toast"></div>

<script>
  const $ = id => document.getElementById(id);

  // ── Tabs ──────────────────────────────────────────────
  function switchTab(name) {
    document.querySelectorAll('.tab-btn').forEach((b, i) => {
      b.classList.toggle('active', (name === 'dedup' ? i === 0 : i === 1));
    });
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    $('tab-' + name).classList.add('active');
  }

  // ── Dedup State ───────────────────────────────────────
  let newBatchFile = null;
  let historyFiles = [];
  let resultData = { used: [], unused: [] };
  const btn = $("runBtn");

  document.querySelectorAll(".upload-card").forEach(card => {
    card.addEventListener("dragover",  e => { e.preventDefault(); card.classList.add("drag-over"); });
    card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
    card.addEventListener("drop", e => {
      e.preventDefault();
      card.classList.remove("drag-over");
      const input = card.querySelector("input[type=file]");
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event("change"));
    });
  });

  $("newFile").addEventListener("change", function () {
    newBatchFile = this.files[0] || null;
    renderFileTags("newFileList", newBatchFile ? [newBatchFile] : [], "new");
    checkReady();
  });

  $("histFiles").addEventListener("change", function () {
    for (const f of this.files) {
      if (!historyFiles.some(h => h.name === f.name && h.size === f.size))
        historyFiles.push(f);
    }
    renderFileTags("histFileList", historyFiles, "hist");
    checkReady();
  });

  function renderFileTags(containerId, files, kind) {
    const c = $(containerId);
    c.innerHTML = "";
    files.forEach((f, i) => {
      const tag = document.createElement("span");
      tag.className = "file-tag";
      tag.innerHTML = f.name + ' <span class="x" data-idx="' + i + '" data-kind="' + kind + '">&times;</span>';
      c.appendChild(tag);
    });
    c.querySelectorAll(".x").forEach(x => x.addEventListener("click", e => {
      e.preventDefault(); e.stopPropagation();
      removeFile(x.dataset.kind, +x.dataset.idx);
    }));
  }

  function removeFile(kind, idx) {
    if (kind === "new") {
      newBatchFile = null; $("newFile").value = "";
      renderFileTags("newFileList", [], "new");
    } else {
      historyFiles.splice(idx, 1);
      renderFileTags("histFileList", historyFiles, "hist");
    }
    checkReady();
  }

  function checkReady() {
    btn.disabled = !(newBatchFile && historyFiles.length);
  }

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Processing…';
    const fd = new FormData();
    fd.append("new_batch", newBatchFile);
    historyFiles.forEach(f => fd.append("history_files", f));
    try {
      const res = await fetch("/process", { method: "POST", body: fd });
      const data = await res.json();
      if (data.error) { toast(data.error); return; }
      resultData = { used: data.used, unused: data.unused };
      $("masterCount").textContent = data.master_count;
      $("usedCount").textContent   = data.used.length;
      $("unusedCount").textContent  = data.unused.length;
      $("usedList").textContent   = data.used.join("\n")   || "";
      $("unusedList").textContent  = data.unused.join("\n") || "";
      if (!data.used.length)   $("usedList").innerHTML   = '<div class="empty-msg">No duplicates found</div>';
      if (!data.unused.length)  $("unusedList").innerHTML  = '<div class="empty-msg">All emails were used</div>';
      $("results").classList.add("visible");
      $("results").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      toast("Something went wrong: " + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Run Deduplication";
      checkReady();
    }
  });

  function copyList(kind) {
    const text = resultData[kind].join("\n");
    navigator.clipboard.writeText(text).then(() => toast("Copied " + resultData[kind].length + " emails"));
  }

  async function downloadList(kind) {
    const res = await fetch("/download/" + kind, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ emails: resultData[kind] }),
    });
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = kind + "_emails.txt";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("Downloaded " + kind + "_emails.txt");
  }

  // ── Password Generator ────────────────────────────────
  let generatedPasswords = [];

  $("pwBtn").addEventListener("click", async () => {
    const pbtn = $("pwBtn");
    pbtn.disabled = true;
    pbtn.innerHTML = '<span class="spinner"></span>Generating…';
    try {
      const res = await fetch("/generate-passwords", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          count:   +$("pwCount").value,
          length:  +$("pwLength").value,
          symbols: $("pwSymbols").checked,
        }),
      });
      const data = await res.json();
      generatedPasswords = data.passwords;
      $("pwGenCount").textContent  = data.passwords.length;
      $("pwGenLength").textContent = $("pwLength").value;
      $("pwList").textContent = data.passwords.join("\n");
      $("pwResults").classList.add("visible");
      $("pwResults").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      toast("Something went wrong: " + err.message);
    } finally {
      pbtn.disabled = false;
      pbtn.textContent = "Generate Passwords";
    }
  });

  function copyPasswords() {
    navigator.clipboard.writeText(generatedPasswords.join("\n"))
      .then(() => toast("Copied " + generatedPasswords.length + " passwords"));
  }

  async function downloadPasswords() {
    const res = await fetch("/download-passwords", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passwords: generatedPasswords }),
    });
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "passwords.txt";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("Downloaded passwords.txt");
  }

  // ── Toast ─────────────────────────────────────────────
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 2400);
  }
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
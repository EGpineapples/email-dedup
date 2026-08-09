#!/usr/bin/env python3
"""
Email Toolkit — Flask UI
  Tab 1: Duplicate Checker (emails, phones, cards, addresses)
  Tab 2: Password Generator
  Tab 3: TCGplayer Order Extractor
Run:  python app.py
Open: http://localhost:5000
"""

import re
import os
import io
import secrets
import string
import json
import csv
from collections import Counter

import pandas as pd
from flask import Flask, render_template_string, request, send_file, jsonify

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

ICLOUD_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@icloud\.com", re.IGNORECASE)
PHONE_REGEX = re.compile(
    r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)
CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


# ── Helpers ──────────────────────────────────────────────────────────────────

def normalize_phone(raw: str) -> str:
    """Strip to digits only. If 11 digits starting with 1, drop leading 1."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def read_file_lines(file_storage) -> list[str]:
    """Read uploaded file and return raw lines."""
    raw = file_storage.read()
    file_storage.seek(0)
    text = raw.decode("utf-8", errors="replace")
    return text.splitlines()


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


def analyze_file_internals(file_storage) -> dict:
    """Analyze a single file for total lines, emails found, and internal dupes."""
    raw = file_storage.read()
    file_storage.seek(0)
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total_lines = len(lines)

    all_matches = [m.lower() for m in ICLOUD_REGEX.findall(text)]
    unique_emails = set(all_matches)
    counts = Counter(all_matches)
    internal_dupes = {email: cnt for email, cnt in counts.items() if cnt > 1}

    return {
        "filename": file_storage.filename,
        "total_lines": total_lines,
        "emails_found": len(unique_emails),
        "total_matches": len(all_matches),
        "internal_dupes": internal_dupes,
        "unique_emails": unique_emails,
    }


# ── Phone Logic ──────────────────────────────────────────────────────────────

def extract_phones_from_text(text: str) -> list[str]:
    raw_matches = PHONE_REGEX.findall(text)
    return [normalize_phone(m) for m in raw_matches if len(normalize_phone(m)) >= 10]


def analyze_phone_dupes(file_storage) -> dict:
    raw = file_storage.read()
    file_storage.seek(0)
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    all_phones = extract_phones_from_text(text)
    counts = Counter(all_phones)
    internal_dupes = {p: c for p, c in counts.items() if c > 1}
    return {
        "filename": file_storage.filename,
        "total_lines": len(lines),
        "phones_found": len(set(all_phones)),
        "total_matches": len(all_phones),
        "internal_dupes": internal_dupes,
    }


# ── Card Logic ───────────────────────────────────────────────────────────────

def normalize_card(raw: str) -> str:
    return re.sub(r"[\s-]", "", raw)


def luhn_check(number: str) -> bool:
    """Basic Luhn check to filter out false positives."""
    digits = [int(d) for d in number]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    total = sum(odd_digits)
    for d in even_digits:
        total += sum(divmod(d * 2, 10))
    return total % 10 == 0


def extract_cards_from_text(text: str) -> list[str]:
    raw_matches = CARD_REGEX.findall(text)
    cards = []
    for m in raw_matches:
        norm = normalize_card(m)
        if 13 <= len(norm) <= 19 and luhn_check(norm):
            cards.append(norm)
    return cards


def analyze_card_dupes(file_storage) -> dict:
    raw = file_storage.read()
    file_storage.seek(0)
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    all_cards = extract_cards_from_text(text)
    counts = Counter(all_cards)
    internal_dupes = {c: cnt for c, cnt in counts.items() if cnt > 1}
    # Mask cards for display: show last 4 only
    masked_dupes = {}
    for card, cnt in internal_dupes.items():
        masked = "•" * (len(card) - 4) + card[-4:]
        masked_dupes[masked] = cnt
    return {
        "filename": file_storage.filename,
        "total_lines": len(lines),
        "cards_found": len(set(all_cards)),
        "total_matches": len(all_cards),
        "internal_dupes": masked_dupes,
    }


# ── Address Logic ────────────────────────────────────────────────────────────

def extract_addresses_from_csv(file_storage) -> dict:
    """
    Look for address columns in a CSV. Matches on columns containing
    'address', 'line 1', 'line 2', 'street', 'addr'.
    Returns analysis with internal duplicate addresses.
    """
    raw = file_storage.read()
    file_storage.seek(0)
    text = raw.decode("utf-8", errors="replace")

    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, on_bad_lines="skip")
    except Exception:
        return {
            "filename": file_storage.filename,
            "total_lines": len(text.splitlines()),
            "error": "Could not parse as CSV",
            "addresses_found": 0,
            "internal_dupes": {},
        }

    total_lines = len(text.splitlines())
    cols_lower = {c: c.lower().strip() for c in df.columns}

    # Find address line 1 and line 2 columns
    addr1_col = None
    addr2_col = None
    for orig, low in cols_lower.items():
        if any(k in low for k in ["address line 1", "address_line_1", "addr1", "address1", "street line 1", "street_1"]):
            addr1_col = orig
        elif any(k in low for k in ["address line 2", "address_line_2", "addr2", "address2", "street line 2", "street_2"]):
            addr2_col = orig
        elif addr1_col is None and any(k in low for k in ["address", "street", "addr"]):
            addr1_col = orig

    if addr1_col is None:
        # Fallback: try to find any column with "address" in name
        for orig, low in cols_lower.items():
            if "address" in low or "street" in low:
                addr1_col = orig
                break

    if addr1_col is None:
        return {
            "filename": file_storage.filename,
            "total_lines": total_lines,
            "error": "No address columns found. Expected columns containing 'address', 'street', or 'addr'.",
            "addresses_found": 0,
            "internal_dupes": {},
            "columns_found": list(df.columns),
        }

    # Build composite address keys
    addresses = []
    for _, row in df.iterrows():
        line1 = str(row.get(addr1_col, "")).strip().lower()
        line2 = str(row.get(addr2_col, "")).strip().lower() if addr2_col else ""
        if line1 and line1 != "nan":
            key = f"{line1}|{line2}" if line2 and line2 != "nan" else line1
            addresses.append(key)

    counts = Counter(addresses)
    internal_dupes = {}
    for addr, cnt in counts.items():
        if cnt > 1:
            display = addr.replace("|", " + ") if "|" in addr else addr
            internal_dupes[display] = cnt

    return {
        "filename": file_storage.filename,
        "total_lines": total_lines,
        "addr1_col": addr1_col,
        "addr2_col": addr2_col,
        "addresses_found": len(set(addresses)),
        "total_rows": len(addresses),
        "internal_dupes": internal_dupes,
    }


# ── Password Logic ───────────────────────────────────────────────────────────

def generate_passwords(count: int, length: int = 12, use_symbols: bool = False) -> list[str]:
    alphabet = string.ascii_letters + string.digits
    if use_symbols:
        alphabet += "!@#$%&*_+-="
    return [''.join(secrets.choice(alphabet) for _ in range(length)) for _ in range(count)]


# ── TCGplayer Order Logic ────────────────────────────────────────────────────

def process_tcg_orders(pull_sheet_file, shipping_file):
    ps = pd.read_csv(pull_sheet_file, dtype=str)
    se = pd.read_csv(shipping_file, dtype=str)

    order_value = {}
    for _, row in se.iterrows():
        oid = str(row.get("Order Number", row.get("Order #", ""))).strip()
        val = str(row.get("Value Of Products", row.get("Product Total", "0")))
        val = re.sub(r"[^\d.]", "", val)
        try:
            order_value[oid] = float(val)
        except ValueError:
            pass

    products = []
    for _, row in ps.iterrows():
        oq = str(row.get("Order Quantity", ""))
        parsed_orders = {}
        if oq and oq != "nan":
            for chunk in oq.split("|"):
                chunk = chunk.strip()
                if ":" in chunk:
                    parts = chunk.split(":")
                    parsed_orders[parts[0].strip()] = int(parts[1].strip()) if len(parts) > 1 else 1

        rev = sum(order_value.get(oid, 0) for oid in parsed_orders)
        qty = 0
        try:
            qty = int(row.get("Quantity", 0))
        except (ValueError, TypeError):
            pass

        name = str(row.get("Product Name", "Unknown"))
        game = detect_game(name + " " + str(row.get("Product Line", "")) + " " + str(row.get("Set", "")))

        products.append({
            "name": name,
            "set": str(row.get("Set", "")),
            "product_line": str(row.get("Product Line", "")),
            "game": game,
            "qty": qty,
            "orders": len(parsed_orders),
            "revenue": round(rev, 2),
            "release_date": str(row.get("Set Release Date", "")),
        })

    return products


def detect_game(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["magic", "mtg", "commander", "modern horizons", "foundations", "bloomburrow", "duskmourn", "aetherdrift"]):
        return "MTG"
    if any(k in t for k in ["pokemon", "pokémon", "pkmn", "scarlet", "violet", "prismatic"]):
        return "Pokemon"
    if any(k in t for k in ["yu-gi-oh", "yugioh", "ygo"]):
        return "YuGiOh"
    if any(k in t for k in ["star wars", "unlimited"]):
        return "SWU"
    if any(k in t for k in ["one piece"]):
        return "OnePiece"
    if any(k in t for k in ["lorcana", "disney"]):
        return "Lorcana"
    return "Other"


def process_order_tracker(tracker_file):
    df = pd.read_csv(tracker_file, dtype=str, on_bad_lines="skip")
    groups = []
    for _, row in df.iterrows():
        name = str(row.get("Item", row.get("item", "Unknown")))
        game = detect_game(name + " " + str(row.get("Retailer", "")))
        qty_raw = row.get("Qty", row.get("qty", "1"))
        total_raw = row.get("Total", row.get("total", "0"))
        try:
            qty = int(float(str(qty_raw).replace(",", "")))
        except (ValueError, TypeError):
            qty = 1
        try:
            total = float(re.sub(r"[^\d.]", "", str(total_raw)))
        except (ValueError, TypeError):
            total = 0

        groups.append({
            "name": name,
            "game": game,
            "qty": qty,
            "total": round(total, 2),
            "retailer": str(row.get("Retailer", row.get("retailer", ""))),
            "order_num": str(row.get("Order #", row.get("order_num", ""))),
            "date": str(row.get("Date Ordered", row.get("date", ""))),
            "status": str(row.get("Status", row.get("status", ""))),
        })
    return groups


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/process", methods=["POST"])
def process():
    new_files = request.files.getlist("new_batch")
    hist_files = request.files.getlist("history_files")

    if not new_files or not new_files[0].filename:
        return jsonify(error="Upload at least one new-batch file"), 400

    # ── Analyze each file individually ──
    file_reports = []

    # Analyze new batch files
    new_emails_all: set[str] = set()
    for f in new_files:
        report = analyze_file_internals(f)
        report["role"] = "new_batch"
        file_reports.append(report)
        new_emails_all.update(report["unique_emails"])
        f.seek(0)

    # Analyze history files
    master: set[str] = set()
    for f in hist_files:
        if f.filename:
            report = analyze_file_internals(f)
            report["role"] = "history"
            file_reports.append(report)
            master.update(report["unique_emails"])
            f.seek(0)

    used, unused = compare(new_emails_all, master)

    # Strip unique_emails sets from reports (not JSON serializable & not needed)
    for r in file_reports:
        r.pop("unique_emails", None)
        # Convert internal_dupes keys to sorted list for consistent display
        r["internal_dupes"] = dict(sorted(r["internal_dupes"].items()))

    return jsonify(
        used=sorted(used),
        unused=sorted(unused),
        master_size=len(master),
        new_size=len(new_emails_all),
        file_reports=file_reports,
    )


@app.route("/check-phones", methods=["POST"])
def check_phones():
    files = request.files.getlist("phone_files")
    if not files or not files[0].filename:
        return jsonify(error="Upload at least one file"), 400

    reports = []
    all_phones: list[str] = []
    for f in files:
        report = analyze_phone_dupes(f)
        reports.append(report)
        all_phones.extend(extract_phones_from_text(
            f.read().decode("utf-8", errors="replace")
        ))
        f.seek(0)

    # Cross-file dupes
    cross_counts = Counter(all_phones)
    cross_dupes = {p: c for p, c in cross_counts.items() if c > 1}

    return jsonify(
        reports=reports,
        cross_file_dupes=cross_dupes if len(files) > 1 else {},
        total_unique=len(set(all_phones)),
        total_found=len(all_phones),
    )


@app.route("/check-cards", methods=["POST"])
def check_cards():
    files = request.files.getlist("card_files")
    if not files or not files[0].filename:
        return jsonify(error="Upload at least one file"), 400

    reports = []
    all_cards: list[str] = []
    for f in files:
        report = analyze_card_dupes(f)
        reports.append(report)
        f.seek(0)
        all_cards.extend(extract_cards_from_text(
            f.read().decode("utf-8", errors="replace")
        ))
        f.seek(0)

    cross_counts = Counter(all_cards)
    cross_dupes = {}
    for card, cnt in cross_counts.items():
        if cnt > 1:
            masked = "•" * (len(card) - 4) + card[-4:]
            cross_dupes[masked] = cnt

    return jsonify(
        reports=reports,
        cross_file_dupes=cross_dupes if len(files) > 1 else {},
        total_unique=len(set(all_cards)),
        total_found=len(all_cards),
    )


@app.route("/check-addresses", methods=["POST"])
def check_addresses():
    files = request.files.getlist("address_files")
    if not files or not files[0].filename:
        return jsonify(error="Upload at least one CSV file"), 400

    reports = []
    for f in files:
        if f.filename:
            report = extract_addresses_from_csv(f)
            reports.append(report)
            f.seek(0)

    return jsonify(reports=reports)


@app.route("/generate-passwords", methods=["POST"])
def gen_passwords():
    data = request.get_json()
    count = min(int(data.get("count", 5)), 100)
    length = min(int(data.get("length", 12)), 128)
    symbols = bool(data.get("symbols", False))
    return jsonify(passwords=generate_passwords(count, length, symbols))


@app.route("/process-orders", methods=["POST"])
def orders():
    ps = request.files.get("pull_sheet")
    se = request.files.get("shipping_export")
    if not ps or not se:
        return jsonify(error="Upload both Pull Sheet and Shipping Export CSVs"), 400
    try:
        return jsonify(products=process_tcg_orders(ps, se))
    except Exception as e:
        return jsonify(error=str(e)), 400


@app.route("/process-order-tracker", methods=["POST"])
def order_tracker():
    of = request.files.get("order_tracker")
    if not of:
        return jsonify(error="Upload an order tracker CSV"), 400
    try:
        return jsonify(groups=process_order_tracker(of))
    except Exception as e:
        return jsonify(error=str(e)), 400


@app.route("/download/<kind>")
def download(kind):
    data = request.args.get("data", "")
    fname = f"{kind}_emails.txt"
    buf = io.BytesIO(data.encode("utf-8"))
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=fname, mimetype="text/plain")


# ── HTML ─────────────────────────────────────────────────────────────────────
_template_path = os.path.join(os.path.dirname(__file__) or '.', 'template.html')
if os.path.exists(_template_path):
    with open(_template_path, 'r') as _f:
        HTML_TEMPLATE = _f.read()
else:
    HTML_TEMPLATE = "<!-- template.html missing -->"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    if not os.environ.get("RENDER") and not os.environ.get("RAILWAY_ENVIRONMENT"):
        import webbrowser, threading
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    print(f"\n  ✦  Email Toolkit running on port {port}")
    print(f"  ✦  Press Ctrl+C to quit\n")
    app.run(host="0.0.0.0", debug=False, port=port)

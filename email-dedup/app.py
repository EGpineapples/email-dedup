#!/usr/bin/env python3
"""
Email Toolkit — Flask UI
  Tab 1: Duplicate Checker (emails, phones, cards, addresses)
  Tab 2: Password Generator
  Tab 3: TCGplayer Order Extractor
  Tab 4: Column Extractor
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

# Phone: 10-digit US numbers with optional +1 prefix
# Uses word boundaries to avoid matching inside longer digit strings (card numbers)
PHONE_REGEX = re.compile(
    r"(?<!\d)"                        # not preceded by a digit
    r"(?:\+?1[-.\s]?)?"               # optional country code
    r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
    r"(?!\d)",                        # not followed by a digit
    re.MULTILINE
)

CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


# ── Helpers ──────────────────────────────────────────────────────────────────

def normalize_phone(raw: str) -> str:
    """Strip to digits only. If 11 digits starting with 1, drop leading 1."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


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
        "all_emails": sorted(all_matches),  # full list for display
        "internal_dupes": internal_dupes,
        "unique_emails": unique_emails,
    }


# ── Phone Logic ──────────────────────────────────────────────────────────────

def _find_card_digit_spans(text: str) -> set[int]:
    """Return set of character positions occupied by card numbers."""
    spans = set()
    for m in CARD_REGEX.finditer(text):
        norm = re.sub(r"[\s-]", "", m.group())
        if 13 <= len(norm) <= 19 and luhn_check(norm):
            for i in range(m.start(), m.end()):
                spans.add(i)
    return spans


def extract_phones_from_text(text: str, exclude_card_spans: bool = True) -> list[str]:
    """Extract phones, skipping any that overlap with card number positions."""
    card_spans = _find_card_digit_spans(text) if exclude_card_spans else set()

    phones = []
    for m in PHONE_REGEX.finditer(text):
        # Skip if this match overlaps with a card number
        match_positions = set(range(m.start(), m.end()))
        if match_positions & card_spans:
            continue
        norm = normalize_phone(m.group())
        if len(norm) == 10:
            phones.append(norm)
    return phones


def analyze_phone_dupes(file_storage) -> dict:
    raw = file_storage.read()
    file_storage.seek(0)
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()

    # Try CSV first — dedupe phones within each row (billing + shipping = 1)
    filename = file_storage.filename.lower()
    if filename.endswith(".csv"):
        try:
            file_storage.seek(0)
            df = pd.read_csv(file_storage, dtype=str, on_bad_lines="skip")
            file_storage.seek(0)
            all_phones = []
            for _, row in df.iterrows():
                row_text = " ".join(str(v) for v in row.values if pd.notna(v))
                row_phones = extract_phones_from_text(row_text)
                # Dedupe within the row — same phone as billing & shipping counts once
                unique_in_row = list(dict.fromkeys(row_phones))
                all_phones.extend(unique_in_row)
        except Exception:
            all_phones = extract_phones_from_text(text)
    else:
        all_phones = extract_phones_from_text(text)

    counts = Counter(all_phones)
    internal_dupes = {p: c for p, c in counts.items() if c > 1}
    return {
        "filename": file_storage.filename,
        "total_lines": len(lines),
        "phones_found": len(set(all_phones)),
        "total_matches": len(all_phones),
        "internal_dupes": internal_dupes,
        "all_phones": all_phones,
    }


# ── Card Logic ───────────────────────────────────────────────────────────────

def normalize_card(raw: str) -> str:
    return re.sub(r"[\s-]", "", raw)


def luhn_check(number: str) -> bool:
    """Basic Luhn check to filter out false positives."""
    try:
        digits = [int(d) for d in number]
    except ValueError:
        return False
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
    # Mask cards for display
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
    Finds address columns in CSV. Matches ONLY on address line 1 + line 2.
    Name columns are completely ignored.
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

    # Find address line 1 and line 2 columns (explicitly skip name columns)
    addr1_col = None
    addr2_col = None

    # First pass: look for explicit "line 1" / "line 2" columns
    for orig, low in cols_lower.items():
        if any(k in low for k in ["address line 1", "address_line_1", "addr1",
                                   "address1", "street line 1", "street_1",
                                   "shipping address 1", "billing address 1"]):
            addr1_col = orig
        elif any(k in low for k in ["address line 2", "address_line_2", "addr2",
                                     "address2", "street line 2", "street_2",
                                     "shipping address 2", "billing address 2"]):
            addr2_col = orig

    # Second pass: fallback to generic "address" / "street" (but never "name")
    if addr1_col is None:
        for orig, low in cols_lower.items():
            if "name" in low:
                continue  # skip name columns
            if any(k in low for k in ["address", "street", "addr"]):
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

    # Build composite keys from address line 1 + line 2 ONLY (no name)
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

    # Clean reports for JSON
    for r in file_reports:
        r.pop("unique_emails", None)
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
    all_phones_global: list[str] = []
    for f in files:
        report = analyze_phone_dupes(f)
        reports.append(report)
        all_phones_global.extend(report["all_phones"])
        f.seek(0)

    # Strip all_phones from individual reports (not needed in response)
    for r in reports:
        r.pop("all_phones", None)

    # Cross-file dupes
    cross_counts = Counter(all_phones_global)
    cross_dupes = {p: c for p, c in cross_counts.items() if c > 1}

    return jsonify(
        reports=reports,
        cross_file_dupes=cross_dupes if len(files) > 1 else {},
        total_unique=len(set(all_phones_global)),
        total_found=len(all_phones_global),
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


@app.route("/extract-columns", methods=["POST"])
def extract_columns():
    """Parse an uploaded CSV, XLSX, or comma-separated TXT and return columns + all data."""
    f = request.files.get("col_file")
    if not f or not f.filename:
        return jsonify(error="Upload a file"), 400

    filename = f.filename.lower()
    try:
        if filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(f, dtype=str, engine="openpyxl")
        elif filename.endswith(".csv"):
            df = pd.read_csv(f, dtype=str, on_bad_lines="skip")
        elif filename.endswith(".txt"):
            raw = f.read().decode("utf-8", errors="replace")
            df = pd.read_csv(io.StringIO(raw), dtype=str, sep=",", on_bad_lines="skip")
        else:
            return jsonify(error="Unsupported file type. Use CSV, XLSX, or TXT."), 400
    except Exception as e:
        return jsonify(error=f"Could not parse file: {e}"), 400

    # Build column → values mapping
    columns = list(df.columns)
    data = {}
    for col in columns:
        values = df[col].fillna("").astype(str).tolist()
        # Strip whitespace, keep empty strings so row count is accurate
        data[col] = [v.strip() for v in values]

    return jsonify(
        filename=f.filename,
        columns=columns,
        data=data,
        total_rows=len(df),
    )


@app.route("/parse-keyvalue", methods=["POST"])
def parse_keyvalue():
    """Parse key=value text format. Each line is a record with space-separated Key=Value pairs."""
    data = request.get_json()
    text = data.get("text", "").strip()
    if not text:
        return jsonify(error="No text provided"), 400

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    all_records = []
    all_keys_ordered = []
    all_keys_set = set()

    for line in lines:
        record = {}
        # Find all =VALUE patterns and derive keys from text between them
        eq_matches = list(re.finditer(r'=(\S+)', line))
        for i, m in enumerate(eq_matches):
            value = m.group(1)
            eq_pos = m.start()
            if i == 0:
                key = line[:eq_pos].strip()
            else:
                prev_end = eq_matches[i - 1].end()
                key = line[prev_end:eq_pos].strip()
            if key:
                record[key] = value
                if key not in all_keys_set:
                    all_keys_set.add(key)
                    all_keys_ordered.append(key)

        if record:
            all_records.append(record)

    return jsonify(
        records=all_records,
        keys=all_keys_ordered,
        total_lines=len(lines),
        total_records=len(all_records),
    )


@app.route("/match-profiles", methods=["POST"])
def match_profiles():
    """Match profiles CSV against accounts CSV by email. Return matched profiles as downloadable CSV."""
    profiles_file = request.files.get("profiles_file")
    accounts_file = request.files.get("accounts_file")

    if not profiles_file or not profiles_file.filename:
        return jsonify(error="Upload a profiles file"), 400
    if not accounts_file or not accounts_file.filename:
        return jsonify(error="Upload an accounts file"), 400

    def read_df(f):
        fname = f.filename.lower()
        if fname.endswith((".xlsx", ".xls")):
            return pd.read_excel(f, dtype=str, engine="openpyxl")
        else:
            return pd.read_csv(f, dtype=str, on_bad_lines="skip")

    try:
        profiles_df = read_df(profiles_file)
    except Exception as e:
        return jsonify(error=f"Could not parse profiles file: {e}"), 400

    try:
        accounts_df = read_df(accounts_file)
    except Exception as e:
        return jsonify(error=f"Could not parse accounts file: {e}"), 400

    # Auto-detect email column in each dataframe
    def find_email_col(df, label):
        for col in df.columns:
            low = col.lower().strip()
            if "email" in low:
                return col
        # Fallback: scan values for anything that looks like an email
        email_re = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
        for col in df.columns:
            sample = df[col].dropna().head(20).astype(str)
            matches = sample.apply(lambda v: bool(email_re.search(v))).sum()
            if matches >= min(5, len(sample) * 0.5):
                return col
        return None

    profiles_email_col = find_email_col(profiles_df, "profiles")
    accounts_email_col = find_email_col(accounts_df, "accounts")

    if not profiles_email_col:
        return jsonify(error="Could not find an email column in the profiles file",
                       columns=list(profiles_df.columns)), 400
    if not accounts_email_col:
        return jsonify(error="Could not find an email column in the accounts file",
                       columns=list(accounts_df.columns)), 400

    # Build set of account emails (lowercased)
    account_emails = set(
        accounts_df[accounts_email_col].dropna().str.strip().str.lower()
    )

    # Match profiles whose email exists in accounts
    profiles_df["_email_lower"] = profiles_df[profiles_email_col].fillna("").str.strip().str.lower()
    matched = profiles_df[profiles_df["_email_lower"].isin(account_emails)].drop(columns=["_email_lower"])
    unmatched = profiles_df[~profiles_df["_email_lower"].isin(account_emails)].drop(columns=["_email_lower"])

    # Build CSV output for matched profiles
    csv_buf = io.StringIO()
    matched.to_csv(csv_buf, index=False)
    csv_text = csv_buf.getvalue()

    # Clean NaN values for JSON serialization
    preview = matched.head(20).fillna("").values.tolist()

    return jsonify(
        profiles_total=int(len(profiles_df)),
        accounts_total=int(len(accounts_df)),
        account_emails_unique=len(account_emails),
        matched_count=int(len(matched)),
        unmatched_count=int(len(unmatched)),
        profiles_email_col=profiles_email_col,
        accounts_email_col=accounts_email_col,
        matched_csv=csv_text,
        matched_preview=preview,
        matched_columns=list(matched.columns),
    )


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

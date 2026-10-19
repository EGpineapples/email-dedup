#!/usr/bin/env python3
"""
Email Toolkit — Flask UI
  Tab 1: Duplicate Checker (emails, phones, cards, addresses, profile matcher)
  Tab 2: Password Generator
  Tab 3: TCGplayer Order Extractor
  Tab 4: Column Extractor
  Tab 5: Address Lab (USPS suffix checker, Discord analytics, suggestions, generator)
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
import difflib
import zipfile
from collections import Counter, defaultdict

import pandas as pd
from flask import Flask, render_template_string, request, send_file, jsonify, Response

from pipeline import JOB, HAS_DISCORD

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


# ── USPS Street Suffix Table ─────────────────────────────────────────────────
# Source: USPS Pub 28, Appendix C — https://pe.usps.com/text/pub28/28apc_002.htm
# {primary_name: {standard_abbr: str, variants: [all accepted forms]}}

USPS_SUFFIXES = {
    "ALLEY":{"std":"ALY","v":["ALLEE","ALLEY","ALLY","ALY"]},
    "ANEX":{"std":"ANX","v":["ANEX","ANNEX","ANNX","ANX"]},
    "ARCADE":{"std":"ARC","v":["ARC","ARCADE"]},
    "AVENUE":{"std":"AVE","v":["AV","AVE","AVEN","AVENU","AVENUE","AVN","AVNUE"]},
    "BAYOU":{"std":"BYU","v":["BAYOO","BAYOU","BYU"]},
    "BEACH":{"std":"BCH","v":["BCH","BEACH"]},
    "BEND":{"std":"BND","v":["BEND","BND"]},
    "BLUFF":{"std":"BLF","v":["BLF","BLUF","BLUFF"]},
    "BLUFFS":{"std":"BLFS","v":["BLUFFS","BLFS"]},
    "BOTTOM":{"std":"BTM","v":["BOT","BTM","BOTTM","BOTTOM"]},
    "BOULEVARD":{"std":"BLVD","v":["BLVD","BOUL","BOULEVARD","BOULV"]},
    "BRANCH":{"std":"BR","v":["BR","BRNCH","BRANCH"]},
    "BRIDGE":{"std":"BRG","v":["BRDGE","BRG","BRIDGE"]},
    "BROOK":{"std":"BRK","v":["BRK","BROOK"]},
    "BROOKS":{"std":"BRKS","v":["BROOKS","BRKS"]},
    "BURG":{"std":"BG","v":["BURG","BG"]},
    "BURGS":{"std":"BGS","v":["BURGS","BGS"]},
    "BYPASS":{"std":"BYP","v":["BYP","BYPA","BYPAS","BYPASS","BYPS"]},
    "CAMP":{"std":"CP","v":["CAMP","CP","CMP"]},
    "CANYON":{"std":"CYN","v":["CANYN","CANYON","CNYN","CYN"]},
    "CAPE":{"std":"CPE","v":["CAPE","CPE"]},
    "CAUSEWAY":{"std":"CSWY","v":["CAUSEWAY","CAUSWA","CSWY"]},
    "CENTER":{"std":"CTR","v":["CEN","CENT","CENTER","CENTR","CENTRE","CNTER","CNTR","CTR"]},
    "CENTERS":{"std":"CTRS","v":["CENTERS","CTRS"]},
    "CIRCLE":{"std":"CIR","v":["CIR","CIRC","CIRCL","CIRCLE","CRCL","CRCLE"]},
    "CIRCLES":{"std":"CIRS","v":["CIRCLES","CIRS"]},
    "CLIFF":{"std":"CLF","v":["CLF","CLIFF"]},
    "CLIFFS":{"std":"CLFS","v":["CLFS","CLIFFS"]},
    "CLUB":{"std":"CLB","v":["CLB","CLUB"]},
    "COMMON":{"std":"CMN","v":["COMMON","CMN"]},
    "COMMONS":{"std":"CMNS","v":["COMMONS","CMNS"]},
    "CORNER":{"std":"COR","v":["COR","CORNER"]},
    "CORNERS":{"std":"CORS","v":["CORNERS","CORS"]},
    "COURSE":{"std":"CRSE","v":["COURSE","CRSE"]},
    "COURT":{"std":"CT","v":["COURT","CT"]},
    "COURTS":{"std":"CTS","v":["COURTS","CTS"]},
    "COVE":{"std":"CV","v":["COVE","CV"]},
    "COVES":{"std":"CVS","v":["COVES","CVS"]},
    "CREEK":{"std":"CRK","v":["CREEK","CRK"]},
    "CRESCENT":{"std":"CRES","v":["CRESCENT","CRES","CRSENT","CRSNT"]},
    "CREST":{"std":"CRST","v":["CREST","CRST"]},
    "CROSSING":{"std":"XING","v":["CROSSING","CRSSNG","XING"]},
    "CROSSROAD":{"std":"XRD","v":["CROSSROAD","XRD"]},
    "CROSSROADS":{"std":"XRDS","v":["CROSSROADS","XRDS"]},
    "CURVE":{"std":"CURV","v":["CURVE","CURV"]},
    "DALE":{"std":"DL","v":["DALE","DL"]},
    "DAM":{"std":"DM","v":["DAM","DM"]},
    "DIVIDE":{"std":"DV","v":["DIV","DIVIDE","DV","DVD"]},
    "DRIVE":{"std":"DR","v":["DR","DRIV","DRIVE","DRV"]},
    "DRIVES":{"std":"DRS","v":["DRIVES","DRS"]},
    "ESTATE":{"std":"EST","v":["EST","ESTATE"]},
    "ESTATES":{"std":"ESTS","v":["ESTATES","ESTS"]},
    "EXPRESSWAY":{"std":"EXPY","v":["EXP","EXPR","EXPRESS","EXPRESSWAY","EXPW","EXPY"]},
    "EXTENSION":{"std":"EXT","v":["EXT","EXTENSION","EXTN","EXTNSN"]},
    "EXTENSIONS":{"std":"EXTS","v":["EXTS","EXTENSIONS"]},
    "FALL":{"std":"FALL","v":["FALL"]},
    "FALLS":{"std":"FLS","v":["FALLS","FLS"]},
    "FERRY":{"std":"FRY","v":["FERRY","FRRY","FRY"]},
    "FIELD":{"std":"FLD","v":["FIELD","FLD"]},
    "FIELDS":{"std":"FLDS","v":["FIELDS","FLDS"]},
    "FLAT":{"std":"FLT","v":["FLAT","FLT"]},
    "FLATS":{"std":"FLTS","v":["FLATS","FLTS"]},
    "FORD":{"std":"FRD","v":["FORD","FRD"]},
    "FORDS":{"std":"FRDS","v":["FORDS","FRDS"]},
    "FOREST":{"std":"FRST","v":["FOREST","FORESTS","FRST"]},
    "FORGE":{"std":"FRG","v":["FORG","FORGE","FRG"]},
    "FORGES":{"std":"FRGS","v":["FORGES","FRGS"]},
    "FORK":{"std":"FRK","v":["FORK","FRK"]},
    "FORKS":{"std":"FRKS","v":["FORKS","FRKS"]},
    "FORT":{"std":"FT","v":["FORT","FRT","FT"]},
    "FREEWAY":{"std":"FWY","v":["FREEWAY","FREEWY","FRWAY","FRWY","FWY"]},
    "GARDEN":{"std":"GDN","v":["GARDEN","GARDN","GRDEN","GRDN","GDN"]},
    "GARDENS":{"std":"GDNS","v":["GARDENS","GDNS","GRDNS"]},
    "GATEWAY":{"std":"GTWY","v":["GATEWAY","GATEWY","GATWAY","GTWAY","GTWY"]},
    "GLEN":{"std":"GLN","v":["GLEN","GLN"]},
    "GLENS":{"std":"GLNS","v":["GLENS","GLNS"]},
    "GREEN":{"std":"GRN","v":["GREEN","GRN"]},
    "GREENS":{"std":"GRNS","v":["GREENS","GRNS"]},
    "GROVE":{"std":"GRV","v":["GROV","GROVE","GRV"]},
    "GROVES":{"std":"GRVS","v":["GROVES","GRVS"]},
    "HARBOR":{"std":"HBR","v":["HARB","HARBOR","HARBR","HBR","HRBOR"]},
    "HARBORS":{"std":"HBRS","v":["HARBORS","HBRS"]},
    "HAVEN":{"std":"HVN","v":["HAVEN","HVN"]},
    "HEIGHTS":{"std":"HTS","v":["HT","HTS","HEIGHTS"]},
    "HIGHWAY":{"std":"HWY","v":["HIGHWAY","HIGHWY","HIWAY","HIWY","HWAY","HWY"]},
    "HILL":{"std":"HL","v":["HILL","HL"]},
    "HILLS":{"std":"HLS","v":["HILLS","HLS"]},
    "HOLLOW":{"std":"HOLW","v":["HLLW","HOLLOW","HOLLOWS","HOLW","HOLWS"]},
    "INLET":{"std":"INLT","v":["INLT","INLET"]},
    "ISLAND":{"std":"IS","v":["IS","ISLAND","ISLND"]},
    "ISLANDS":{"std":"ISS","v":["ISLANDS","ISLNDS","ISS"]},
    "ISLE":{"std":"ISLE","v":["ISLE","ISLES"]},
    "JUNCTION":{"std":"JCT","v":["JCT","JCTION","JCTN","JUNCTION","JUNCTN","JUNCTON"]},
    "JUNCTIONS":{"std":"JCTS","v":["JCTNS","JCTS","JUNCTIONS"]},
    "KEY":{"std":"KY","v":["KEY","KY"]},
    "KEYS":{"std":"KYS","v":["KEYS","KYS"]},
    "KNOLL":{"std":"KNL","v":["KNL","KNOL","KNOLL"]},
    "KNOLLS":{"std":"KNLS","v":["KNLS","KNOLLS"]},
    "LAKE":{"std":"LK","v":["LK","LAKE"]},
    "LAKES":{"std":"LKS","v":["LKS","LAKES"]},
    "LAND":{"std":"LAND","v":["LAND"]},
    "LANDING":{"std":"LNDG","v":["LANDING","LNDG","LNDNG"]},
    "LANE":{"std":"LN","v":["LANE","LN"]},
    "LIGHT":{"std":"LGT","v":["LGT","LIGHT"]},
    "LIGHTS":{"std":"LGTS","v":["LIGHTS","LGTS"]},
    "LOAF":{"std":"LF","v":["LF","LOAF"]},
    "LOCK":{"std":"LCK","v":["LCK","LOCK"]},
    "LOCKS":{"std":"LCKS","v":["LCKS","LOCKS"]},
    "LODGE":{"std":"LDG","v":["LDG","LDGE","LODG","LODGE"]},
    "LOOP":{"std":"LOOP","v":["LOOP","LOOPS"]},
    "MALL":{"std":"MALL","v":["MALL"]},
    "MANOR":{"std":"MNR","v":["MNR","MANOR"]},
    "MANORS":{"std":"MNRS","v":["MANORS","MNRS"]},
    "MEADOW":{"std":"MDW","v":["MEADOW","MDW"]},
    "MEADOWS":{"std":"MDWS","v":["MDW","MDWS","MEADOWS","MEDOWS"]},
    "MEWS":{"std":"MEWS","v":["MEWS"]},
    "MILL":{"std":"ML","v":["MILL","ML"]},
    "MILLS":{"std":"MLS","v":["MILLS","MLS"]},
    "MISSION":{"std":"MSN","v":["MISSN","MSSN","MSN","MISSION"]},
    "MOTORWAY":{"std":"MTWY","v":["MOTORWAY","MTWY"]},
    "MOUNT":{"std":"MT","v":["MNT","MT","MOUNT"]},
    "MOUNTAIN":{"std":"MTN","v":["MNTAIN","MNTN","MOUNTAIN","MOUNTIN","MTIN","MTN"]},
    "MOUNTAINS":{"std":"MTNS","v":["MNTNS","MOUNTAINS","MTNS"]},
    "NECK":{"std":"NCK","v":["NCK","NECK"]},
    "ORCHARD":{"std":"ORCH","v":["ORCH","ORCHARD","ORCHRD"]},
    "OVAL":{"std":"OVAL","v":["OVAL","OVL"]},
    "OVERPASS":{"std":"OPAS","v":["OVERPASS","OPAS"]},
    "PARK":{"std":"PARK","v":["PARK","PRK"]},
    "PARKS":{"std":"PARK","v":["PARKS"]},
    "PARKWAY":{"std":"PKWY","v":["PARKWAY","PARKWY","PKWAY","PKWY","PKY"]},
    "PARKWAYS":{"std":"PKWY","v":["PARKWAYS","PKWYS"]},
    "PASS":{"std":"PASS","v":["PASS"]},
    "PASSAGE":{"std":"PSGE","v":["PASSAGE","PSGE"]},
    "PATH":{"std":"PATH","v":["PATH","PATHS"]},
    "PIKE":{"std":"PIKE","v":["PIKE","PIKES"]},
    "PINE":{"std":"PNE","v":["PINE","PNE"]},
    "PINES":{"std":"PNES","v":["PINES","PNES"]},
    "PLACE":{"std":"PL","v":["PL","PLACE"]},
    "PLAIN":{"std":"PLN","v":["PLAIN","PLN"]},
    "PLAINS":{"std":"PLNS","v":["PLAINS","PLNS"]},
    "PLAZA":{"std":"PLZ","v":["PLAZA","PLZ","PLZA"]},
    "POINT":{"std":"PT","v":["POINT","PT"]},
    "POINTS":{"std":"PTS","v":["POINTS","PTS"]},
    "PORT":{"std":"PRT","v":["PORT","PRT"]},
    "PORTS":{"std":"PRTS","v":["PORTS","PRTS"]},
    "PRAIRIE":{"std":"PR","v":["PR","PRAIRIE","PRR"]},
    "RADIAL":{"std":"RADL","v":["RAD","RADIAL","RADIEL","RADL"]},
    "RAMP":{"std":"RAMP","v":["RAMP"]},
    "RANCH":{"std":"RNCH","v":["RANCH","RANCHES","RNCH","RNCHS"]},
    "RAPID":{"std":"RPD","v":["RAPID","RPD"]},
    "RAPIDS":{"std":"RPDS","v":["RAPIDS","RPDS"]},
    "REST":{"std":"RST","v":["REST","RST"]},
    "RIDGE":{"std":"RDG","v":["RDG","RDGE","RIDGE"]},
    "RIDGES":{"std":"RDGS","v":["RDGS","RIDGES"]},
    "RIVER":{"std":"RIV","v":["RIV","RIVER","RVR","RIVR"]},
    "ROAD":{"std":"RD","v":["RD","ROAD"]},
    "ROADS":{"std":"RDS","v":["ROADS","RDS"]},
    "ROUTE":{"std":"RTE","v":["ROUTE","RTE"]},
    "ROW":{"std":"ROW","v":["ROW"]},
    "RUE":{"std":"RUE","v":["RUE"]},
    "RUN":{"std":"RUN","v":["RUN"]},
    "SHOAL":{"std":"SHL","v":["SHL","SHOAL"]},
    "SHOALS":{"std":"SHLS","v":["SHLS","SHOALS"]},
    "SHORE":{"std":"SHR","v":["SHOAR","SHORE","SHR"]},
    "SHORES":{"std":"SHRS","v":["SHOARS","SHORES","SHRS"]},
    "SKYWAY":{"std":"SKWY","v":["SKYWAY","SKWY"]},
    "SPRING":{"std":"SPG","v":["SPG","SPNG","SPRING","SPRNG"]},
    "SPRINGS":{"std":"SPGS","v":["SPGS","SPNGS","SPRINGS","SPRNGS"]},
    "SPUR":{"std":"SPUR","v":["SPUR"]},
    "SPURS":{"std":"SPUR","v":["SPURS"]},
    "SQUARE":{"std":"SQ","v":["SQ","SQR","SQRE","SQU","SQUARE"]},
    "SQUARES":{"std":"SQS","v":["SQRS","SQUARES","SQS"]},
    "STATION":{"std":"STA","v":["STA","STATION","STATN","STN"]},
    "STRAVENUE":{"std":"STRA","v":["STRA","STRAV","STRAVEN","STRAVENUE","STRAVN","STRVN","STRVNUE"]},
    "STREAM":{"std":"STRM","v":["STREAM","STREME","STRM"]},
    "STREET":{"std":"ST","v":["STREET","STRT","ST","STR"]},
    "STREETS":{"std":"STS","v":["STREETS","STS"]},
    "SUMMIT":{"std":"SMT","v":["SMT","SUMIT","SUMITT","SUMMIT"]},
    "TERRACE":{"std":"TER","v":["TER","TERR","TERRACE"]},
    "THROUGHWAY":{"std":"TRWY","v":["THROUGHWAY","TRWY"]},
    "TRACE":{"std":"TRCE","v":["TRACE","TRACES","TRCE"]},
    "TRACK":{"std":"TRAK","v":["TRACK","TRACKS","TRAK","TRK","TRKS"]},
    "TRAFFICWAY":{"std":"TRFY","v":["TRAFFICWAY","TRFY"]},
    "TRAIL":{"std":"TRL","v":["TRAIL","TRAILS","TRL","TRLS"]},
    "TRAILER":{"std":"TRLR","v":["TRAILER","TRLR","TRLRS"]},
    "TUNNEL":{"std":"TUNL","v":["TUNEL","TUNL","TUNLS","TUNNEL","TUNNELS","TUNNL"]},
    "TURNPIKE":{"std":"TPKE","v":["TRNPK","TURNPIKE","TURNPK","TPKE"]},
    "UNDERPASS":{"std":"UPAS","v":["UNDERPASS","UPAS"]},
    "UNION":{"std":"UN","v":["UN","UNION"]},
    "UNIONS":{"std":"UNS","v":["UNIONS","UNS"]},
    "VALLEY":{"std":"VLY","v":["VALLEY","VALLY","VLLY","VLY"]},
    "VALLEYS":{"std":"VLYS","v":["VALLEYS","VLYS"]},
    "VIADUCT":{"std":"VIA","v":["VDCT","VIA","VIADCT","VIADUCT"]},
    "VIEW":{"std":"VW","v":["VIEW","VW"]},
    "VIEWS":{"std":"VWS","v":["VIEWS","VWS"]},
    "VILLAGE":{"std":"VLG","v":["VILL","VILLAG","VILLAGE","VILLG","VILLIAGE","VLG"]},
    "VILLAGES":{"std":"VLGS","v":["VILLAGES","VLGS"]},
    "VILLE":{"std":"VL","v":["VILLE","VL"]},
    "VISTA":{"std":"VIS","v":["VIS","VIST","VISTA","VST","VSTA"]},
    "WALK":{"std":"WALK","v":["WALK"]},
    "WALKS":{"std":"WALK","v":["WALKS"]},
    "WALL":{"std":"WALL","v":["WALL"]},
    "WAY":{"std":"WAY","v":["WY","WAY"]},
    "WAYS":{"std":"WAYS","v":["WAYS"]},
    "WELL":{"std":"WL","v":["WELL","WL"]},
    "WELLS":{"std":"WLS","v":["WELLS","WLS"]},
}

# Build reverse lookup: any variant -> primary name
_SUFFIX_REVERSE = {}
for _prim, _info in USPS_SUFFIXES.items():
    for _v in _info["v"]:
        _SUFFIX_REVERSE[_v.upper()] = _prim
    _SUFFIX_REVERSE[_info["std"].upper()] = _prim

# All variant strings for fuzzy matching
_ALL_SUFFIX_STRINGS = sorted(set(
    v for info in USPS_SUFFIXES.values() for v in info["v"]
))


def _parse_address_suffix(address: str):
    """Split an address into (street_base, suffix_token).
    Returns (base, suffix) where suffix is the last word if it matches a USPS suffix."""
    parts = address.strip().split()
    if not parts:
        return address, None
    # Check last word, then last 2 words joined
    last = parts[-1].upper().rstrip(".,")
    if last in _SUFFIX_REVERSE:
        return " ".join(parts[:-1]), last
    if len(parts) >= 2:
        last2 = (parts[-2] + " " + parts[-1]).upper().rstrip(".,")
        if last2 in _SUFFIX_REVERSE:
            return " ".join(parts[:-2]), last2
    return address, None


def usps_check_suffix(address: str):
    """Given an address, find its suffix and return alternatives, similar-sounding, similar-spelled."""
    base, suffix = _parse_address_suffix(address)
    if not suffix:
        return {
            "address": address,
            "base": base,
            "detected_suffix": None,
            "error": "No recognized USPS street suffix found in this address",
            "all_suffixes": sorted(USPS_SUFFIXES.keys()),
        }

    primary = _SUFFIX_REVERSE.get(suffix.upper(), suffix.upper())
    info = USPS_SUFFIXES.get(primary, {})

    # All official alternatives for this suffix
    alternatives = []
    for v in info.get("v", []):
        if v.upper() != suffix.upper():
            alternatives.append({"form": v, "address": f"{base} {v}"})
    std = info.get("std", "")
    if std.upper() != suffix.upper() and not any(a["form"] == std for a in alternatives):
        alternatives.insert(0, {"form": std, "address": f"{base} {std}", "note": "USPS Standard"})

    # Similar sounding (phonetic similarity via difflib)
    similar_sound = []
    suffix_up = suffix.upper()
    for prim, pinfo in USPS_SUFFIXES.items():
        if prim == primary:
            continue
        # Check if any variant sounds similar
        for v in pinfo["v"]:
            ratio = difflib.SequenceMatcher(None, suffix_up, v.upper()).ratio()
            if ratio >= 0.55 and ratio < 1.0:
                similar_sound.append({
                    "suffix": prim,
                    "form": v,
                    "std": pinfo["std"],
                    "similarity": round(ratio, 2),
                    "address": f"{base} {v}",
                })
                break

    similar_sound.sort(key=lambda x: -x["similarity"])

    # Similar spelled (close matches via difflib)
    close = difflib.get_close_matches(suffix_up, _ALL_SUFFIX_STRINGS, n=15, cutoff=0.5)
    similar_spelled = []
    seen_primaries = {primary}
    for c in close:
        c_primary = _SUFFIX_REVERSE.get(c, c)
        if c_primary in seen_primaries:
            continue
        seen_primaries.add(c_primary)
        c_info = USPS_SUFFIXES.get(c_primary, {})
        similar_spelled.append({
            "suffix": c_primary,
            "form": c,
            "std": c_info.get("std", c),
            "address": f"{base} {c}",
        })

    return {
        "address": address,
        "base": base,
        "detected_suffix": suffix,
        "primary_name": primary,
        "standard_abbr": info.get("std", ""),
        "alternatives": alternatives,
        "similar_sounding": similar_sound[:10],
        "similar_spelled": similar_spelled[:10],
    }


# ── Discord Analytics Data Layer ─────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VALOR_JSON    = os.path.join(BASE_DIR, "valor.json")
DECLINED_CSV  = os.path.join(BASE_DIR, "declined_profiles.csv")
CHECKED_CSV   = os.path.join(BASE_DIR, "checked_profiles.csv")
CHANNELS_JSON = os.path.join(BASE_DIR, "channels.json")
FUZZY_CUTOFF  = 0.75


def _load_valor_profiles():
    """Load profiles from valor.json if it exists."""
    if not os.path.exists(VALOR_JSON):
        return {}
    try:
        with open(VALOR_JSON, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}

    profiles = {}
    for pid, p in raw.items():
        b = p.get("billing") or {}
        s = p.get("shipping") or {}
        c = p.get("card") or {}
        name = (p.get("name") or "").strip()
        if not name:
            continue
        profiles[name.lower()] = {
            "name":      name,
            "card_type": (c.get("type") or "unknown").lower(),
            "zip":       (b.get("zipCode")     or s.get("zipCode")     or "unknown").strip(),
            "state":     (b.get("state")       or s.get("state")       or "unknown").strip(),
            "city":      (b.get("city")        or s.get("city")        or "unknown").strip(),
            "address":   (b.get("addressLine1") or s.get("addressLine1") or "unknown").strip(),
        }
    return profiles


def load_discord_data():
    """Load profiles, declined/checked events, match them via fuzzy matching.

    Works in two modes:
    - WITH valor.json: enriches events with card type, zip, address, etc.
    - WITHOUT valor.json: uses profile name + site from CSVs directly.
    """
    valor_profiles = _load_valor_profiles()
    keys = list(valor_profiles.keys()) if valor_profiles else []

    def read_events(path, status):
        out = []
        if not os.path.exists(path):
            return out
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    out.append({
                        "profile":   (row.get("profile") or "").strip(),
                        "timestamp": row.get("timestamp", ""),
                        "site":      (row.get("site") or "").strip(),
                        "status":    status,
                    })
        except Exception:
            pass
        return out

    events = read_events(DECLINED_CSV, "declined") + read_events(CHECKED_CSV, "checked")
    if not events:
        return valor_profiles, [], []

    # Build profiles from CSV names (fallback when valor.json is missing)
    all_profiles = dict(valor_profiles)
    match_cache, unmatched = {}, set()
    for e in events:
        raw_name = e["profile"]
        if not raw_name:
            continue
        low = raw_name.lower()
        if low in match_cache:
            e["valor"] = match_cache[low]
            continue
        hit = None
        # Try valor.json match first
        if valor_profiles:
            if low in valor_profiles:
                hit = valor_profiles[low]
            else:
                m = difflib.get_close_matches(low, keys, n=1, cutoff=FUZZY_CUTOFF)
                if m:
                    hit = valor_profiles[m[0]]
                else:
                    for k in keys:
                        if low and (low in k or k in low):
                            hit = valor_profiles[k]
                            break
        # No valor.json or no match -> create a basic profile from the CSV name
        if hit is None:
            if valor_profiles:
                unmatched.add(raw_name)
            hit = {
                "name":      raw_name,
                "card_type": "unknown",
                "zip":       "unknown",
                "state":     "unknown",
                "city":      "unknown",
                "address":   "unknown",
            }
            if low not in all_profiles:
                all_profiles[low] = hit
        match_cache[low] = hit
        e["valor"] = hit

    return all_profiles, [e for e in events if e.get("valor")], sorted(unmatched)


def discord_aggregate(events, keyfn):
    buckets = defaultdict(lambda: {"declined": 0, "checked": 0})
    for e in events:
        buckets[keyfn(e)][e["status"]] += 1
    rows = []
    for k, v in buckets.items():
        total = v["declined"] + v["checked"]
        rows.append({
            "key":         k or "unknown",
            "declined":    v["declined"],
            "checked":     v["checked"],
            "total":       total,
            "decline_pct": round(v["declined"] / total * 100, 1) if total else 0.0,
            "check_pct":   round(v["checked"]  / total * 100, 1) if total else 0.0,
        })
    rows.sort(key=lambda r: (-r["decline_pct"], -r["total"]))
    return rows


DISCORD_GROUPINGS = {
    "Profile":    lambda e: e["valor"]["name"],
    "Card Type":  lambda e: e["valor"]["card_type"],
    "Zip Code":   lambda e: e["valor"]["zip"],
    "State":      lambda e: e["valor"]["state"],
    "Address":    lambda e: e["valor"]["address"],
    "Type + Zip": lambda e: f'{e["valor"]["card_type"]} | {e["valor"]["zip"]}',
    "Site":       lambda e: e.get("site") or "unknown",
}


# Channel store
def _load_channels():
    """Load channels from channels.json, seeded from DISCORD_CHANNELS env var.

    DISCORD_CHANNELS format (set in Render):
      {"channel_id":"name","channel_id":"name",...}
      e.g. {"1422713687008870400":"valor-cooked","9999":"hayha"}
    """
    channels = []
    if os.path.exists(CHANNELS_JSON):
        try:
            with open(CHANNELS_JSON, "r", encoding="utf-8") as f:
                channels = json.load(f)
        except Exception:
            channels = []

    # Seed from env var (only adds channels not already present)
    env_raw = os.environ.get("DISCORD_CHANNELS", "")
    if env_raw:
        try:
            env_map = json.loads(env_raw)   # {"id": "name", ...}
            existing_ids = {str(ch.get("id")) for ch in channels}
            for cid, cname in env_map.items():
                if str(cid) not in existing_ids:
                    channels.append({"id": str(cid), "name": cname or str(cid)})
        except Exception:
            pass

    return channels


def _save_channels(items):
    with open(CHANNELS_JSON, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


# Cache
_discord_cache = {"mtime": None, "profiles": {}, "events": [], "unmatched": [], "by_profile": []}


def _discord_stamp():
    parts = []
    for p in (VALOR_JSON, DECLINED_CSV, CHECKED_CSV):
        parts.append(os.path.getmtime(p) if os.path.exists(p) else 0)
    return tuple(parts)


def get_discord_data():
    st = _discord_stamp()
    if _discord_cache["mtime"] != st:
        profiles, events, unmatched = load_discord_data()
        _discord_cache.update({
            "mtime":      st,
            "profiles":   profiles,
            "events":     events,
            "unmatched":  unmatched,
            "by_profile": discord_aggregate(events, lambda e: e["valor"]["name"]),
        })
    return _discord_cache


# ── Address Suggestion Engine ────────────────────────────────────────────────

def _generate_misspellings(word: str) -> list[str]:
    """Generate slight misspellings of a word."""
    results = set()
    w = word.upper()
    if len(w) < 2:
        return []

    # Swap adjacent characters
    for i in range(len(w) - 1):
        swapped = w[:i] + w[i+1] + w[i] + w[i+2:]
        if swapped != w:
            results.add(swapped)

    # Double a letter
    for i in range(len(w)):
        doubled = w[:i] + w[i] + w[i:]
        if doubled != w:
            results.add(doubled)

    # Drop a letter (only if word long enough)
    if len(w) >= 4:
        for i in range(len(w)):
            dropped = w[:i] + w[i+1:]
            if dropped != w and len(dropped) >= 2:
                results.add(dropped)

    # Common letter substitutions
    subs = {"S": "Z", "Z": "S", "C": "K", "K": "C", "PH": "F", "F": "PH",
            "EE": "EA", "EA": "EE", "OO": "OU", "OU": "OO", "IE": "EI", "EI": "IE",
            "E": "A", "A": "E", "I": "Y", "Y": "I"}
    for old, new in subs.items():
        if old in w:
            results.add(w.replace(old, new, 1))

    results.discard(w)
    return sorted(results)[:12]


def generate_address_suggestions(base: str, current_suffix: str | None = None,
                                 used_addresses: set | None = None,
                                 decline_data: list | None = None) -> dict:
    """Generate new address form suggestions that haven't been used before."""
    used = {a.lower() for a in (used_addresses or set())}
    suggestions = []

    # 1) All USPS suffix alternatives
    for prim, info in USPS_SUFFIXES.items():
        for v in info["v"]:
            addr = f"{base} {v}"
            if addr.lower() not in used:
                suggestions.append({
                    "address": addr,
                    "source": "usps_variant",
                    "suffix": v,
                    "primary": prim,
                    "note": f"Official USPS variant of {prim}",
                })

    # 2) Misspellings of current suffix
    if current_suffix:
        for mis in _generate_misspellings(current_suffix):
            addr = f"{base} {mis}"
            if addr.lower() not in used:
                suggestions.append({
                    "address": addr,
                    "source": "misspelling",
                    "suffix": mis,
                    "note": f"Slight misspelling of {current_suffix}",
                })

    # 3) Commonly successful suffixes from decline data
    if decline_data:
        # Find which suffixes have better checkout rates
        suffix_stats = defaultdict(lambda: {"declined": 0, "checked": 0})
        for e in decline_data:
            addr = e.get("valor", {}).get("address", "")
            _, sfx = _parse_address_suffix(addr)
            if sfx:
                prim = _SUFFIX_REVERSE.get(sfx.upper(), sfx.upper())
                suffix_stats[prim][e["status"]] += 1

        good_suffixes = []
        for sfx, stats in suffix_stats.items():
            total = stats["declined"] + stats["checked"]
            if total >= 2 and stats["checked"] / total >= 0.4:
                good_suffixes.append((sfx, stats["checked"] / total))

        good_suffixes.sort(key=lambda x: -x[1])
        for sfx_name, rate in good_suffixes[:8]:
            info = USPS_SUFFIXES.get(sfx_name, {})
            for v in info.get("v", []):
                addr = f"{base} {v}"
                if addr.lower() not in used:
                    suggestions.append({
                        "address": addr,
                        "source": "high_checkout_rate",
                        "suffix": v,
                        "primary": sfx_name,
                        "note": f"{sfx_name} has {round(rate*100)}% checkout rate",
                    })
                    break

    # 4) Commonly used suffixes (top ~20 most common)
    common_suffixes = [
        "STREET", "AVENUE", "DRIVE", "ROAD", "LANE", "COURT", "CIRCLE",
        "BOULEVARD", "PLACE", "WAY", "TRAIL", "TERRACE", "PARKWAY",
        "HIGHWAY", "RIDGE", "HILL", "CREEK", "POINT", "SQUARE", "RUN",
    ]
    for prim in common_suffixes:
        info = USPS_SUFFIXES.get(prim, {})
        for v in info.get("v", []):
            addr = f"{base} {v}"
            if addr.lower() not in used:
                suggestions.append({
                    "address": addr,
                    "source": "common_suffix",
                    "suffix": v,
                    "primary": prim,
                    "note": f"Commonly used street suffix",
                })
                break

    # Deduplicate by address
    seen_addrs = set()
    unique = []
    for s in suggestions:
        key = s["address"].lower()
        if key not in seen_addrs:
            seen_addrs.add(key)
            unique.append(s)

    return {
        "base": base,
        "current_suffix": current_suffix,
        "suggestions": unique,
        "total": len(unique),
    }


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

    # ── Duplicate checks within matched profiles ──
    dupes_found = {}
    cols_lower = {c: c.lower().strip() for c in matched.columns}

    # 1) Duplicate emails
    email_col_m = None
    for orig, low in cols_lower.items():
        if "email" in low:
            email_col_m = orig
            break
    if email_col_m:
        vals = matched[email_col_m].fillna("").str.strip().str.lower()
        vals = vals[vals != ""]
        counts = vals.value_counts()
        email_dupes = {v: int(c) for v, c in counts.items() if c > 1}
        if email_dupes:
            dupes_found["email"] = {"column": email_col_m, "dupes": email_dupes}

    # 2) Duplicate phone numbers
    phone_col_m = None
    for orig, low in cols_lower.items():
        if any(k in low for k in ["phone", "phone_num", "phone_number", "telephone", "mobile", "cell"]):
            phone_col_m = orig
            break
    if phone_col_m:
        vals = matched[phone_col_m].fillna("").astype(str).apply(
            lambda v: normalize_phone(v) if v.strip() else ""
        )
        vals = vals[vals.str.len() == 10]
        counts = vals.value_counts()
        phone_dupes = {v: int(c) for v, c in counts.items() if c > 1}
        if phone_dupes:
            dupes_found["phone"] = {"column": phone_col_m, "dupes": phone_dupes}

    # 3) Duplicate card numbers
    cc_col_m = None
    for orig, low in cols_lower.items():
        if any(k in low for k in ["cc_number", "card_number", "card_num", "cc_num",
                                   "credit_card", "card", "cc", "payment_card"]):
            cc_col_m = orig
            break
    if cc_col_m:
        vals = matched[cc_col_m].fillna("").astype(str).apply(
            lambda v: re.sub(r"[\s-]", "", v)
        )
        vals = vals[vals.str.len() >= 4]  # must have something
        counts = vals.value_counts()
        cc_dupes = {}
        for v, c in counts.items():
            if c > 1:
                masked = "•" * max(0, len(v) - 4) + v[-4:]
                cc_dupes[masked] = int(c)
        if cc_dupes:
            dupes_found["card"] = {"column": cc_col_m, "dupes": cc_dupes}

    # 4) Duplicate shipping addresses (shipping_street + shipping_street_2)
    ship1_col = None
    ship2_col = None
    for orig, low in cols_lower.items():
        if any(k in low for k in ["shipping_street_2", "shipping_address_2",
                                   "shipping_street2", "ship_street_2"]):
            ship2_col = orig
        elif any(k in low for k in ["shipping_street", "shipping_address",
                                     "ship_street", "shipping_street_1",
                                     "shipping_address_1"]):
            ship1_col = orig
    if ship1_col:
        addr_keys = []
        for _, row in matched.iterrows():
            line1 = str(row.get(ship1_col, "")).strip().lower()
            line2 = str(row.get(ship2_col, "")).strip().lower() if ship2_col else ""
            if line1 and line1 != "nan":
                key = f"{line1}|{line2}" if line2 and line2 != "nan" else line1
                addr_keys.append(key)
        counts = Counter(addr_keys)
        addr_dupes = {}
        for addr, cnt in counts.items():
            if cnt > 1:
                display = addr.replace("|", " + ") if "|" in addr else addr
                addr_dupes[display] = cnt
        if addr_dupes:
            dupes_found["address"] = {
                "column": ship1_col + (f" + {ship2_col}" if ship2_col else ""),
                "dupes": addr_dupes,
            }

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
        dupes_found=dupes_found,
    )


@app.route("/download/<kind>")
def download(kind):
    data = request.args.get("data", "")
    fname = f"{kind}_emails.txt"
    buf = io.BytesIO(data.encode("utf-8"))
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=fname, mimetype="text/plain")


# ── Address Lab API Routes ───────────────────────────────────────────────────

@app.route("/api/usps-check", methods=["POST"])
def api_usps_check():
    body = request.get_json(force=True, silent=True) or {}
    address = (body.get("address") or "").strip()
    if not address:
        return jsonify({"error": "address is required"}), 400
    return jsonify(usps_check_suffix(address))


@app.route("/api/address-suggest", methods=["POST"])
def api_address_suggest():
    body = request.get_json(force=True, silent=True) or {}
    address = (body.get("address") or "").strip()
    if not address:
        return jsonify({"error": "address is required"}), 400

    base, suffix = _parse_address_suffix(address)

    # Optionally pull decline data for smarter suggestions
    decline_events = []
    try:
        d = get_discord_data()
        decline_events = d.get("events", [])
    except Exception:
        pass

    # Collect already-used addresses from decline data
    used = set()
    for e in decline_events:
        v = e.get("valor", {})
        if v:
            used.add(v.get("address", "").lower())

    result = generate_address_suggestions(
        base, suffix, used_addresses=used, decline_data=decline_events
    )
    return jsonify(result)


@app.route("/api/address-generate", methods=["POST"])
def api_address_generate():
    """Generate brand new address variations that have never been used."""
    body = request.get_json(force=True, silent=True) or {}
    base = (body.get("base") or "").strip()
    if not base:
        return jsonify({"error": "base (street without suffix) is required"}), 400

    exclude_raw = body.get("exclude", [])
    used = {a.lower() for a in exclude_raw if isinstance(a, str)}

    # Also pull used addresses from Discord data
    try:
        d = get_discord_data()
        for e in d.get("events", []):
            v = e.get("valor", {})
            if v:
                used.add(v.get("address", "").lower())
    except Exception:
        pass

    result = generate_address_suggestions(base, None, used_addresses=used)
    return jsonify(result)


# ── Discord Analytics API Routes ─────────────────────────────────────────────

@app.route("/api/discord/lookup")
def api_discord_lookup():
    q = (request.args.get("q") or "").strip().lower()
    d = get_discord_data()
    rows_all = d.get("by_profile", [])

    if not q:
        rows = rows_all
    else:
        rows = [r for r in rows_all if q in r["key"].lower()]
        if not rows:
            names = [r["key"].lower() for r in rows_all]
            close = set(difflib.get_close_matches(q, names, n=12, cutoff=0.5))
            rows = [r for r in rows_all if r["key"].lower() in close]

    dec = sum(r["declined"] for r in rows)
    chk = sum(r["checked"]  for r in rows)
    tot = dec + chk
    return jsonify({
        "rows": rows,
        "stats": {
            "total":   tot,
            "decline": round(dec / tot * 100, 1) if tot else None,
            "check":   round(chk / tot * 100, 1) if tot else None,
            "matched": len(rows),
        },
    })


@app.route("/api/discord/breakdown")
def api_discord_breakdown():
    name = request.args.get("group", "Card Type")
    try:
        minimum = int(request.args.get("min", "1"))
    except ValueError:
        minimum = 1
    keyfn = DISCORD_GROUPINGS.get(name, DISCORD_GROUPINGS["Card Type"])
    d = get_discord_data()
    rows = [r for r in discord_aggregate(d["events"], keyfn) if r["total"] >= minimum]
    return jsonify({"group": name, "rows": rows})


@app.route("/api/discord/unmatched")
def api_discord_unmatched():
    return jsonify({"unmatched": get_discord_data()["unmatched"]})


@app.route("/api/discord/export")
def api_discord_export():
    name = request.args.get("group", "Card Type")
    try:
        minimum = int(request.args.get("min", "1"))
    except ValueError:
        minimum = 1
    keyfn = DISCORD_GROUPINGS.get(name, DISCORD_GROUPINGS["Card Type"])
    rows = [r for r in discord_aggregate(get_discord_data()["events"], keyfn)
            if r["total"] >= minimum]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["key", "declined", "checked", "total",
                                         "decline_pct", "check_pct"])
    w.writeheader()
    w.writerows(rows)
    fn = f'stats_by_{name.lower().replace(" ", "_").replace("+", "and")}.csv'
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@app.route("/api/discord/refresh", methods=["POST"])
def api_discord_refresh():
    _discord_cache["mtime"] = None
    d = get_discord_data()
    return jsonify({"ok": True, "profiles": len(d["profiles"]),
                    "events": len(d["events"]), "unmatched": len(d["unmatched"])})


# ---- Channel management ----
@app.route("/api/discord/channels", methods=["GET", "POST", "DELETE"])
def api_discord_channels():
    channels = _load_channels()
    if request.method == "GET":
        return jsonify({"channels": channels})
    if request.method == "POST":
        body = request.get_json(force=True, silent=True) or {}
        cid  = str(body.get("id", "")).strip()
        name = (body.get("name") or "").strip() or cid
        if not cid.isdigit():
            return jsonify({"ok": False, "error": "channel id must be numeric"}), 400
        channels = [c for c in channels if str(c.get("id")) != cid]
        channels.append({"id": cid, "name": name})
        _save_channels(channels)
        return jsonify({"ok": True, "channels": channels})
    if request.method == "DELETE":
        cid = str(request.args.get("id", "")).strip()
        channels = [c for c in channels if str(c.get("id")) != cid]
        _save_channels(channels)
        return jsonify({"ok": True, "channels": channels})


# ---- Scrape control ----
@app.route("/api/discord/scrape", methods=["POST"])
def api_discord_scrape():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        return jsonify({"ok": False, "error": "DISCORD_BOT_TOKEN env var not set"}), 400
    body = request.get_json(force=True, silent=True) or {}
    cid  = str(body.get("channel_id") or request.args.get("channel_id") or "").strip()
    if not cid.isdigit():
        return jsonify({"ok": False, "error": "channel_id must be numeric"}), 400
    ok = JOB.start(cid, token)
    if not ok:
        return jsonify({"ok": False, "error": "a scrape is already running"}), 409
    return jsonify({"ok": True, "channel_id": cid})


@app.route("/api/discord/scrape/status")
def api_discord_scrape_status():
    return jsonify(JOB.snapshot())


@app.route("/api/discord/info")
def api_discord_info():
    """Summary info for the Address Lab dashboard."""
    d = get_discord_data()
    return jsonify({
        "profile_count":  len(d.get("profiles", {})),
        "event_count":    len(d.get("events", [])),
        "unmatched_count": len(d.get("unmatched", [])),
        "groupings":      list(DISCORD_GROUPINGS.keys()),
        "channels":       _load_channels(),
        "has_token":      bool(os.environ.get("DISCORD_BOT_TOKEN")),
        "has_discord_py": HAS_DISCORD,
    })


# ---- Download / Upload scraped data ----
@app.route("/api/discord/download-data")
def api_discord_download_data():
    """Download scraped CSVs as a zip bundle for backup / reload."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, path in [("webhook_history.csv", os.path.join(BASE_DIR, "webhook_history.csv")),
                           ("declined_profiles.csv", DECLINED_CSV),
                           ("checked_profiles.csv", CHECKED_CSV)]:
            if os.path.exists(path):
                zf.write(path, name)
    buf.seek(0)
    if buf.getbuffer().nbytes <= 22:  # empty zip
        return jsonify({"ok": False, "error": "No scraped data to download"}), 404
    return send_file(buf, as_attachment=True,
                     download_name="discord_scraped_data.zip",
                     mimetype="application/zip")


@app.route("/api/discord/upload-data", methods=["POST"])
def api_discord_upload_data():
    """Upload a previously downloaded zip (or individual CSVs) to restore scraped data."""
    restored = []
    valid_names = {"webhook_history.csv", "declined_profiles.csv", "checked_profiles.csv"}

    for f in request.files.getlist("files"):
        fname = (f.filename or "").lower()

        # Handle zip file
        if fname.endswith(".zip"):
            try:
                zf = zipfile.ZipFile(f.stream, "r")
                for zname in zf.namelist():
                    base = os.path.basename(zname)
                    if base in valid_names:
                        target = os.path.join(BASE_DIR, base)
                        with zf.open(zname) as src, open(target, "wb") as dst:
                            dst.write(src.read())
                        restored.append(base)
            except Exception as e:
                return jsonify({"ok": False, "error": f"Bad zip: {e}"}), 400
            continue

        # Handle individual CSV
        base = os.path.basename(fname)
        if base in valid_names:
            target = os.path.join(BASE_DIR, base)
            f.save(target)
            restored.append(base)

    if not restored:
        return jsonify({"ok": False, "error": "No valid CSV files found"}), 400

    # If only webhook_history was uploaded, re-split into declined/checked
    if "webhook_history.csv" in restored and "declined_profiles.csv" not in restored:
        from pipeline import _filter_and_write
        _filter_and_write()
        restored += ["declined_profiles.csv (generated)", "checked_profiles.csv (generated)"]

    # Bust cache
    _discord_cache["mtime"] = None
    d = get_discord_data()

    return jsonify({
        "ok": True,
        "restored": restored,
        "profiles": len(d["profiles"]),
        "events": len(d["events"]),
    })


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

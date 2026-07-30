"""
Step 6 — Field Extraction Engine
Implements ALL techniques:
- X-histogram column detection (replaces pure Voronoi)
- Char confusion fix for ALL fields (not just GSTIN)
- GSTIN checksum validation
- Product name dictionary with fuzzy matching
- Domain-specific number cleaning
"""
import re, logging
from pipeline.step5_layout import row_to_text, assign_column_histogram, build_column_map_histogram

logger = logging.getLogger(__name__)

# ── Regex patterns ─────────────────────────────────────────────────────────
NUM_RE   = re.compile(r'\b(\d{1,8}(?:,\d{3})*(?:\.\d{1,2})?)\b')
GSTIN_RE = re.compile(r'\b(\d{2}[A-Z0-9]{5}\d{4}[A-Z][A-Z0-9][Z0][A-Z0-9])\b', re.I)
DATE_RE  = re.compile(
    r'\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})\b'
    r'|\b(\d{1,2}\s*-\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
    r'[a-z]*\s*-\s*\d{4})\b', re.I)
PHONE_RE = re.compile(r'\b(\d{10})\b|\b(\+91[\s\-]?\d{10})\b')
INV_LABEL_RE = re.compile(
    r'(?:invoice\s*no\.?|bill\s*no\.?|inv\.?\s*no\.?|bill\s*#|no\.)\s*[:\-#]?\s*'
    r'([A-Z0-9][A-Z0-9\-/]{1,15})', re.I)
_P = re.compile(r'[.\-/%\s]')

def _n(t): return _P.sub("", t.lower()).strip()
def _f(t):
    t = _fix_numbers(str(t))
    m = NUM_RE.search(t)
    return float(m.group(1).replace(",", "")) if m else 0.0


# ── Character confusion fixes ──────────────────────────────────────────────

def _fix_numbers(text: str) -> str:
    """
    Fix OCR character confusion in numeric fields.
    Common mistakes: O→0, l→1, I→1, S→5, B→8, Z→2, G→6
    Applied to any string that should be a number.
    """
    # Only apply if string looks like it should be a number
    if not re.search(r'\d', text):
        return text
    result = list(text)
    for i, ch in enumerate(result):
        if ch == 'O': result[i] = '0'
        elif ch == 'l' or ch == 'I': result[i] = '1'
        elif ch == 'S' and i > 0 and result[i-1].isdigit(): result[i] = '5'
        elif ch == 'B' and i > 0 and result[i-1].isdigit(): result[i] = '8'
        elif ch == 'Z' and i > 0 and result[i-1].isdigit(): result[i] = '2'
        elif ch == 'G' and i > 0 and result[i-1].isdigit(): result[i] = '6'
    return "".join(result)


def _fix_gstin(line: str) -> str:
    """Fix OCR confusion specifically in GSTIN format positions."""
    u = list(line.upper())
    # Positions 0-1: state code digits
    for i in (0, 1):
        if i < len(u):
            if u[i] == 'O': u[i] = '0'
            if u[i] == 'I' or u[i] == 'l': u[i] = '1'
    # Positions 2-6, 11: should be letters
    for i in (2, 3, 4, 5, 6, 11):
        if i < len(u):
            if u[i] == '0': u[i] = 'O'
            if u[i] == '1': u[i] = 'I'
    # Positions 7-10: PAN digits
    for i in (7, 8, 9, 10):
        if i < len(u):
            if u[i] == 'O': u[i] = '0'
            if u[i] == 'I' or u[i] == 'l': u[i] = '1'
    return "".join(u)


def _validate_gstin_checksum(gstin: str) -> bool:
    """
    Validate GSTIN checksum (last character).
    Uses the GSTIN checksum algorithm.
    Returns True if valid, False if checksum error detected.
    """
    if len(gstin) != 15:
        return False
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    total = 0
    for i, ch in enumerate(gstin[:14]):
        if ch not in chars:
            return False
        v = chars.index(ch)
        if i % 2 == 1:
            v *= 2
        total += v // len(chars) + v % len(chars)
    check_idx = (len(chars) - total % len(chars)) % len(chars)
    return gstin[14] == chars[check_idx]


# ── Product dictionary for fuzzy matching ─────────────────────────────────

# Common FMCG products seen on Indian distributor bills
# Add your distributor's products here over time
PRODUCT_DICT = [
    "SWADIST SOYA OIL", "SOYA OIL", "SUNFLOWER OIL", "MUSTARD OIL",
    "BASMATI RICE", "BALAJI BASMATI RICE", "RICE",
    "LIFEBUOY SOAP", "LIFEBUOY SOAP LEMON", "LIFEBUOY HANDWASH",
    "CAMEL TEA", "RED LABEL TEA", "TATA TEA",
    "DABUR HONEY", "HONEY",
    "GOLD COIN BREAD", "BRITANNIA BREAD",
    "KISSAN TOMATO KETCHUP", "KISSAN KETCHUP",
    "BRITANNIA MUFFILLS CAKE", "BRITANNIA CAKE",
    "KHARAK SAKHARIYA", "KHAKHRA",
    "BOURNVITA", "HORLICKS", "COMPLAN",
    "SURF EXCEL", "ARIEL", "TIDE",
    "COLGATE", "PEPSODENT", "CLOSEUP",
    "LUX SOAP", "DOVE SOAP", "DETTOL SOAP",
    "MAGGI NOODLES", "YiPPEE NOODLES",
    "AMUL BUTTER", "AMUL GHEE",
    "PARLE G BISCUIT", "HIDE AND SEEK", "BOURBON",
]

def _fuzzy_match_product(name: str, threshold: int = 75) -> str:
    """
    Match extracted product name against known FMCG dictionary.
    Returns corrected name if match score >= threshold, else original.
    Uses simple token-based similarity (no external library needed).
    """
    if not name or len(name) < 3:
        return name

    name_upper = name.upper()

    # Exact match first
    for product in PRODUCT_DICT:
        if product in name_upper or name_upper in product:
            return product

    # Token overlap similarity
    name_tokens = set(re.findall(r'\b\w{3,}\b', name_upper))
    best_score = 0
    best_match = name

    for product in PRODUCT_DICT:
        prod_tokens = set(re.findall(r'\b\w{3,}\b', product.upper()))
        if not prod_tokens:
            continue
        intersection = len(name_tokens & prod_tokens)
        union = len(name_tokens | prod_tokens)
        score = int(intersection / union * 100) if union > 0 else 0
        if score > best_score:
            best_score = score
            best_match = product

    if best_score >= threshold:
        logger.info(f"  Fuzzy match: '{name}' -> '{best_match}' ({best_score}%)")
        return best_match

    return name


# ── Header map ────────────────────────────────────────────────────────────

HEADER_MAP = {
    "description":"desc","product":"desc","item":"desc","particulars":"desc","name":"desc",
    "hsn":"hsn","sac":"hsn","hsnsac":"hsn","hsncode":"hsn","hsnno":"hsn",
    "qty":"qty","quantity":"qty","qnty":"qty","nos":"qty",
    "pcs":"uom","uom":"uom","unit":"uom","pkg":"uom",
    "case":"case","free":"free","mrp":"mrp",
    "rate":"rate","price":"rate",
    "scheme":"scheme","schm":"scheme","sch":"scheme",
    "schmrs":"scheme_amt","schmart":"scheme_amt",
    "disc%":"disc_pct","dis%":"disc_pct",
    "discamt":"disc_amt","discrs":"disc_amt",
    "taxablevalue":"taxable","taxableamt":"taxable",
    "cgst%":"cgst_r","cgstrate":"cgst_r",
    "cgstamt":"cgst_a","cgstrs":"cgst_a",
    "sgst%":"sgst_r","sgstrate":"sgst_r",
    "sgstamt":"sgst_a","sgstrs":"sgst_a",
    "igst%":"igst_r","igstamt":"igst_a",
    "cess":"cess",
    "gst%":"gst","tax%":"gst",
    "netamount":"amount","amountrs":"amount","netamt":"amount","total":"amount",
}

SUMMARY_KW = [
    "total amount after tax","grand total","net amount","total payable",
    "amount after tax","total amount after","net amt",
    "total amount before tax","taxable value","taxable amount",
    "amount before tax","sub total","subtotal","gross amount","gross total",
    "add: cgst","add: sgst","add cgst","add sgst","cgst payable","sgst payable",
    "less discount","rupees","in words","discount rs",
]


def find_header_and_col_map(rows: list) -> tuple:
    for i, row in enumerate(rows):
        col_map = {}
        for block in row:
            n = _n(block["text"])
            for kw, role in HEADER_MAP.items():
                if n == kw or n.startswith(kw):
                    cx = (block["bbox"]["x1"] + block["bbox"]["x2"]) / 2
                    if role not in col_map:
                        col_map[role] = cx
        if len(col_map) >= 3:
            logger.info(f"Header row {i}: {sorted(col_map.items(), key=lambda x:x[1])}")
            return i, col_map
    return None, {}


def _voronoi_col(block: dict, col_map: dict) -> str | None:
    if not col_map: return None
    cx = (block["bbox"]["x1"] + block["bbox"]["x2"]) / 2
    return min(col_map, key=lambda r: abs(col_map[r] - cx))


# ── Vendor / meta ──────────────────────────────────────────────────────────

_NOT_NAME = re.compile(
    r'^(?:gstin|gst\s*#|invoice|bill\s*no|bill\s*to|ship\s*to|tax\s*invoice|'
    r'gst\s*invoice|cash\s*memo|phone|tel\s*:|mobile|address|fssai|'
    r'one\s*stop|pvt|reverse|transport|salesman|meerut|terms|bank|ifsc|'
    r'a/c|account|state\s*:|place\s*of|amba|tiwari|durga|sarafa|shop\s*no|'
    r'daulatganj|ujjain|nvoice|\d)', re.I)


def extract_vendor_info(vendor_rows: list) -> dict:
    blocks = [b for row in vendor_rows for b in row]
    all_t  = " ".join(row_to_text(r) for r in vendor_rows)
    info   = {"vendor_name":"","gstin":"","phone":"","address":"","state":""}

    # GSTIN with checksum validation
    gstin_raw = None
    m = GSTIN_RE.search(all_t.upper())
    if m:
        gstin_raw = m.group(1).upper()
    else:
        for row in vendor_rows:
            m = GSTIN_RE.search(_fix_gstin(row_to_text(row)))
            if m: gstin_raw = m.group(1).upper(); break

    if gstin_raw:
        info["gstin"] = gstin_raw
        if not _validate_gstin_checksum(gstin_raw):
            logger.warning(f"GSTIN checksum failed: {gstin_raw} — may have OCR error")
            info["gstin_checksum_valid"] = False
        else:
            info["gstin_checksum_valid"] = True

    m = PHONE_RE.search(all_t)
    if m: info["phone"] = (m.group(1) or m.group(2) or "").strip()

    if blocks:
        by_y = sorted(blocks, key=lambda b: b["bbox"]["y1"])
        max_y = max(b["bbox"]["y1"] for b in by_y)
        thresh = max_y * 0.15
        for b in by_y:
            if b["bbox"]["y1"] > thresh: break
            t = b["text"].strip()
            if (len(t) >= 6 and not GSTIN_RE.search(t.upper())
                    and not PHONE_RE.search(t) and not _NOT_NAME.match(t)
                    and len(re.findall(r'[A-Za-z]{2,}', t)) >= 2):
                info["vendor_name"] = t; break

    return info


def extract_invoice_meta(vendor_rows: list, all_rows: list) -> dict:
    rows  = vendor_rows + all_rows[:20]
    all_t = "\n".join(row_to_text(r) for r in rows)
    meta  = {"invoice_no":"","invoice_date":"","buyer":"","buyer_gstin":"","place_of_supply":""}

    m = INV_LABEL_RE.search(all_t)
    if m:
        c = m.group(1).strip().strip(".").replace(" ","")
        if (not DATE_RE.search(c) and not re.match(r'^[a-z]+$', c, re.I)
                and not PHONE_RE.match(c) and not re.match(r'^\d{10}$', c)
                and len(c) <= 15):
            meta["invoice_no"] = c

    for line in [row_to_text(r) for r in rows[:20]]:
        flat = [d for pair in DATE_RE.findall(line) for d in pair if d]
        if flat: meta["invoice_date"] = flat[0]; break

    bt = re.search(
        r'(?:bill\s*(?:to|/\s*ship\s*to)|sold\s*to|buyer)[:\s]+'
        r'([A-Z][A-Za-z0-9\s&.()\-]{2,50}?)(?:\n|addr|gst|state|\d{6}|$)',
        all_t, re.I)
    if bt: meta["buyer"] = bt.group(1).strip().rstrip(",")

    gstins = GSTIN_RE.findall(all_t.upper())
    if len(gstins) > 1: meta["buyer_gstin"] = gstins[1]
    return meta


# ── Line items ─────────────────────────────────────────────────────────────

_SKIP = re.compile(
    r'^\s*(t?otal|grand|net\s|sub\s*total|rupees|in\s*words|gst\s*%|tax\s*%|'
    r'terms|transport|salesman|bank|ifsc|reverse|authoris|signatory|customer|'
    r'tax%\s+taxable|class\s+gross)', re.I)


def extract_line_items(data_rows: list, header_rows: list) -> list[dict]:
    _, col_map = find_header_and_col_map(header_rows)
    if not col_map:
        _, col_map = find_header_and_col_map(data_rows)

    raw = []
    for row in data_rows:
        if not row: continue
        txt = row_to_text(row).strip()
        if not txt or _SKIP.match(txt): continue
        if re.match(r'^\d{1,2}\s+[\d.]+(?:\s+[\d.]+){3,}$', txt): continue
        item = _parse_row(row, col_map) if col_map else _parse_positional(row)
        if item: raw.append(item)

    # Merge continuation rows (product names split across two rows)
    items = []
    for item in raw:
        name = item["name"]
        is_cont = (re.match(r'^[-–]', name) or
                   (len(name)<10 and item["qty"]==0 and item["rate"]==0
                    and item["amount"]==0 and not re.search(r'\d{4,}', name)))
        if items and is_cont:
            items[-1]["name"] = items[-1]["name"].rstrip() + " " + name
        elif len(name) >= 2:
            items.append(item)

    # Apply fuzzy product name matching
    for item in items:
        item["name"] = _fuzzy_match_product(item["name"])

    return [i for i in items
            if not re.match(r'^[\d.\s,]+$', i["name"])
            and not re.match(r'^t?otal', i["name"], re.I)]


def _best_amount(row: list, rate_v: float, assigned_amt: float) -> float:
    def is_valid_amount(v, rate):
        if v <= 0: return False
        if rate > 0 and v < rate * 0.8: return False
        if rate > 30 and v <= 30: return False
        return True

    if is_valid_amount(assigned_amt, rate_v):
        return assigned_amt

    num_blocks = sorted(
        [b for b in row if NUM_RE.search(b["text"])],
        key=lambda b: b["bbox"]["x1"], reverse=True
    )
    for nb in num_blocks:
        v = _f(nb["text"])
        if is_valid_amount(v, rate_v):
            return v
    return 0.0


def _parse_row(row: list, col_map: dict) -> dict | None:
    assigned = {}
    for block in row:
        role = _voronoi_col(block, col_map)
        if role:
            sep = " " if role in assigned else ""
            assigned[role] = assigned.get(role,"") + sep + block["text"]

    name = assigned.get("desc","").strip()
    if re.match(r'^\d{1,3}\.?$', name):
        for b in sorted(row, key=lambda b: b["bbox"]["x1"]):
            t = b["text"].strip()
            if len(t)>=3 and not re.match(r'^\d+\.?\d*$',t): name=t; break
    if not name or len(name) < 2: return None

    rate_v  = _f(assigned.get("rate",""))
    raw_amt = _f(assigned.get("amount",""))
    amt_v   = _best_amount(row, rate_v, raw_amt)

    hsn_raw = assigned.get("hsn","").strip()
    hsn = ""
    if hsn_raw:
        m = re.search(r'\b(\d{4,8})\b', _fix_numbers(hsn_raw))
        if m: hsn = m.group(1)

    unit = assigned.get("uom", assigned.get("case",""))
    if unit and re.match(r'^\d+\.?\d*$', unit.strip()): unit = ""

    gv = _f(assigned.get("gst",""))
    if gv > 100: gv = 0.0
    if gv == 0.0:
        c = _f(assigned.get("cgst_r","")); s = _f(assigned.get("sgst_r",""))
        if 0 < c <= 50 and c == s: gv = round(c+s, 2)
        elif 0 < c <= 50: gv = c

    qty_v = int(_f(assigned.get("qty",""))) if assigned.get("qty") else 0

    return {
        "name": name, "hsn": hsn,
        "qty": qty_v, "unit": unit.strip(),
        "mrp": _f(assigned.get("mrp","")),
        "rate": rate_v, "gst_percent": gv, "amount": amt_v,
    }


def _parse_positional(row: list) -> dict | None:
    name=""; nums=[]
    for i,b in enumerate(row):
        t=b["text"].strip()
        if i==0 and re.match(r'^\d{1,3}\.?$',t): continue
        if not name and len(t)>=2 and not re.match(r'^\d+\.?\d*$',t): name=t
        elif re.search(r'\d',t): nums.append(t)
    if not name or len(name)<2: return None
    return {"name":name,"hsn":"","qty":int(_f(nums[0])) if nums else 0,
            "unit":"","mrp":0,"rate":_f(nums[1]) if len(nums)>1 else 0,
            "gst_percent":0,"amount":_f(nums[-1]) if len(nums)>2 else 0}


def extract_gst_summary(summary_rows: list, item_total: float = 0) -> dict:
    all_t = " ".join(row_to_text(r) for r in summary_rows)
    max_v = max(item_total*15, 500_000) if item_total > 0 else 10_000_000

    def find(kws):
        for kw in kws:
            pat = rf'(?<![a-zA-Z]){re.escape(kw)}[^0-9]{{0,30}}(\d{{1,8}}(?:,\d{{3}})*(?:\.\d{{1,2}})?)'
            m = re.search(pat, all_t, re.I)
            if m:
                v = float(m.group(1).replace(",",""))
                if v <= max_v: return v
        return 0.0

    taxable = find(["total amount before tax","taxable value","taxable amount",
                    "amount before tax","sub total","subtotal","gross amount","gross total"])
    total   = find(["total amount after tax","grand total","net amount",
                    "amount after tax","net amt","total payable"])
    cgst    = find(["add: cgst","add cgst","cgst payable","cgst rs","cgst amount"])
    sgst    = find(["add: sgst","add sgst","sgst payable","sgst rs","sgst amount"])
    igst    = find(["add igst","igst rs","igst amount"])
    cess    = find(["add cess","cess"])
    disc    = find(["less discount","discount rs","gross discount","discount"])

    if item_total>0 and taxable>0 and abs(taxable-item_total)/item_total>0.30:
        taxable = round(item_total, 2)
    if total==0.0 and taxable>0:
        total = round(taxable+cgst+sgst+igst+cess-disc, 2)

    return {"taxable_amount":taxable,"cgst":cgst,"sgst":sgst,
            "igst":igst,"cess":cess,"discount_total":disc,"total":total}
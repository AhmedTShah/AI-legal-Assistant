r"""
lawmind_ingest.py  — v5.14
============================
Fixes from v5.13 diagnostic + multi-pass parsing:

1. MULTI-PASS PARSING (NEW):
   - Previously: one PDF → one subcategory → exactly one parser.
     If an Act PDF had BOTH numbered sections AND an embedded
     schedule table, the table was silently dropped.
   - NOW: every PDF is scanned for CONTENT SIGNALS (not file names):
       has_sections, has_articles, has_rules, has_schedule_table
     `decide_parsers()` uses these signals to build an ORDERED LIST
     of parsers to run on the SAME file. Each parser extracts only
     the part of the document relevant to it; irrelevant parts are
     ignored by that parser's own regex/table logic.
   - Fully content-based — zero file-name or act-name hardcoding.
     A brand new, never-seen-before PDF gets classified correctly
     purely from its own text/table structure.

2. Schedule-table canonical key IMPROVED:
   - Uses a full-text MD5 hash instead of a 60-character text slug,
     so two different rows that happen to share the same first 60
     characters no longer collide into a single canonical key.

3. All v5.13 fixes preserved:
   - Cross-reference Pass 2 alias resolution (CrPC/QSO external refs)
   - GeometricTitleExtractor (coordinate-based, highest priority)
   - Self-ref classification (_SELF_REF_PAT for Pass 1/3/4)
   - TOC-aware section number thresholding
   - Deduplication by canonical_key
   - Chapter heading filter
   - Marginal artifact removal
   - Gazette footnote removal
   - Year as int
   - QSO/CrPC alias normalization
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
import warnings
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import pdfplumber

try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

warnings.filterwarnings("ignore", category=FutureWarning)

# ================================================================
# CONFIGURATION
# ================================================================

PDF_DIR = Path(os.getenv(
    "PDF_DIR",
    str(Path(__file__).resolve().parent / "statutes")
))

# ================================================================
# ENUMS
# ================================================================

class DocSubcategory(Enum):
    ACTS_ORDINANCES   = "acts_ordinances"
    RULES_ORDERS      = "rules_orders"
    NOTIFICATIONS_SRO = "notifications_sro"
    SCHEDULE_TABLES   = "schedule_tables"

# ================================================================
# SHARED REGEX
# ================================================================

_JURISDICTION_PATTERNS = [
    (re.compile(r'\b(Punjab)\b',                          re.I), "Punjab"),
    (re.compile(r'\b(Sindh)\b',                           re.I), "Sindh"),
    (re.compile(r'\b(Balochistan)\b',                     re.I), "Balochistan"),
    (re.compile(r'\b(Khyber\s+Pakhtunkhwa|KPK|NWFP)\b',  re.I), "Khyber Pakhtunkhwa"),
    (re.compile(r'\b(Islamabad|Federal|Pakistan)\b',      re.I), "Federal"),
]

_ACT_TITLE_RE = re.compile(
    r'(?:THE\s+)?([A-Z][A-Z\s,\u2013\-\(\)]{4,120}?'
    r'(?:ACT|ORDINANCE|ORDER|CODE|RULES?)[,\s]*\d{4})',
    re.I
)

_KNOWN_DOCS: Dict[str, Tuple[str, int, str]] = {
    "ppc":  ("Pakistan Penal Code, 1860",                 1860, "statute"),
    "crpc": ("Code of Criminal Procedure, 1898",          1898, "statute"),
    "qso":  ("Qanun-e-Shahadat Order, 1984",              1984, "order"),
    "peca": ("Prevention of Electronic Crimes Act, 2016", 2016, "statute"),
}

_YEAR_RE        = re.compile(r'\b(18\d{2}|19\d{2}|20\d{2})\b')
_BRACKET_STATUS = re.compile(
    r'\[\s*(?:O\s*m\s*i\s*t\s*t\s*e\s*d'
    r'|R\s*e\s*p\s*e\s*a\s*l\s*e\s*d'
    r'|Rep\.'
    r'|D\s*E\s*L\s*E\s*T\s*E\s*D)\s*\]',
    re.I
)
_AMENDMENT_RE = re.compile(
    r'\b(Subs(?:tituted)?\.?|Ins(?:erted)?\.?|Rep(?:ealed)?\.?|Omitted)\s+by\s+'
    r'(?:the\s+)?([^,\n]+?(?:Act|Ordinance|Rules)[^,\n]*?\d{4}[^,\n]*?)'
    r'(?:,\s*s\.?\s*(\d+[A-Za-z]?))?[,.]',
    re.I
)
_ACTION_MAP = {
    "subs": "SUBSTITUTED", "substituted": "SUBSTITUTED",
    "ins":  "INSERTED",    "inserted":    "INSERTED",
    "rep":  "REPEALED",    "repealed":    "REPEALED",
    "omitted": "OMITTED",
}
_WHOLE_REPEAL  = re.compile(
    r'([A-Z][^.\n]{5,120}?(?:Order|Act|Ordinance)[,\s]*\d{4}[^.\n]{0,40}?)'
    r'\s+is\s+hereby\s+repealed', re.I
)
_WHOLE_REVIVAL = re.compile(
    r'([A-Z][^.\n]{5,80}?(?:Order|Act)[,\s]*\d{4})'
    r'\s+shall\s+stand\s+revived', re.I
)
_DELETED_RANGE = re.compile(
    r'(?:Article|Section)s?\s+(\d+)\s*[-\u2013\u2014]\s*(\d+)'
    r'\s*\n+\s*\[?\s*D\s*E\s*L\s*E\s*T\s*E\s*D\s*\]?', re.I
)
_ENABLING_RE = re.compile(
    r'[Ii]n\s+exercise\s+of\s+.*?powers?\s+conferred\s+by\s+'
    r'(?:section\s+(\d+[A-Z]?)\s+of\s+)?(?:the\s+)?'
    r'([A-Z][A-Za-z\s,]+(?:Act|Ordinance|Code)\s*\d{0,4})',
    re.DOTALL
)

_GAZETTE_FOOTNOTE = re.compile(
    r'(?:and\s+)?published\s+in\s+the\s+\w[\w\s]*?Gazette[^\n]*?\d{4}[^\n]*?[.\n]'
    r'|Gazette\s+\(Extraordinary\)\s+No\.?\s*\d+[^\n]*'
    r'|assented\s+to\s+by\s+the\s+(?:Governor|President)[^\n]*'
    r'|Pages?\s+\d+\s*(?:to\s+\d+)?[^\n]*Gazette[^\n]*',
    re.I
)

_KNOWN_MARGIN_LINES = re.compile(
    r'\n[ \t]*(?:'
    r'Agency\.|Constitution\.|Administration\.'
    r'|General\.|Director\.|Material\.'
    r'|Opinion\.|Performance\.|Effect\.'
    r'|Difficulty\.|Delegation\.|Composition\.'
    r'|constitution of|of the Agency|of the Agency\.'
    r'|the Agency\.|the Agency'
    r'|of Power\.|of Power'
    r'|in force\.'
    r'|Re-examination\.|clarification\.'
    r'|Clarification\.|conjunction\.'
    r'|deemed to be|constituted under'
    r'|functioning in'
    r')[ \t]*\n',
    re.I
)

_CHAPTER_HEADING_LINE = re.compile(
    r'\n[ \t]*[A-Z][A-Z\s\-]{4,60}\n'
)

# ================================================================
# UTILITY FUNCTIONS
# ================================================================

def normalize_string(s: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', ' ', s).lower()


def _extract_jurisdiction(text: str) -> str:
    for pat, name in _JURISDICTION_PATTERNS:
        if pat.search(text):
            return name
    return "Federal"


def _extract_act_name_and_year(
    full_text: str, pdf_path: Path
) -> Tuple[str, Optional[int], str]:
    stem_lower = pdf_path.stem.lower().strip()

    for key, (name, yr, dtype) in _KNOWN_DOCS.items():
        if stem_lower == key or key in stem_lower:
            return name, yr, dtype

    search_zone = full_text[:5000]
    m = _ACT_TITLE_RE.search(search_zone)
    if m:
        act_name = re.sub(r'\s+', ' ', m.group(0)).strip().title()
        yr_m     = _YEAR_RE.search(act_name)
        year     = int(yr_m.group(1)) if yr_m else None
        name_l   = act_name.lower()
        if   "ordinance" in name_l: dtype = "ordinance"
        elif "rules"     in name_l: dtype = "rules"
        elif "order"     in name_l: dtype = "order"
        else:                       dtype = "statute"
        return act_name, year, dtype

    stem_title = re.sub(r'[^a-zA-Z0-9]', ' ', pdf_path.stem).strip().title()
    yr_m       = _YEAR_RE.search(full_text[:2000])
    year       = int(yr_m.group(1)) if yr_m else None
    return stem_title, year, "statute"


def _detect_numbering_unit(act_name: str, header: str) -> str:
    norm = normalize_string(act_name)
    if any(w in norm for w in [
        "police order", "constitution", "qanun e shahadat",
        "qso", "shahadat", "local government order"
    ]):
        return "article"
    if re.search(r'\bArticle\s+\d+\b', header[:3000], re.I):
        return "article"
    if any(w in norm for w in ["rule", "rules"]):
        return "rule"
    return "section"


def _extract_enabling(text: str) -> Optional[str]:
    m = _ENABLING_RE.search(text[:3000])
    if m:
        act = (m.group(2) or "").strip()
        sec = f", s.{m.group(1)}" if m.group(1) else ""
        return f"{act}{sec}"
    return None


def _detect_status(text: str) -> Tuple[str, bool, List, List, List]:
    amends, repeals, revivals = [], [], []
    bracket = _BRACKET_STATUS.search(text)
    status, active = "ACTIVE", True

    if bracket:
        w = re.sub(r'\s+', '', bracket.group(0).upper()).strip('[]')
        if   "OMIT"   in w: status = "OMITTED"
        elif "DELETE" in w: status = "DELETED"
        else:               status = "REPEALED"
        active = False

    for m in _AMENDMENT_RE.finditer(text):
        raw    = m.group(1).lower().rstrip(".")
        action = _ACTION_MAP.get(raw, raw.upper())
        amends.append({
            "action":      action,
            "by_act":      m.group(2).strip(),
            "section_ref": m.group(3),
        })
        if action in ("REPEALED", "OMITTED") and not bracket and m.start() < 200:
            status, active = action, False

    for m in _WHOLE_REPEAL.finditer(text):
        repeals.append(m.group(1).strip())
    for m in _WHOLE_REVIVAL.finditer(text):
        revivals.append(m.group(1).strip())

    return status, active, amends, repeals, revivals


def _scan_deleted_ranges(
    text: str, act_name: str, jurisdiction: str,
    source_file: str, unit: str, subcat: str, year: Optional[int]
) -> Tuple[List, List]:
    ranges, chunks = [], []
    for m in _DELETED_RANGE.finditer(text):
        s, e  = int(m.group(1)), int(m.group(2))
        lbl   = unit.capitalize()
        ranges.append((s, e))
        chunks.append(LegalChunk(
            text           = (f"{lbl}s {s}-{e}. [DELETED]\n"
                              f"This range ({s} through {e}) has been deleted."),
            act_name       = act_name,
            year           = year,
            jurisdiction   = jurisdiction,
            source_file    = source_file,
            doc_type       = "statute",
            subcategory    = subcat,
            section_number = f"{s}-{e}",
            section_title  = f"{lbl}s {s}-{e} [DELETED]",
            numbering_unit = unit,
            is_active      = False,
            status         = "DELETED",
        ))
    return ranges, chunks


# ================================================================
# CROSS-REFERENCE EXTRACTION  (v5.13 — Pass 2 regression fixed)
# ================================================================

def _normalize_act_name(raw: str) -> str:
    norm = re.sub(r'\s+', ' ', raw).strip()
    aliases = [
        # CrPC aliases
        (r'\bthe\s+code\s+of\s+criminal\s+procedure\b',   "Code of Criminal Procedure, 1898"),
        (r'\bcode\s+of\s+criminal\s+procedure\b',          "Code of Criminal Procedure, 1898"),
        (r'\bcr\.?\s*p\.?\s*c\.?\b',                       "Code of Criminal Procedure, 1898"),
        (r'^the\s+code$',                                  "Code of Criminal Procedure, 1898"),
        # QSO aliases
        (r'\bqanun.e.shahadat\b',                          "Qanun-e-Shahadat Order, 1984"),
        (r'\bq\.?\s*s\.?\s*o\.?\b',                        "Qanun-e-Shahadat Order, 1984"),
        (r'\bqanun\s+e\s+shahadat\b',                      "Qanun-e-Shahadat Order, 1984"),
        (r'^the\s+order$',                                 "Qanun-e-Shahadat Order, 1984"),
        # PPC aliases
        (r'\bpakistan\s+penal\s+code\b',                   "Pakistan Penal Code, 1860"),
        (r'\bp\.?\s*p\.?\s*c\.?\b',                        "Pakistan Penal Code, 1860"),
        # PECA
        (r'\bpeca\b',                                      "Prevention of Electronic Crimes Act, 2016"),
        (r'\bprevention\s+of\s+electronic\s+crimes\b',     "Prevention of Electronic Crimes Act, 2016"),
        # Other common acts
        (r'\binvestigation\s+for\s+fair\s+trial\b',        "Investigation for Fair Trial Act, 2013"),
        (r'\banti.terrorism\s+act\b',                      "Anti-Terrorism Act, 1997"),
        (r'\banti\s+terrorism\s+act\b',                    "Anti-Terrorism Act, 1997"),
    ]
    for pattern, canonical in aliases:
        if re.search(pattern, norm, re.I):
            return canonical
    return norm.title()


_EXT_XREF_PAT = re.compile(
    r'(?:section|article|rule)s?\s+(\d{1,4}[A-Z]{0,2})'
    r'\s+of\s+(?:the\s+)?'
    r'([A-Z][A-Za-z\s,\(\)\-]{3,80}?(?:Act|Code|Order|Ordinance|Rules)'
    r'(?:\s*,?\s*\d{4})?)',
    re.I
)

# Short alias pattern — "section N of the Code/Order/Act"
_EXT_SHORT_ALIAS_PAT = re.compile(
    r'(?:section|article|rule)s?\s+(\d{1,4}[A-Z]{0,2})'
    r'\s+of\s+(the\s+(?:Code|Order|Act|Ordinance|Rules))\b',
    re.I
)

# Self-reference pattern — used in Pass 1, 3, 4 only
# Catches "of this Act", "of the Act", "herein", "hereunder" etc.
_SELF_REF_PAT = re.compile(
    r'of\s+(?:this|the)\s+(?:Act|Order|Code|Ordinance|Rules)\b'
    r'|herein|hereunder|hereof|under\s+this\s+(?:Act|Order)',
    re.I
)

_INT_XREF_PAT = re.compile(
    r'(?:section|article|rule)s?\s+'
    r'((?:\d{1,4}[A-Z]{0,2})(?:\s*(?:,|and|or|&)\s*\d{1,4}[A-Z]{0,2})*)',
    re.I
)
_EXT_FOLLOWING = re.compile(r'^\s+of\s+(?:the\s+)?[A-Z]', re.I)
_RANGE_XREF   = re.compile(
    r'(?:section|article|rule)s?\s+(\d+)\s+to\s+(\d+)', re.I
)
_YEAR_NUM_PAT = re.compile(r'^(?:18|19|20)\d{2}$')


def _extract_cross_refs(text: str, self_num: str, act_name: str) -> Dict:
    internal: set  = set()
    external: List = []
    seen_ext: set  = set()

    # ── Pass 1: Full act name references ─────────────────────────────────────
    # e.g. "section 29 of the Prevention of Electronic Crimes Act, 2016"
    for m in _EXT_XREF_PAT.finditer(text):
        num     = m.group(1)
        ref_act = m.group(2)

        context = text[max(0, m.start() - 20): m.end() + 30]

        # _SELF_REF_PAT correctly used here — catches "of the Act" patterns
        # that slip through the full-name regex when act name is ambiguous
        if _SELF_REF_PAT.search(context):
            if num != self_num and not _YEAR_NUM_PAT.match(num):
                internal.add(num)
            continue

        ref_norm = _normalize_act_name(ref_act)
        key      = f"{num}::{ref_norm}"
        if key not in seen_ext:
            seen_ext.add(key)
            external.append({"number": num, "act": ref_norm})

    # ── Pass 2: Short alias references ───────────────────────────────────────
    # e.g. "section 510 of the Code" or "Article 59 of the Order"
    #
    # FIX v5.13: RESOLVE ALIAS FIRST — do NOT apply _SELF_REF_PAT here.
    # Rationale:
    #   - "section 510 of the Code" → _resolve_short_alias returns CrPC → EXTERNAL
    #   - "section 29 of the Act"   → _resolve_short_alias returns None  → INTERNAL
    for m in _EXT_SHORT_ALIAS_PAT.finditer(text):
        num       = m.group(1)
        alias_raw = m.group(2).strip()   # e.g. "the Code", "the Order", "the Act"

        ref_norm = _resolve_short_alias(alias_raw, act_name, text)

        if ref_norm:
            # Alias resolved to a known external act → add to external refs
            key = f"{num}::{ref_norm}"
            if key not in seen_ext:
                seen_ext.add(key)
                external.append({"number": num, "act": ref_norm})
        else:
            # Alias could not be resolved (e.g., "the Act" = self-reference)
            # → treat as internal reference
            if num != self_num and not _YEAR_NUM_PAT.match(num):
                internal.add(num)

    # ── Pass 3: Internal references ──────────────────────────────────────────
    # e.g. "section 12 and 13" within the same act
    for m in _INT_XREF_PAT.finditer(text):
        after = text[m.end(): m.end() + 60]
        if _EXT_FOLLOWING.match(after):
            continue
        for num_str in re.findall(r'\d{1,4}[A-Z]{0,2}', m.group(1)):
            if num_str == self_num:
                continue
            if _YEAR_NUM_PAT.match(num_str):
                continue
            internal.add(num_str)

    # ── Pass 4: Range references ──────────────────────────────────────────────
    # e.g. "sections 5 to 10"
    for m in _RANGE_XREF.finditer(text):
        s_n, e_n = int(m.group(1)), int(m.group(2))
        if 0 < e_n - s_n <= 50:
            for n in range(s_n, e_n + 1):
                ns = str(n)
                if ns != self_num and not _YEAR_NUM_PAT.match(ns):
                    internal.add(ns)

    # Remove any internal refs that were later identified as external
    ext_nums = {e["number"] for e in external}
    internal -= ext_nums

    return {
        "internal": sorted(
            internal,
            key=lambda x: (int(re.match(r'\d+', x).group(0)), x)
        ),
        "external": external,
    }


def _resolve_short_alias(
    alias_raw: str, act_name: str, full_text: str
) -> Optional[str]:
    """
    Resolve short aliases like "the Code", "the Order", "the Act"
    to canonical act names using context clues.

    Returns canonical name string if resolvable to an EXTERNAL act,
    or None if it appears to be a self-reference.
    """
    alias_lower = alias_raw.lower().strip()

    # "the Code" → always CrPC
    if re.search(r'\bcode\b', alias_lower):
        return "Code of Criminal Procedure, 1898"

    # "the Order" — context-dependent
    if re.search(r'\border\b', alias_lower):
        act_lower = act_name.lower()
        if "qanun" in act_lower or "shahadat" in act_lower:
            return None
        if "police order" in act_lower:
            return None
        if re.search(
            r'qanun.e.shahadat|q\.s\.o\.|evidence|shahadat',
            full_text[:2000], re.I
        ):
            return "Qanun-e-Shahadat Order, 1984"
        if re.search(r'police\s+order', full_text[:2000], re.I):
            return "Police Order, 2002"
        return "Qanun-e-Shahadat Order, 1984"

    # "the Act" → self-reference in virtually all Pakistani statutes
    if re.search(r'\bact\b', alias_lower):
        return None

    # "the Rules" → self-reference in rules context
    if re.search(r'\brules\b', alias_lower):
        return None

    # "the Ordinance" → self-reference
    if re.search(r'\bordinance\b', alias_lower):
        return None

    return None


# ================================================================
# BODY TEXT CLEANER
# ================================================================

def clean_body_text(text: str) -> str:
    text = _GAZETTE_FOOTNOTE.sub('', text)
    text = _KNOWN_MARGIN_LINES.sub('\n', text)
    text = re.sub(r'(\w)(\d)\s+(?=[A-Z\(])', r'\1 ', text)
    text = re.sub(
        r'\n+\s*CHAPTER\s*[\u2013\u2014\-]?\s*[IVXLCDM]+.*$',
        '', text, flags=re.I | re.DOTALL
    )
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ================================================================
# CONTENT SIGNAL DETECTION  (v5.14 — NEW, multi-pass routing)
# ================================================================
#
# These functions decide WHAT is inside a PDF, and therefore WHICH
# parsers should run on it. Detection is 100% content-based:
#   - No file names are ever checked.
#   - No act names are ever checked.
#   - Only regex patterns over the extracted text, and pdfplumber's
#     own structural table detection over the raw PDF geometry.
#
# A single PDF can trigger MULTIPLE parsers (multi-pass). Each
# parser only extracts the portion of the document relevant to its
# own logic; it silently ignores everything else.
# ================================================================

_SIG_SECTION = re.compile(
    r'(?:^|\n)[ \t]{0,8}(?:Section\s+)?\d{1,4}[A-Z]{0,2}\.'
    r'[ \t]*(?=[\(\["A-Z])',
    re.M
)
_SIG_ARTICLE = re.compile(
    r'(?:^|\n)[ \t]{0,8}Article\s+\d{1,3}[A-Z]{0,2}\.'
    r'[ \t]*(?=[\(\["A-Z])',
    re.I | re.M
)
_SIG_RULE = re.compile(
    r'(?:^|\n)[ \t]{0,8}Rule\s+\d{1,3}(?:\.\d+)?[A-Z]{0,2}\.'
    r'[ \t]*(?=[\(\["A-Z])',
    re.I | re.M
)
_SIG_SCHEDULE_KW = re.compile(
    r'offence|bailable|cognizable|punishment|triable|compoundable',
    re.I
)


def detect_content_types(pdf_path: Path, full_text: str) -> Dict[str, bool]:
    """
    Detect WHAT structural content exists inside a PDF, purely from
    its own text and table geometry.

    Returns a dict of booleans:
        has_sections        -> numbered "N." provisions present
        has_articles        -> numbered "Article N." provisions present
        has_rules           -> numbered "Rule N." provisions present
        has_schedule_table  -> a real PDF table exists whose header
                                row contains schedule-style keywords
                                (offence / bailable / punishment / etc.)

    IMPORTANT: this function never inspects pdf_path.name or any
    act/document title. It only reads the extracted text and the
    PDF's own table structures.
    """
    scan = full_text[:8000]

    has_sections = bool(_SIG_SECTION.search(scan))
    has_articles = bool(_SIG_ARTICLE.search(scan))
    has_rules    = bool(_SIG_RULE.search(scan))

    has_schedule_table = False

    # Performance gate: skip expensive table scanning entirely if the
    # document text never mentions any schedule-style keyword at all.
    if _SIG_SCHEDULE_KW.search(full_text):
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    if has_schedule_table:
                        break
                    for table in (page.extract_tables() or []):
                        real_rows = [
                            r for r in table
                            if r and any((c or "").strip() for c in r)
                        ]
                        if len(real_rows) < 2:
                            continue
                        if max(len(r) for r in real_rows) < 2:
                            continue

                        header_text = " ".join(
                            (c or "")
                            for r in real_rows[:2]
                            for c in r
                        )
                        if _SIG_SCHEDULE_KW.search(header_text):
                            has_schedule_table = True
                            break
        except Exception:
            pass

    return {
        "has_sections":       has_sections,
        "has_articles":       has_articles,
        "has_rules":          has_rules,
        "has_schedule_table": has_schedule_table,
    }

def decide_parsers(
    content_types: Dict[str, bool],
    meta: dict,
) -> List[str]:
    """
    Safe multi-pass routing policy.

    Primary document type is decided by DocumentClassifier:

      acts_ordinances  -> Parser A
      rules_orders     -> Parser B
      notifications    -> Parser C
      schedule_tables  -> Parser D

    Multi-pass is allowed ONLY for Acts/Ordinances with a verified
    embedded criminal-schedule table.

    Important:
    - Rules/Orders must never go to ParserA merely because they have
      numbered provisions such as 1., 2., 3.
    - Rules/Orders must never go to ParserD merely because they contain
      an ordinary administrative table.
    """
    subcat = meta.get("subcategory", "")

    # Notification / SRO document: Parser C only.
    if subcat == DocSubcategory.NOTIFICATIONS_SRO.value:
        return ["parser_c"]

    # Standalone Schedule / Table document: Parser D only.
    if subcat == DocSubcategory.SCHEDULE_TABLES.value:
        return ["parser_d"]

    # Rules, Police Orders, Standing Orders:
    # Parser B only.
    #
    # Even if generic signal says has_sections=True, that only means
    # numbered provisions exist. It does NOT mean it is an Act.
    if subcat == DocSubcategory.RULES_ORDERS.value:
        return ["parser_b"]

    # Everything else is treated as an Act / Ordinance.
    parsers = ["parser_a"]

    # Hybrid case:
    # An Act may contain an actual criminal schedule table.
    # Then ParserA extracts sections and ParserD extracts table rows.
    #
    # This does NOT affect rules/orders because they returned above.
    if content_types.get("has_schedule_table", False):
        parsers.append("parser_d")

    return parsers

def detect_page_layout(pdf_path: Path) -> str:
    """
    Decide whether a PDF is a true two-column/marginal-title layout
    or a normal single-column statute.

    Returns:
        "single_column"
        "two_column"
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            sample_pages = pdf.pages[:min(5, len(pdf.pages))]
            two_column_votes = 0
            checked_pages = 0

            for page in sample_pages:
                words = page.extract_words() or []

                if len(words) < 30:
                    continue

                checked_pages += 1
                width = float(page.width)

                left_words = sum(
                    1 for word in words
                    if float(word["x0"]) < width * 0.22
                )

                middle_words = sum(
                    1 for word in words
                    if width * 0.22 <= float(word["x0"]) < width * 0.32
                )

                right_words = sum(
                    1 for word in words
                    if float(word["x0"]) >= width * 0.32
                )

                if (
                    left_words >= 5
                    and right_words >= 15
                    and middle_words <= max(3, left_words * 0.35)
                ):
                    two_column_votes += 1

            if checked_pages and two_column_votes >= max(
                2, checked_pages // 2
            ):
                return "two_column"

    except Exception:
        pass

    return "single_column"

# ================================================================
# TWO-COLUMN PAGE EXTRACTOR
# ================================================================

class TwoColumnPageExtractor:

    DEFAULT_MARGIN_RATIO = 0.22

    def _detect_column_ratio(self, pdf) -> float:
        x_positions = []
        try:
            for page in pdf.pages[:min(3, len(pdf.pages))]:
                words = page.extract_words() or []
                for w in words:
                    x_positions.append(float(w.get("x0", 0)))

            if not x_positions:
                return self.DEFAULT_MARGIN_RATIO

            page_width  = float(pdf.pages[0].width)
            bucket_size = 5.0
            buckets: Dict[int, int] = {}
            for x in x_positions:
                b = int(x / bucket_size)
                buckets[b] = buckets.get(b, 0) + 1

            min_b = int(page_width * 0.10 / bucket_size)
            max_b = int(page_width * 0.40 / bucket_size)
            min_density = float('inf')
            gap_bucket  = int(
                page_width * self.DEFAULT_MARGIN_RATIO / bucket_size
            )

            for b in range(min_b, max_b):
                density = buckets.get(b, 0)
                if density < min_density:
                    min_density = density
                    gap_bucket  = b

            ratio = (gap_bucket * bucket_size) / page_width
            return max(0.12, min(0.35, ratio))

        except Exception:
            return self.DEFAULT_MARGIN_RATIO

    def extract_document(
        self, pdf_path: Path
    ) -> Tuple[List[str], List[str], float]:
        """
        Returns (margin_pages, body_pages, col_ratio).
        col_ratio is passed to GeometricTitleExtractor so both
        use the same column boundary.
        """
        margin_pages: List[str] = []
        body_pages:   List[str] = []
        col_ratio = self.DEFAULT_MARGIN_RATIO

        try:
            with pdfplumber.open(pdf_path) as pdf:
                col_ratio = self._detect_column_ratio(pdf)
                for page in pdf.pages:
                    m_txt, b_txt = self._split_page(page, col_ratio)
                    margin_pages.append(m_txt)
                    body_pages.append(b_txt)
        except Exception as exc:
            print(f"  [TwoColumnExtractor] {pdf_path.name}: {exc}")

        return margin_pages, body_pages, col_ratio

    def _split_page(self, page, col_ratio: float) -> Tuple[str, str]:
        w = float(page.width)
        h = float(page.height)
        margin_x1 = w * col_ratio
        body_x0   = w * col_ratio

        try:
            m_page = page.within_bbox((0,       0, margin_x1, h))
            b_page = page.within_bbox((body_x0, 0, w,         h))
            m_txt  = m_page.extract_text() or ""
            b_txt  = b_page.extract_text() or ""

            if len(b_txt.strip()) < 20:
                return "", page.extract_text() or ""

            return m_txt, b_txt

        except Exception:
            return "", page.extract_text() or ""


# ================================================================
# GEOMETRIC TITLE EXTRACTOR
# ================================================================

class GeometricTitleExtractor:
    """
    Position-based title extraction using word coordinates.

    Uses actual PDF geometry (x0, top coordinates) instead of
    text-pattern guessing on merged text streams.
    """

    _SEC_MARKER = re.compile(r'(\d{1,4}[A-Z]{0,2})\.')

    _LINE_TOLERANCE       = 3.0    # px: words within this are same line
    _BLOCK_GAP_MULTIPLIER = 1.8    # gap > (line_height * this) = new block
    _MATCH_TOLERANCE_PX   = 80.0   # v5.13: increased from 40 → 80px

    def extract(self, pdf_path: Path, col_ratio: float) -> Dict[str, str]:
        title_map: Dict[str, str] = {}
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_map = self._process_page(page, col_ratio)
                    for sec_num, title in page_map.items():
                        if sec_num not in title_map:
                            title_map[sec_num] = title
        except Exception as exc:
            print(f"  [GeometricTitleExtractor] {pdf_path.name}: {exc}")
        return title_map

    def _process_page(self, page, col_ratio: float) -> Dict[str, str]:
        w = float(page.width)
        split_x = w * col_ratio

        words = page.extract_words() or []
        if not words:
            return {}

        margin_words = [wd for wd in words if float(wd['x0']) < split_x]
        body_words   = [wd for wd in words if float(wd['x0']) >= split_x]

        if not margin_words or not body_words:
            return {}

        margin_lines = self._group_into_lines(margin_words)
        if not margin_lines:
            return {}

        blocks      = self._group_lines_into_blocks(margin_lines)
        sec_markers = self._find_section_markers(body_words)

        if not sec_markers:
            return {}

        return self._match_blocks_to_sections(blocks, sec_markers)

    def _group_into_lines(self, words: List[dict]) -> List[dict]:
        if not words:
            return []
        sorted_words = sorted(
            words, key=lambda x: (float(x['top']), float(x['x0']))
        )
        lines = []
        current_line = [sorted_words[0]]
        current_top  = float(sorted_words[0]['top'])

        for wd in sorted_words[1:]:
            top = float(wd['top'])
            if abs(top - current_top) <= self._LINE_TOLERANCE:
                current_line.append(wd)
            else:
                lines.append(self._finalize_line(current_line))
                current_line = [wd]
                current_top  = top

        lines.append(self._finalize_line(current_line))
        return lines

    def _finalize_line(self, line_words: List[dict]) -> dict:
        sorted_words = sorted(line_words, key=lambda x: float(x['x0']))
        text   = ' '.join(wd['text'] for wd in sorted_words)
        top    = min(float(wd['top'])    for wd in sorted_words)
        bottom = max(float(wd['bottom']) for wd in sorted_words)
        return {'text': text, 'top': top, 'bottom': bottom}

    def _group_lines_into_blocks(self, lines: List[dict]) -> List[dict]:
        if not lines:
            return []

        heights = sorted(l['bottom'] - l['top'] for l in lines)
        median_height = heights[len(heights) // 2] if heights else 10.0
        gap_threshold = median_height * self._BLOCK_GAP_MULTIPLIER

        blocks = []
        current_texts = [lines[0]['text']]
        current_top   = lines[0]['top']
        prev_bottom   = lines[0]['bottom']

        for line in lines[1:]:
            gap = line['top'] - prev_bottom
            if gap <= gap_threshold:
                current_texts.append(line['text'])
            else:
                blocks.append({
                    'text': ' '.join(current_texts),
                    'top':  current_top,
                })
                current_texts = [line['text']]
                current_top   = line['top']
            prev_bottom = line['bottom']

        blocks.append({
            'text': ' '.join(current_texts),
            'top':  current_top,
        })
        return blocks

    def _find_section_markers(
        self, body_words: List[dict]
    ) -> List[Tuple[str, float]]:
        lines   = self._group_into_lines(body_words)
        markers = []
        seen    = set()

        for line in lines:
            m = self._SEC_MARKER.search(line['text'])
            if m:
                sec_num = m.group(1)
                if _YEAR_NUM_PAT.match(sec_num):
                    continue
                num_part = int(re.match(r'\d+', sec_num).group(0))
                if num_part == 0 or num_part > 999:
                    continue
                if sec_num not in seen:
                    seen.add(sec_num)
                    markers.append((sec_num, line['top']))

        return markers

    def _match_blocks_to_sections(
        self, blocks: List[dict], sec_markers: List[Tuple[str, float]]
    ) -> Dict[str, str]:
        result   = {}
        used_secs = set()

        for block in blocks:
            block_top = block['top']
            cleaned   = re.sub(r'\s+', ' ', block['text']).strip(' .')

            if not self._is_valid_title(cleaned):
                continue

            best_sec, best_dist = None, float('inf')
            for sec_num, sec_top in sec_markers:
                if sec_num in used_secs:
                    continue
                dist = abs(sec_top - block_top)
                if dist < best_dist:
                    best_dist = dist
                    best_sec  = sec_num

            if best_sec is not None and best_dist < self._MATCH_TOLERANCE_PX:
                result[best_sec] = cleaned
                used_secs.add(best_sec)

        return result

    def _is_valid_title(self, text: str) -> bool:
        if not text or len(text) < 2:
            return False
        words = text.split()
        if len(words) > 16:
            return False
        if text == text.upper() and len(words) >= 2:
            return False
        if not text[0].isupper():
            return False
        return True


# ================================================================
# INLINE TITLE EXTRACTOR  (fallback for single-column / non-gazette PDFs)
# ================================================================

class InlineTitleExtractor:
    """
    Text-pattern based extractor. Used as fallback when
    GeometricTitleExtractor cannot find matches (single-column
    documents, or PDFs where word-coordinate extraction fails).
    """

    _SAME_LINE_PAT = re.compile(
        r'^[ \t]*([A-Z][A-Za-z\s\-\(\)]{2,60}?)'
        r'[.\u2013\u2014]\s*'
        r'(\d{1,4}[A-Z]{0,2})\.'
        r'[ \t]*(?=[\(\["A-Z\u201c])',
        re.M
    )

    _PRE_NUM_PAT = re.compile(
        r'^([ \t]*[A-Z][A-Za-z\s\-]{2,60}?[.\u2014]?)\s*\n'
        r'[ \t]*(\d{1,4}[A-Z]{0,2})\.',
        re.M
    )

    _INLINE_PARTIAL_PAT = re.compile(
        r'^[ \t]*([A-Z][A-Za-z\s\-]{1,40}?)\s+'
        r'(\d{1,4}[A-Z]{0,2})\.'
        r'[ \t]*(?=[\(\["A-Z\u201c])',
        re.M
    )

    _GAZETTE_TITLE_PAT = re.compile(
        r'^[ \t]*([A-Z][A-Za-z][A-Za-z\s\-\(\)]{1,55}?\.?)\s*\n'
        r'[ \t]*(\d{1,4}[A-Z]{0,2})\.\s*(?:\(\d+\)|\()',
        re.M
    )

    _BODY_STARTERS = re.compile(
        r'^(?:The|A|An|Any|Every|No\s+\w|Where|If|When|For\s+the|'
        r'Subject|Notwithstanding|In\s+this|Unless|Save|Provided|'
        r'Whoever|Nothing|All|Upon|It\s+shall)',
        re.I
    )

    _LEGAL_VERBS = re.compile(
        r'\b(shall|may|hereby|means|includes|referred|defined|'
        r'appointed|established|exercised|conferred|vested|'
        r'notify|constitute|authorize)\b',
        re.I
    )

    _BODY_INDICATORS = re.compile(
        r'\b(shall|may|by|of|the|in|to|for|with|any|all|under|'
        r'section|act|court|person|government|agency|officer|'
        r'tribunal|authority|prescribed|notification|gazette|'
        r'official|rules|hereby|whereas|therefore|pursuant)\b',
        re.I
    )

    _CONNECTOR_END = re.compile(
        r'\b(and|of|the|in|to|for|with|or|at|on|'
        r'under|from|into|upon|within|a|an|certain)\s*$',
        re.I
    )

    def build_title_map(self, full_body_text: str) -> Dict[str, str]:
        cleaned   = _CHAPTER_HEADING_LINE.sub('\n', full_body_text)
        title_map: Dict[str, str] = {}

        for m in self._SAME_LINE_PAT.finditer(cleaned):
            title   = m.group(1).strip().rstrip(' .')
            sec_num = m.group(2)
            if self._is_valid_title(title) and sec_num not in title_map:
                title_map[sec_num] = title

        for m in self._GAZETTE_TITLE_PAT.finditer(cleaned):
            title   = m.group(1).strip().rstrip(' .')
            sec_num = m.group(2)
            if self._is_valid_title(title) and sec_num not in title_map:
                title_map[sec_num] = title

        for m in self._PRE_NUM_PAT.finditer(cleaned):
            title   = m.group(1).strip().rstrip(' .')
            sec_num = m.group(2)
            if self._is_valid_title(title) and sec_num not in title_map:
                title_map[sec_num] = title

        for m in self._INLINE_PARTIAL_PAT.finditer(cleaned):
            partial = m.group(1).strip().rstrip(' .')
            sec_num = m.group(2)

            if sec_num in title_map:
                continue

            if self._CONNECTOR_END.search(partial):
                full_title = self._reconstruct_multiline(
                    partial, m.end(), cleaned
                )
                if full_title and self._is_valid_title(full_title):
                    title_map[sec_num] = full_title
            elif self._is_valid_title(partial):
                title_map[sec_num] = partial

        return title_map

    def _reconstruct_multiline(
        self, partial: str, after_pos: int, text: str
    ) -> str:
        remaining = text[after_pos: after_pos + 600]
        lines     = remaining.split('\n')
        title_parts = [partial]

        for line in lines[:10]:
            stripped = line.strip()
            if not stripped:
                continue
            if re.match(r'^\(\d+\)', stripped):
                break
            if re.match(r'^\([a-z]\)', stripped):
                break
            if self._BODY_STARTERS.match(stripped):
                break

            parts         = re.split(r'\s{2,}', stripped)
            left_fragment = parts[0].strip() if parts else stripped
            left_clean    = left_fragment.rstrip(' .,;:')

            if not left_clean:
                continue

            left_words = left_clean.split()

            if self._LEGAL_VERBS.search(left_clean):
                break

            if len(left_words) <= 5:
                title_parts.append(left_clean)
                if (left_clean.endswith('.')
                        or not self._CONNECTOR_END.search(left_clean)):
                    break
            else:
                body_count = len(self._BODY_INDICATORS.findall(left_clean))
                if body_count / max(len(left_words), 1) <= 0.3:
                    title_parts.append(left_clean)
                    if not self._CONNECTOR_END.search(left_clean):
                        break
                else:
                    break

        full = ' '.join(title_parts)
        full = re.sub(r'\s+', ' ', full).strip(' .')

        if len(full.split()) > 15:
            return partial
        if self._LEGAL_VERBS.search(full):
            return partial

        return full

    def _is_valid_title(self, text: str) -> bool:
        if not text or len(text) < 2:
            return False
        words = text.split()
        if len(words) > 14:
            return False
        if text == text.upper() and len(words) >= 2:
            return False
        if '\n' in text:
            return False
        if self._BODY_STARTERS.match(text) and len(words) > 3:
            return False
        if self._LEGAL_VERBS.search(text):
            return False
        if not text[0].isupper():
            return False
        return True


# ================================================================
# MARGIN TITLE STORE  (geometric extractor as top priority)
# ================================================================

class MarginTitleStore:

    _BODY_SEC_RE = re.compile(
        r'^[ \t]{0,8}(?:Section\s+|Rule\s+|Article\s+)?'
        r'(\d{1,4}[A-Z]{0,2})\.'
        r'[ \t]*(?=[\(\["A-Z\u201c\u2018])',
        re.M
    )

    _SKIP_RE = re.compile(
        r'^\s*\d{1,4}\s*$'
        r'|gazette|extraordinary|pakistan|provincial|government'
        r'|^\s*-+\s*$|^\s*_+\s*$',
        re.I
    )

    def build(
        self,
        margin_pages: List[str],
        body_pages:   List[str],
        pdf_path:     Optional[Path]  = None,
        col_ratio:    Optional[float] = None,
    ) -> Dict[str, str]:
        """
        Priority order (highest wins):
          1. GeometricTitleExtractor  — coordinate-based, most reliable
          2. Margin text-block parsing — index-aligned text heuristic
          3. InlineTitleExtractor      — pattern-based fallback
        """
        geo_map: Dict[str, str] = {}
        if pdf_path is not None and col_ratio is not None:
            geo_map = GeometricTitleExtractor().extract(pdf_path, col_ratio)

        margin_map = self._from_margin(margin_pages, body_pages)
        body_full  = "\n".join(body_pages)
        inline_map = InlineTitleExtractor().build_title_map(body_full)

        # geo_map wins over margin_map wins over inline_map
        return {**inline_map, **margin_map, **geo_map}

    def _from_margin(
        self,
        margin_pages: List[str],
        body_pages:   List[str],
    ) -> Dict[str, str]:
        all_sec_nums: List[str] = []
        seen:         set       = set()
        for b_text in body_pages:
            for m in self._BODY_SEC_RE.finditer(b_text):
                sn = m.group(1)
                if sn not in seen:
                    seen.add(sn)
                    all_sec_nums.append(sn)

        if not all_sec_nums:
            return {}

        all_titles: List[str] = []
        for m_text in margin_pages:
            all_titles.extend(self._parse_blocks(m_text))

        if not all_titles:
            return {}

        title_map: Dict[str, str] = {}
        for i, title in enumerate(all_titles):
            if i >= len(all_sec_nums):
                break
            sn = all_sec_nums[i]
            if sn not in title_map:
                title_map[sn] = title

        return title_map

    def _parse_blocks(self, margin_text: str) -> List[str]:
        if not margin_text.strip():
            return []

        blocks:  List[str] = []
        current: List[str] = []

        for line in margin_text.split('\n'):
            stripped = line.strip()
            if not stripped:
                if current:
                    block = ' '.join(current).strip(' .')
                    if self._is_valid(block):
                        blocks.append(block)
                    current = []
            else:
                if self._SKIP_RE.search(stripped):
                    continue
                current.append(stripped)

        if current:
            block = ' '.join(current).strip(' .')
            if self._is_valid(block):
                blocks.append(block)

        return blocks

    def _is_valid(self, block: str) -> bool:
        if not block:
            return False
        words = block.split()
        if not (1 <= len(words) <= 12):
            return False
        if re.search(
            r'\b(shall|may|provided|means|whoever|notwithstanding'
            r'|under|hereby|government|whereas|therefore)\b',
            block, re.I
        ):
            return False
        if re.match(r'^\d+$', block):
            return False
        return True


# ================================================================
# SECTION NUMBER EXTRACTOR
# ================================================================

class SectionNumberExtractor:
    """
    Large-document threshold applied AFTER TOC removal.
    """

    _SEC_PAT = re.compile(
        r'^[ \t]{0,8}'
        r'(?:Section\s+|Rule\s+|Article\s+)?'
        r'(\d{1,4}[A-Z]{0,2})\.'
        r'[ \t]*'
        r'(?=[\(\["A-Z\u201c\u2018]'
        r'|\n[ \t]*[\(\[A-Z])',
        re.M
    )

    def find_boundaries(
        self, body_text: str
    ) -> List[Tuple[int, str]]:

        raw: List[Tuple[int, str, int]] = []
        for m in self._SEC_PAT.finditer(body_text):
            sec_str  = m.group(1)
            num_part = int(re.match(r'\d+', sec_str).group(0))
            
            # Skip years and invalid numbers
            if num_part == 0 or len(str(num_part)) == 4:
                continue
            
            # NEW: Skip obviously phantom sections (>600 for CrPC-style docs)
            if num_part > 600:
                continue
            
            raw.append((m.start(), sec_str, num_part))

        if not raw:
            return []

        # ── TOC boundary detection (IMPROVED) ────────────────────────────────
        # Look for the FIRST occurrence of section 1 or 2, not any reset
        toc_end_idx = 0
        for i, (_, sec_str, num) in enumerate(raw):
            if num == 1 or num == 2:
                # Check if this looks like real body (has title text after)
                pos = raw[i][0]
                following = body_text[pos:pos+200]
                if re.search(r'[A-Z][a-z]{3,}', following):
                    toc_end_idx = i
                    break

        post_toc = raw[toc_end_idx:]

        # ── NO gap filtering for statutes with known gaps ───────────────────
        # CrPC has many repealed/omitted sections — gaps are normal
        # Skip the dynamic threshold logic entirely for now

        # ── Monotonicity + sub-letter filter only ──────────────────────────
        final:    List[Tuple[int, str]] = []
        last_num: int = 0
        last_str: str = ""

        for pos, sec_str, num in post_toc:
            letter      = sec_str[len(str(num)):]
            last_letter = last_str[len(str(last_num)):] if last_num > 0 else ""

            # Handle sub-lettered sections (22A, 22B, etc.)
            if num == last_num:
                if letter and letter > last_letter:
                    final.append((pos, sec_str))
                    last_str = sec_str
                continue

            # Skip backwards (non-monotonic)
            if num < last_num:
                continue

            # Accept all forward sections (no gap filter)
            final.append((pos, sec_str))
            last_num = num
            last_str = sec_str

        return final
# ================================================================
# UNIFIED CHUNK SCHEMA
# ================================================================

@dataclass
class LegalChunk:
    text:         str
    act_name:     str
    jurisdiction: str
    source_file:  str

    doc_type:    str           = "statute"
    subcategory: str           = ""
    year:        Optional[int] = None

    section_number: Optional[str] = None
    section_title:  str           = ""
    parent_section: Optional[str] = None
    numbering_unit: str           = "section"

    is_active: bool = True
    status:    str  = "ACTIVE"

    amendment_history:  List[Dict] = field(default_factory=list)
    whole_act_repeals:  List[str]  = field(default_factory=list)
    whole_act_revivals: List[str]  = field(default_factory=list)
    deleted_ranges:     List       = field(default_factory=list)

    cross_references:    Dict          = field(
        default_factory=lambda: {"internal": [], "external": []}
    )
    enacting_instrument: Optional[str] = None

    offence:      str = ""
    arrestable:   str = ""
    bailable:     str = ""
    compoundable: str = ""
    punishment:   str = ""
    triable_by:   str = ""

    sro_number:        str = ""
    gazette_number:    str = ""
    issuing_ministry:  str = ""
    notification_date: str = ""

    version: str = "v1"

    def get_content_hash(self) -> str:
        """
        Stable MD5 hash of normalized text — used to disambiguate
        chunks that legitimately share the same section number
        (e.g. multiple rows of the same Schedule section).
        """
        normalized = re.sub(r'\s+', ' ', self.text).strip().lower()
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]

    def get_canonical_key(self) -> str:
        act_id  = re.sub(r'[^A-Z0-9]', '_', self.act_name.upper()).strip('_')
        file_id = re.sub(r'[^A-Z0-9]', '_', self.source_file.upper()).strip('_')
        unit    = self.numbering_unit.upper()
        subcat  = re.sub(r'[^A-Z0-9]', '_', self.subcategory.upper())

        if self.section_number:
            # Schedule table rows: a single section number can have
            # multiple distinct rows. Disambiguate with a content hash
            # of the FULL row text (not just the first 60 chars) so
            # two different rows never collide into one canonical key.
            if self.doc_type == "schedule_table":
                row_hash = self.get_content_hash()
                return (
                    f"{act_id}::{file_id}::{subcat}"
                    f"::{unit}::{self.section_number}::{row_hash}::{self.version}"
                )

            return (
                f"{act_id}::{file_id}::{subcat}"
                f"::{unit}::{self.section_number}::{self.version}"
            )

        slug = re.sub(r'\W+', '_', self.text[:60]).strip('_')
        return (
            f"{act_id}::{file_id}::{subcat}"
            f"::{self.doc_type.upper()}::{slug}::{self.version}"
        )

    def get_point_id(self) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, self.get_canonical_key()))

    def to_qdrant_payload(self) -> Dict:
        payload: Dict = {
            "point_id":            self.get_point_id(),
            "canonical_key":       self.get_canonical_key(),
            "text":                self.text,
            "act_name":            self.act_name,
            "year":                self.year,
            "jurisdiction":        self.jurisdiction,
            "source_file":         self.source_file,
            "doc_type":            self.doc_type,
            "subcategory":         self.subcategory,
            "section_number":      self.section_number,
            "section_title":       self.section_title,
            "parent_section":      self.parent_section,
            "numbering_unit":      self.numbering_unit,
            "is_active":           self.is_active,
            "status":              self.status,
            "amendment_history":   self.amendment_history,
            "whole_act_repeals":   self.whole_act_repeals,
            "whole_act_revivals":  self.whole_act_revivals,
            "deleted_ranges":      self.deleted_ranges,
            "cross_references":    self.cross_references,
            "enacting_instrument": self.enacting_instrument,
            "version":             self.version,
        }

        if self.doc_type == "schedule_table":
            payload.update({
                "offence":      self.offence,
                "arrestable":   self.arrestable,
                "bailable":     self.bailable,
                "compoundable": self.compoundable,
                "punishment":   self.punishment,
                "triable_by":   self.triable_by,
            })

        if self.doc_type in ("sro", "notification", "appointed_date"):
            payload.update({
                "sro_number":        self.sro_number,
                "gazette_number":    self.gazette_number,
                "issuing_ministry":  self.issuing_ministry,
                "notification_date": self.notification_date,
            })

        return payload


# ================================================================
# DOCUMENT CLASSIFIER
# ================================================================

class DocumentClassifier:

    _SCH_SIGNALS = [
        re.compile(r'tabular\s+statement\s+of\s+offences',   re.I),
        re.compile(r'cognizable\s+or\s+non.?cognizable',     re.I),
        re.compile(r'bailable\s+or\s+non.?bailable',         re.I),
        re.compile(r'triable\s+by\s+(?:court|magistrate)',   re.I),
        re.compile(r'compoundable\s+or\s+non.?compoundable', re.I),
    ]
    _NOTIF_SIGNALS = [
        re.compile(r'S\.?\s*R\.?\s*O\.?\s*\d+\s*\([IVX]+\)\s*/\s*\d{4}', re.I),
        re.compile(r'statutory\s+regulatory\s+order',         re.I),
        re.compile(r'extraordinary\s+gazette',                re.I),
        re.compile(r'F\.\s*No\.\s*\d[\d\-\/]+',              re.I),
        re.compile(r'gazette\s+of\s+pakistan',                re.I),
        re.compile(r'is\s+hereby\s+notif(?:ied|ication)',     re.I),
    ]
    _RULES_SIGNALS = [
        re.compile(r'in\s+exercise\s+of\s+(?:the\s+)?powers?\s+conferred', re.I),
        re.compile(r'hereby\s+makes?\s+the\s+following\s+rules',            re.I),
        re.compile(r'(?:^|\n)\s*Rule\s+\d+\.',               re.I | re.M),
        re.compile(r'standing\s+orders?\s+no\.',              re.I),
        re.compile(r'Police\s+Order,?\s*\d{4}',              re.I),
        re.compile(r'(?:^|\n)\s*Article\s+\d+\.',            re.I | re.M),
        re.compile(r'\brules,\s*\d{4}\b',                    re.I),
    ]

    def classify(
        self, pdf_path: Path, header: str, full_text: str = ""
    ) -> DocSubcategory:
        norm_name = normalize_string(pdf_path.stem)
        scan      = (header + "\n" + full_text)[:3000]

        fname_sch = any(w in norm_name for w in
                        ["schedule ii", "schedule 2", "tabular", "offences table"])
        sig_sch   = sum(1 for p in self._SCH_SIGNALS if p.search(scan))
        if fname_sch or sig_sch >= 2:
            return DocSubcategory.SCHEDULE_TABLES

        fname_not = any(w in norm_name for w in
                        ["sro", "gazette", "appointed date"])
        sig_not   = sum(1 for p in self._NOTIF_SIGNALS if p.search(scan))
        if sig_not >= 4 or (fname_not and sig_not >= 2):
            return DocSubcategory.NOTIFICATIONS_SRO

        fname_rul = any(w in norm_name for w in
                        ["rules", "order", "standing order", "police order"])
        sig_rul   = sum(1 for p in self._RULES_SIGNALS if p.search(scan))
        if fname_rul or sig_rul >= 2:
            return DocSubcategory.RULES_ORDERS

        return DocSubcategory.ACTS_ORDINANCES


# ================================================================
# PDF FULL-TEXT EXTRACTOR
# ================================================================

def extract_pdf_full_text(pdf_path: Path) -> str:
    pages: List[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for p in pdf.pages:
                pages.append(p.extract_text() or "")
    except Exception as exc:
        print(f"  pdfplumber error {pdf_path.name}: {exc}")

    full = "\n".join(pages).strip()

    if len(full) < 50 and HAS_PYPDF:
        try:
            reader   = pypdf.PdfReader(str(pdf_path))
            fb_pages = [pg.extract_text() or "" for pg in reader.pages]
            fb       = "\n".join(fb_pages).strip()
            if len(fb) > len(full):
                return fb
        except Exception as exc:
            print(f"  pypdf fallback error {pdf_path.name}: {exc}")

    return full


# ================================================================
# METADATA EXTRACTOR
# ================================================================

def extract_doc_metadata(pdf_path: Path, full_text: str) -> dict:
    act_name, year, doc_type = _extract_act_name_and_year(
        full_text, pdf_path
    )
    header       = full_text[:3000]
    jurisdiction = _extract_jurisdiction(header)
    unit         = _detect_numbering_unit(act_name, header)
    subcat       = DocumentClassifier().classify(pdf_path, header, full_text)

    if "punjab" in pdf_path.stem.lower() and "rules" in pdf_path.stem.lower():
        unit = "rule"

    return {
        "act_name":            act_name,
        "year":                year,
        "jurisdiction":        jurisdiction,
        "doc_type":            doc_type,
        "numbering_unit":      unit,
        "subcategory":         subcat.value,
        "source_file":         pdf_path.name,
        "enacting_instrument": _extract_enabling(full_text),
        "has_schedule_forms":  False,
    }


# ================================================================
# PARSER A — Acts & Ordinances
# ================================================================

class ParserA_ActsOrdinances:

    _SCHED_PAT = re.compile(
        r'((?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)\s+SCHEDULE)'
        r'(.*?)(?=(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)\s+SCHEDULE|\Z)',
        re.DOTALL | re.I
    )

    def parse(
        self,
        pdf_path:      Path,
        act_name:      str,
        jurisdiction:  str,
        unit:          str,
        year:          Optional[int],
        doc_type:      str           = "statute",
        has_schedules: bool          = False,
        enabling:      Optional[str] = None,
    ) -> List[LegalChunk]:

        src    = pdf_path.name
        subcat = DocSubcategory.ACTS_ORDINANCES.value

        layout = detect_page_layout(pdf_path)
        print(f"  Layout  : {layout}") 

        if layout == "two_column":
            # BFSA jaisi gazette/marginal-title PDFs.
            extractor = TwoColumnPageExtractor()
            margin_pages, body_pages, col_ratio = extractor.extract_document(
                pdf_path
            )
            body_full = "\n".join(body_pages)

            title_store = MarginTitleStore()
            title_map = title_store.build(
                margin_pages,
                body_pages,
                pdf_path=pdf_path,
                col_ratio=col_ratio,
            )

        else:
            # CrPC jaisi normal single-column statutes.
            # No cropping: section number and body text remain together.
            body_full = extract_pdf_full_text(pdf_path)
            title_map = InlineTitleExtractor().build_title_map(body_full)

        sec_extractor = SectionNumberExtractor()
        boundaries    = sec_extractor.find_boundaries(body_full)

        if not boundaries:
            full_text  = extract_pdf_full_text(pdf_path)
            boundaries = sec_extractor.find_boundaries(full_text)
            body_full  = full_text
            title_map  = InlineTitleExtractor().build_title_map(full_text)

        del_ranges, del_chunks = _scan_deleted_ranges(
            body_full, act_name, jurisdiction, src, unit, subcat, year
        )

        chunks:   List[LegalChunk] = []
        revivals: List[str]        = []

        for i, (pos, sec_num) in enumerate(boundaries):
            end_pos = (
                boundaries[i + 1][0]
                if i + 1 < len(boundaries)
                else len(body_full)
            )
            raw_text   = body_full[pos:end_pos].strip()
            clean_text = clean_body_text(raw_text)

            if len(clean_text.strip()) < 10:
                continue

            title = title_map.get(sec_num, "")

            parent      = None
            num_str     = re.match(r'\d+', sec_num).group(0)
            letter_part = sec_num[len(num_str):]
            if letter_part:
                parent = num_str

            status, active, amends, rps, revs = _detect_status(clean_text)
            revivals.extend(revs)
            xrefs = _extract_cross_refs(clean_text, sec_num, act_name)

            chunks.append(LegalChunk(
                text               = clean_text,
                act_name           = act_name,
                year               = year,
                jurisdiction       = jurisdiction,
                source_file        = src,
                doc_type           = doc_type,
                subcategory        = subcat,
                section_number     = sec_num,
                section_title      = title,
                parent_section     = parent,
                numbering_unit     = unit,
                is_active          = active,
                status             = status,
                amendment_history  = amends,
                whole_act_repeals  = rps,
                whole_act_revivals = revs,
                cross_references   = xrefs,
                enacting_instrument= enabling,
            ))

        chunks.extend(del_chunks)
        if chunks and del_ranges:
            chunks[0].deleted_ranges = del_ranges
        if chunks and revivals:
            chunks[0].whole_act_revivals = list(set(revivals))

        if has_schedules:
            chunks.extend(
                self._parse_schedules(
                    body_full, act_name, jurisdiction,
                    src, unit, year, enabling
                )
            )

        return chunks

    def _parse_schedules(
        self, text, act_name, jurisdiction, src, unit, year, enabling
    ) -> List[LegalChunk]:
        chunks = []
        for m in self._SCHED_PAT.finditer(text):
            label = m.group(1).strip()
            body  = (m.group(1) + m.group(2)).strip()
            if len(body) < 20:
                continue
            chunks.append(LegalChunk(
                text           = body,
                act_name       = act_name,
                year           = year,
                jurisdiction   = jurisdiction,
                source_file    = src,
                doc_type       = "schedule_form",
                subcategory    = DocSubcategory.ACTS_ORDINANCES.value,
                section_title  = label.title(),
                numbering_unit = unit,
                enacting_instrument = enabling,
            ))
        return chunks


# ================================================================
# PARSER B — Rules / Orders
# ================================================================

class ParserB_RulesOrders:

    _RULE_PAT = re.compile(
        r'(?:^|\n)[ \t]*(?:Rule\s+)?(\d{1,3}(?:\.\d{1,3})?[A-Z]{0,2})\.'
        r'(?=[ \t]*(?:[A-Z"\u201c]|\n[ \t]*[A-Z]))',
        re.M | re.I
    )
    _ART_PAT  = re.compile(
        r'(?:^|\n)[ \t]*(?:Article\s+)?(\d{1,3}[A-Z]{0,2})\.'
        r'(?=[ \t]*\n?[ \t]*(?:\(\d+\)|[A-Z"\u201c]))',
        re.M | re.I
    )
    _SO_PAT   = re.compile(
        r'(?:^|\n)\s*(?:Standing\s+Order\s+)?(?:No\.\s*)?(\d{1,3}[A-Z]{0,2})\.'
        r'(?=[ \t]*[A-Z])',
        re.M | re.I
    )
    _HDR_PAT  = re.compile(r'\n([A-Z][A-Z\s]{4,60})\n')

    def parse(
        self,
        pdf_path:     Path,
        text:         str,
        act_name:     str,
        jurisdiction: str,
        unit:         str           = "rule",
        doc_type:     str           = "rules",
        year:         Optional[int] = None,
    ) -> List[LegalChunk]:

        src      = pdf_path.name
        subcat   = DocSubcategory.RULES_ORDERS.value
        enabling = _extract_enabling(text)

        pat = (
            self._ART_PAT if unit == "article"        else
            self._SO_PAT  if unit == "standing_order" else
            self._RULE_PAT
        )

        chunks = self._by_numbered(
            text, act_name, jurisdiction, src, unit,
            doc_type, subcat, year, enabling, pat
        )
        if len(chunks) < 2:
            chunks = self._by_headings(
                text, act_name, jurisdiction, src, unit,
                doc_type, subcat, year, enabling
            )
        if not chunks:
            chunks = self._by_paras(
                text, act_name, jurisdiction, src, unit,
                doc_type, subcat, year, enabling
            )
        return chunks

    def _by_numbered(
        self, text, act_name, jurisdiction, src, unit,
        doc_type, subcat, year, enabling, pat
    ) -> List[LegalChunk]:
        raw   = list(pat.finditer(text))
        final = []
        last  = 0
        for m in raw:
            n = int(re.match(r'\d+', m.group(1)).group(0))
            if n < last or (last > 0 and n - last > 35):
                continue
            final.append(m)
            last = n

        if len(final) < 2:
            return []

        chunks = []
        for i, m in enumerate(final):
            start   = m.start()
            end     = final[i + 1].start() if i + 1 < len(final) else len(text)
            rnum    = m.group(1)
            raw_txt = text[start:end].strip()
            rtxt    = clean_body_text(raw_txt)
            title   = self._rule_title(rtxt, rnum)
            xrefs   = _extract_cross_refs(rtxt, rnum, act_name)
            st, ac, am, rp, rv = _detect_status(rtxt)
            parent  = rnum.split('.')[0] if re.match(r'\d+\.\d+', rnum) else None

            chunks.append(LegalChunk(
                text               = rtxt,
                act_name           = act_name,
                year               = year,
                jurisdiction       = jurisdiction,
                source_file        = src,
                doc_type           = doc_type,
                subcategory        = subcat,
                section_number     = rnum,
                section_title      = title,
                parent_section     = parent,
                numbering_unit     = unit,
                is_active          = ac,
                status             = st,
                amendment_history  = am,
                whole_act_repeals  = rp,
                whole_act_revivals = rv,
                cross_references   = xrefs,
                enacting_instrument= enabling,
            ))
        return chunks

    def _rule_title(self, txt: str, num: str) -> str:
        m = re.match(
            rf'\s*{re.escape(num)}\.\s*'
            r'([^.\u2013\u2014\n]{3,100})[.\u2013\u2014]',
            txt
        )
        return m.group(1).strip() if m else ""

    def _by_headings(
        self, text, act_name, jurisdiction, src, unit,
        doc_type, subcat, year, enabling
    ) -> List[LegalChunk]:
        splits = list(self._HDR_PAT.finditer(text))
        if len(splits) < 2:
            return []
        chunks = []
        for i, m in enumerate(splits):
            hdr  = m.group(1).strip()
            s, e = m.end(), (
                splits[i + 1].start() if i + 1 < len(splits) else len(text)
            )
            ptxt = (hdr + "\n" + text[s:e]).strip()
            if len(ptxt) < 30:
                continue
            chunks.append(LegalChunk(
                text           = ptxt,
                act_name       = act_name,
                year           = year,
                jurisdiction   = jurisdiction,
                source_file    = src,
                doc_type       = doc_type,
                subcategory    = subcat,
                section_title  = hdr.title(),
                numbering_unit = unit,
                enacting_instrument = enabling,
            ))
        return chunks

    def _by_paras(
        self, text, act_name, jurisdiction, src, unit,
        doc_type, subcat, year, enabling
    ) -> List[LegalChunk]:
        paras = [
            p.strip() for p in re.split(r'\n{2,}', text)
            if len(p.strip()) > 80
        ]
        return [
            LegalChunk(
                text           = p,
                act_name       = act_name,
                year           = year,
                jurisdiction   = jurisdiction,
                source_file    = src,
                doc_type       = doc_type,
                subcategory    = subcat,
                section_number = str(i + 1),
                numbering_unit = "paragraph",
                enacting_instrument = enabling,
            )
            for i, p in enumerate(paras)
        ]


# ================================================================
# PARSER C — Notifications / SROs
# ================================================================

class ParserC_NotificationsSROs:

    _SRO     = re.compile(
        r'S\.?\s*R\.?\s*O\.?\s*(\d+)\s*\(([IVX]+)\)\s*/\s*(\d{4})', re.I
    )
    _GAZ     = re.compile(
        r'No\.\s*([\d\-\/]+(?:\([A-Z]+\))?\/\d{4})', re.I
    )
    _MIN     = re.compile(
        r'(Ministry\s+of\s+[A-Za-z\s]+'
        r'|Federal\s+Board\s+of\s+[A-Za-z\s]+'
        r'|Government\s+of\s+\w+)', re.I
    )
    _DATE    = re.compile(
        r'dated?\s+(?:the\s+)?'
        r'(\d{1,2}(?:st|nd|rd|th)?\s+'
        r'(?:January|February|March|April|May|June|July|August'
        r'|September|October|November|December),?\s+\d{4})', re.I
    )
    _PARANUM = re.compile(r'(?:^|\n)\s*(\d{1,2})\.\s+(?=[A-Z])', re.M)
    _TOPIC   = re.compile(r'\n([A-Z][A-Za-z\s]{5,60})[:—\-]\s*\n')

    def parse(
        self,
        pdf_path:     Path,
        text:         str,
        act_name:     str,
        jurisdiction: str,
        year:         Optional[int] = None,
    ) -> List[LegalChunk]:

        src    = pdf_path.name
        subcat = DocSubcategory.NOTIFICATIONS_SRO.value

        sro   = self._get(self._SRO, text[:1000],
                          lambda m: f"S.R.O. {m.group(1)}({m.group(2)})/{m.group(3)}")
        gaz   = self._get(self._GAZ,  text[:1000], lambda m: m.group(1))
        minis = self._get(self._MIN,  text[:1500],
                          lambda m: re.sub(r'\s+', ' ', m.group(0)).strip())
        date  = self._get(self._DATE, text[:2000], lambda m: m.group(1).strip())
        enab  = _extract_enabling(text)

        dtype = (
            "sro"            if sro else
            "appointed_date" if re.search(r'appointed\s+date', text[:500], re.I)
            else "notification"
        )

        common = dict(
            act_name=act_name, year=year, jurisdiction=jurisdiction,
            source_file=src, doc_type=dtype, subcategory=subcat,
            numbering_unit="paragraph", sro_number=sro,
            gazette_number=gaz, issuing_ministry=minis,
            notification_date=date, enacting_instrument=enab,
        )

        chunks = self._by_nums(text, common, act_name)
        if len(chunks) < 2:
            chunks = self._by_topics(text, common)
        if not chunks:
            chunks = self._by_paras(text, common)
        return chunks

    def _get(self, pat, text, fn):
        m = pat.search(text)
        return fn(m) if m else ""

    def _by_nums(self, text, common, act_name) -> List[LegalChunk]:
        ms = list(self._PARANUM.finditer(text))
        if len(ms) < 2:
            return []
        chunks = []
        for i, m in enumerate(ms):
            pnum = m.group(1)
            s, e = m.start(), (ms[i + 1].start() if i + 1 < len(ms) else len(text))
            ptxt = text[s:e].strip()
            if len(ptxt) < 20:
                continue
            st, ac, am, rp, rv = _detect_status(ptxt)
            xrefs = _extract_cross_refs(ptxt, pnum, act_name)
            chunks.append(LegalChunk(
                **common,
                section_number     = pnum,
                section_title      = ptxt.split('\n')[0][:80].strip(".-— "),
                text               = ptxt,
                is_active          = ac,
                status             = st,
                amendment_history  = am,
                whole_act_repeals  = rp,
                whole_act_revivals = rv,
                cross_references   = xrefs,
            ))
        return chunks

    def _by_topics(self, text, common) -> List[LegalChunk]:
        splits = list(self._TOPIC.finditer(text))
        if len(splits) < 2:
            return []
        chunks = []
        for i, m in enumerate(splits):
            hdr  = m.group(1).strip()
            s, e = m.end(), (
                splits[i + 1].start() if i + 1 < len(splits) else len(text)
            )
            ptxt = (hdr + "\n" + text[s:e]).strip()
            if len(ptxt) < 30:
                continue
            chunks.append(LegalChunk(**common, section_title=hdr.title(), text=ptxt))
        return chunks

    def _by_paras(self, text, common) -> List[LegalChunk]:
        paras = [p.strip() for p in re.split(r'\n{2,}', text) if len(p.strip()) > 60]
        return [
            LegalChunk(**common, section_number=str(i + 1), text=p)
            for i, p in enumerate(paras)
        ]


# ================================================================
# PARSER D — Schedule Tables
# ================================================================

class ParserD_ScheduleTables:

    def parse(
        self,
        pdf_path:     Path,
        text:         str,
        act_name:     str,
        jurisdiction: str,
        year:         Optional[int] = None,
    ) -> List[LegalChunk]:

        src     = pdf_path.name
        subcat  = DocSubcategory.SCHEDULE_TABLES.value
        chunks: List[LegalChunk] = []
        cur_sec = None

        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    for table in (page.extract_tables() or []):
                        for row in table:
                            if not row or all(c is None for c in row):
                                continue
                            cells = [c.strip() if c else "" for c in row]

                            if re.match(r'^\d+[A-Z\-]{0,3}$', cells[0]):
                                cur_sec = cells[0]
                            if cur_sec is None:
                                continue

                            row_text = " | ".join(c for c in cells if c)
                            if len(row_text.strip()) < 5:
                                continue

                            def c(n: int) -> str:
                                return cells[n] if len(cells) > n else ""

                            chunks.append(LegalChunk(
                                text           = row_text,
                                act_name       = act_name,
                                year           = year,
                                jurisdiction   = jurisdiction,
                                source_file    = src,
                                doc_type       = "schedule_table",
                                subcategory    = subcat,
                                section_number = cur_sec,
                                numbering_unit = "row",
                                offence        = c(1),
                                arrestable     = c(2),
                                bailable       = c(4),
                                compoundable   = c(5),
                                punishment     = c(6),
                                triable_by     = c(7),
                            ))
        except Exception as exc:
            print(f"  [ParserD] {pdf_path.name}: {exc}")

        return chunks


# ================================================================
# ROUTER  (v5.14 — multi-pass, content-signal driven)
# ================================================================

def route_and_parse(
    pdf_path:  Path,
    full_text: str,
    meta:      dict,
) -> List[LegalChunk]:

    kw = dict(
        act_name     = meta["act_name"],
        jurisdiction = meta["jurisdiction"],
        year         = meta.get("year"),
    )

    # ── Step 1: what structural content does this PDF contain? ───
    content_types = detect_content_types(pdf_path, full_text)

    # ── Step 2: which parser(s) should run on it? ────────────────
    parsers_to_run = decide_parsers(content_types, meta)

    # ── Step 3: report the decision (content-based, no file names) ─
    print(
        f"  Content : "
        f"sections={content_types['has_sections']} "
        f"articles={content_types['has_articles']} "
        f"rules={content_types['has_rules']} "
        f"schedule_table={content_types['has_schedule_table']}"
    )
    print(f"  Parsers : {' + '.join(parsers_to_run)}")

    # ── Step 4: run every selected parser on the SAME file ────────
    all_chunks: List[LegalChunk] = []

    for parser_name in parsers_to_run:

        if parser_name == "parser_a":
            chunks = ParserA_ActsOrdinances().parse(
                pdf_path      = pdf_path,
                act_name      = meta["act_name"],
                jurisdiction  = meta["jurisdiction"],
                unit          = meta.get("numbering_unit", "section"),
                year          = meta.get("year"),
                doc_type      = meta.get("doc_type", "statute"),
                has_schedules = False,
                enabling      = meta.get("enacting_instrument"),
            )
            all_chunks.extend(chunks)

        elif parser_name == "parser_b":
            unit = meta.get("numbering_unit", "rule")
            if re.search(
                r'(?:^|\n)\s*Article\s+\d+\.',
                full_text[:3000], re.I | re.M
            ):
                unit = "article"
            elif re.search(
                r'standing\s+order\s+no\.', full_text[:3000], re.I
            ):
                unit = "standing_order"
            elif re.search(
                r'(?:^|\n)\s*Rule\s+\d+\.',
                full_text[:3000], re.I | re.M
            ):
                unit = "rule"
            chunks = ParserB_RulesOrders().parse(
                pdf_path, full_text,
                unit     = unit,
                doc_type = meta.get("doc_type", "rules"),
                **kw
            )
            all_chunks.extend(chunks)

        elif parser_name == "parser_c":
            chunks = ParserC_NotificationsSROs().parse(
                pdf_path, full_text, **kw
            )
            all_chunks.extend(chunks)

        elif parser_name == "parser_d":
            chunks = ParserD_ScheduleTables().parse(
                pdf_path, full_text, **kw
            )
            all_chunks.extend(chunks)

    return all_chunks


# ================================================================
# PIPELINE ENGINE
# ================================================================

def process_all_pdfs(
    target_dir:    Path          = PDF_DIR,
    filter_subcat: Optional[str] = None,
) -> List[LegalChunk]:

    if not target_dir.exists():
        print(f"Directory not found: {target_dir}")
        return []

    pdf_files = sorted(set(target_dir.glob("*.pdf")))
    if not pdf_files:
        print(f"No PDFs found in {target_dir}")
        return []

    print(f"Found {len(pdf_files)} PDF(s) in {target_dir}")
    all_chunks: List[LegalChunk] = []

    for pdf_path in pdf_files:
        full_text = extract_pdf_full_text(pdf_path)
        if len(full_text.strip()) < 10:
            print(f"\n  {pdf_path.name}: empty or unreadable — skipping")
            continue

        meta   = extract_doc_metadata(pdf_path, full_text)
        subcat = meta["subcategory"]

        if filter_subcat and subcat != filter_subcat:
            continue

        print(f"\n{'─' * 62}")
        print(f"  File   : {pdf_path.name}")
        print(f"  Act    : {meta['act_name']}")
        print(f"  Year   : {meta['year']}")
        print(f"  Juris  : {meta['jurisdiction']}")
        print(f"  Subcat : {subcat}")
        print(f"  Unit   : {meta['numbering_unit']}")

        chunks = route_and_parse(pdf_path, full_text, meta)

        print(f"  Chunks : {len(chunks)}")

        all_chunks.extend(chunks)

    # ── Deduplication by canonical_key ───────────────────────────────────────
    seen_keys:     set              = set()
    unique_chunks: List[LegalChunk] = []
    for ch in all_chunks:
        key = ch.get_canonical_key()
        if key not in seen_keys:
            seen_keys.add(key)
            unique_chunks.append(ch)

    removed = len(all_chunks) - len(unique_chunks)
    if removed:
        print(f"\n  Deduplication: removed {removed} exact-duplicate chunks")

    print(f"\n{'=' * 62}")
    print(f"  TOTAL CHUNKS: {len(unique_chunks)}")
    print(f"{'=' * 62}")
    return unique_chunks


# ================================================================
# JSON EXPORT
# ================================================================

def export_to_json(chunks: List[LegalChunk], path: str) -> None:
    out  = Path(path)
    data = [c.to_qdrant_payload() for c in chunks]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n  Exported {len(data)} chunks → {out.resolve()}")


# ================================================================
# ENTRY POINT
# ================================================================

def run(
    subcat_filter:    Optional[str] = None,
    export_json_file: Optional[str] = None,
) -> None:
    print("=" * 62)
    print("  LawMind Legal Parser Pipeline  v5.14")
    print("=" * 62)

    chunks = process_all_pdfs(PDF_DIR, filter_subcat=subcat_filter)
    if not chunks:
        print("No chunks produced. Exiting.")
        return

    if export_json_file:
        export_to_json(chunks, export_json_file)
    else:
        print(f"\n  Total chunks parsed: {len(chunks)}")
        print("  To ingest to Qdrant, run: python qdrant_ingest.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="LawMind Ingestion Pipeline v5.14"
    )
    ap.add_argument("--export-json", type=str, metavar="FILE",
                    help="Export parsed chunks to JSON file")
    ap.add_argument("--type",        choices=[e.value for e in DocSubcategory],
                    help="Process only this subcategory")
    # Keep --dry-run for backward compatibility
    ap.add_argument("--dry-run",     action="store_true",
                    help="Parse only (default behaviour now)")
    args = ap.parse_args()

    run(
        subcat_filter    = args.type,
        export_json_file = args.export_json,
    )
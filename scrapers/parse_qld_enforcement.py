"""Fetch and parse the Queensland register of published enforcement actions.

Source: Queensland Department of Education, Early Childhood Education and Care regulatory
authority. Licence: CC BY 4.0 by default on qed.qld.gov.au (see
research/2026-10-29-register-enforcement-nsw-vic-qld-cth.md section 3; confirmation that the
statement covers earlychildhood.qld.gov.au is still open).
Attribution: State of Queensland (Department of Education) 2026.

The register is one HTML page with a table per year. Columns: "Provider or individual name /
Service name", "Date of action", "Details", "Breaches (if applicable)". It prints NO service
or provider approval numbers, so those columns are always null here and the join to ACECQA
must be made by name and location.

Privacy: the first column can name natural persons (fined educators, sole-trader providers).
Individual names are never stored. For such rows provider_name is null, the linked document
URLs (whose file names usually embed the person's name) are withheld, and a service name is
kept only when it shares no word with the withheld name. Every other text column of a withheld
row (action text, reason, legal references, notes) has each word of the name redacted. Because
the page gives no explicit flag, a printed name with no legal-entity or business word in it is
treated as an individual, and so is any name profile_providers.classify_entity_form classes as
likely_individual (an individual trustee, a deceased estate or executor, an accented personal
name) even when it carries a word such as 'trust'. That errs towards withholding; it can wrongly
withhold an entity with an unusual name.

Linked documents are NOT downloaded in this version.

Run: python3 scrapers/parse_qld_enforcement.py [--skip-fetch] [--force]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

if __package__ in (None, ""):  # allow `python3 scrapers/parse_qld_enforcement.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.common import (
    PROJECT_ROOT,
    RAW_DIR,
    assign_record_ids,
    ensure_person_names,
    fetch,
    keep_withheld_names,
    list_snapshots,
    log,
    normalise_pr,
    normalise_se,
    note_withheld_subject,
    printed_fingerprint,
    refuse_if_reparse_incomplete,
    withhold_free_text,
    withhold_prose_naming_people,
    write_processed,
    write_snapshot,
)
from scrapers.profile_providers import classify_entity_form, name_is_withheld

SOURCE = "qld-enforcement"
JURISDICTION = "QLD"
INDEX_URL = (
    "https://earlychildhood.qld.gov.au/regulation/compliance-and-enforcement/"
    "register-published-enforcement-actions"
)
SCHEMA_PATH = "data/schemas/enforcement-action.schema.json"
OUTPUT_NAME = "qld-enforcement-actions"

FIELDNAMES = [
    "record_id",
    "jurisdiction",
    "source_register",
    "source_document",
    "source_snapshot",
    "captured_at",
    "service_approval_number",
    "service_approval_number_raw",
    "provider_approval_number",
    "provider_approval_number_raw",
    "service_name",
    "provider_name",
    "address",
    "suburb",
    "state",
    "postcode",
    "action_type",
    "action_type_raw",
    "reason",
    "legal_references",
    "date_issued",
    "date_issued_raw",
    "period_label",
    "notes",
    # Extra column, not in the schema: every other URL linked from the Details cell.
    "linked_documents",
    # Structured fact taken from the printed headline before any free text is withheld.
    "penalty_amount_aud",
]

NO_APPROVAL_NOTE = "register prints no approval number; join by name and address"
INDIVIDUAL_NOTE = "subject is an individual; name withheld"

_INVISIBLE = re.compile(r"[​‌‍⁠﻿]")
_DOC_EXT = (".pdf", ".docx", ".doc")
_STOPWORDS = {"and", "the", "of", "for", "pty", "ltd"}

# Words that mark a legal entity.
_LEGAL = re.compile(
    r"\b(pty|ltd|limited|proprietary|inc|incorporated|association|trust|trustee|trustees|"
    r"corporation|council|company|co-operative|cooperative|foundation|society|college|"
    r"school|university|atf|holdings|p&c)\b|\(qld\)",
    re.IGNORECASE,
)
# Words that mark a business or service name rather than a person.
_BUSINESS = re.compile(
    r"\b(kindergarten|childcare|child care|care|learning|education|educational|centre|centres|"
    r"center|early|kids|kindy|preschool|school hours|day care|services|group|church|network)\b",
    re.IGNORECASE,
)
# Generic role descriptors the register prints instead of a name.
_ROLE_PREFIX = re.compile(
    r"^(individual|educator|nominated supervisor|certified supervisor|supervisor|"
    r"family day care educator)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def clean(text: str | None) -> str:
    """Strip zero-width characters, normalise spaces. Keeps printed punctuation."""
    if not text:
        return ""
    text = _INVISIBLE.sub("", text.replace("\xa0", " "))
    return re.sub(r"\s+", " ", text).strip()


def pieces(cell) -> list[str]:
    """Visible text fragments of a cell, in order, cleaned, blanks dropped."""
    return [c for c in (clean(s) for s in cell.stripped_strings) if c]


_FINED = re.compile(r"(?i)(?<![a-z])fined(?![a-z])")
_DOLLARS = re.compile(r"[$][ ]?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:[.]([0-9]{2}))?(?![0-9])")


_FINE_WORD = re.compile(r"(?i)(?<![a-z])(?:fined|fine|fines|penalty|penalties)(?![a-z])")
_AMOUNT = r"[$][ ]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:[.][0-9]{2})?(?![0-9])"
FINE_NOT_RECORDED_NOTE = (
    "penalty amount not recorded: the printed amount is not tied explicitly and solely to the fine"
)
# Follow-up to PR #6: an amount printed with a magnitude word or abbreviation ('$1.5 million',
# '$15k'), a decimal that is not cents, or digit grouping that is not standard is not a whole,
# unambiguous figure; nothing is scaled or completed.
FINE_ABBREVIATED_NOTE = (
    "penalty amount not recorded: the printed amount is abbreviated or not a whole dollar figure"
)
# A per-offence or 'each' amount may not be the total fine.
FINE_PER_OFFENCE_NOTE = (
    "penalty amount not recorded: the printed amount may be per offence, not the total fine"
)
# PR #9: anything that is not one of the recognised single-total forms below.
FINE_NOT_SINGLE_TOTAL_NOTE = "fine not recorded: wording is not a recognised single total"
_MONEY_RAW = re.compile(
    r"(?i)[$][ ]?([0-9][0-9,]*)(?:[.]([0-9]+))?"
    r"(?:[ ]?(k|m|bn|b|million|millions|thousand|thousands|billion|mil)(?![a-z]))?"
)
_WHOLE_GROUPING = re.compile(r"^(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)$")
# PR #9: an allowlist (project rule 3: null with a note, never a wrong figure). A figure is
# recorded only from one of these single-total forms in the headline alone, ending the
# headline or a sentence ('.' then a capital or the end; never , ; or :) or followed by a stated
# reason: 'fined $N', 'was fined $N.', 'fined $N for|after|over|following|in relation
# to|regarding|relating to ...', 'fined a total of $N', 'total fine of $N'.
_TOTAL_FORM = re.compile(
    rf"(?i)(?<![a-z])(?:fined(?:[ ]+a[ ]+total[ ]+of)?|total[ ]+fine[ ]+of)[ ]+({_AMOUNT})(?![,.][0-9])"
    r"(?=[ ]*(?:[.](?-i:[ ]+[A-Z]|[ ]*$)|$)|[ ]+(?:for|after|over|following|in[ ]+relation[ ]+to|regarding"
    r"|relating[ ]+to)(?![a-z]))"
)


def _words(*phrases: str) -> re.Pattern:
    alternatives = "|".join(p.replace(" ", r"[ ]+") for p in phrases)
    return re.compile(rf"(?i)(?<![a-z])(?:{alternatives})(?![a-z])")


# Guards over all of the row's text (PR #9, Codex round 1): any one gives null.
_PER_ITEM = re.compile(
    _words(
        "each",
        "every",
        "per",
        "apiece",
        "a time",
        "times",
        "respectively",
        # rates
        "a day",
        "daily",
        "a week",
        "weekly",
        "a month",
        "monthly",
        "a year",
        "per annum",
        "annually",
        "an hour",
        # multipliers
        "multiplied",
        "twice",
        "thrice",
        "double",
        "both",
        # PR #9, Codex round 2
        "fortnightly",
        "tripled",
        "triple",
        "three-fold",
        "threefold",
        "two-fold",
        "twofold",
    ).pattern
    + r"|(?<![a-z])x[ ]?[0-9]|×"
)
# Costs and other components (PR #10: expenses, disbursements, 'the sum|the amount includes').
_COST_NOUNS = r"(?:costs?|fees?|charges?|levy|levies|expenses?|disbursements?)"
_COSTS = re.compile(
    _words("costs?", "plus", "the (?:sum|amount) (?:includes|included|including)").pattern
    + r"|(?i:(?<![a-z])(?:including|includes|included|inclusive[ ]+of)(?:[ ]+[^ ]+){0,3}?[ ]+"
    + rf"(?:{_COST_NOUNS}(?![a-z])|[$]))"
    + rf"|(?i:(?<![a-z]){_COST_NOUNS}(?:[ ]+[^ ]+){{0,3}}?[ ]+"
    + r"(?:including|includes|included)(?![a-z]))"
)
_NOT_A_TOTAL = _words(
    "part-suspended",
    "suspended",
    "partially",
    # modality and negation
    "not",
    "never",
    "no fine",
    "could",
    # a modal "may" only before a verb, so the month never matches (PR #9, Codex round 1)
    "may (?:be|face|receive|incur|pay|have|attract|yet|still)",
    # prospective (PR #9, Codex round 2)
    "will",
    "shall",
    "liable",
    "yet to be",
    "pending",
    "proposed",
    "intends",
    "intended",
    # withdrawn or set aside (PR #9, Codex round 2)
    "withdrawn",
    "withdraw",
    "quashed",
    "revoked",
    "rescinded",
    "cancelled",
    "canceled",
    "waived",
    "remitted",
    "refunded",
    "dismissed",
    "discontinued",
    # another party (PR #9, Codex round 2)
    "another",
    "other",
    "second",
    "separate",
    "co-accused",
    "might",
    "would",
    "faces",
    "faced",
    "facing",
    "potential",
    "possible",
    "up to",
    "maximum",
    "max",
    # a changed or deferred figure
    "originally",
    "initially",
    "reduced",
    "varied",
    "increased",
    "appeal",
    "appealed",
    "overturned",
    "set aside",
    "sets aside",
    "setting aside",
    "set-aside",
    "substituted",
    # annulled or reversed (PR #9, Codex round 3)
    "annul",
    "annulled",
    "annulment",
    "nullified",
    "nullify",
    "void",
    "voided",
    "reversed",
    "reversal",
    "vacated",
    # stayed, discharged or deferred (PR #10, Codex round 4)
    "stayed",
    "stay of",
    "discharged",
    "deferred",
    "postponed",
    # imposed jointly or shared (PR #10, Codex round 4)
    "jointly",
    "joint",
    "and others",
    "shared",
    "apportioned",
    "instalments",
    "to be paid",
    "payable",
)
# Another person fined in a provider's row. On an individual or role row, a role word is
# allowed only in the headline's first clause before the single 'fined', where it names the
# row's own subject (PR #9, Codex round 2).
_ROLE_WORDS = _words(
    "director",
    "educator",
    "employee",
    "staff",
    "supervisor",
    "nominated",
    "individual",
    "person",
    "worker",
    "manager",
)
# 'fined', 'fining', or 'fine(s)' used as a verb: exactly one in the row text, or null.
_FINE_VERB = re.compile(
    r"(?i)(?<![a-z])(?:fined|fining|fines?[ ]+(?:the|a|an|them|him|her|it|this|that)(?![a-z]))"
)
# An organisation named in a later clause before 'fined' ('Provider warned; operator fined').
_ORG_NOUN = _words(
    "organisation",
    "organization",
    "company",
    "provider",
    "operator",
    "entity",
    "business",
    "service",
    "centre",
    "center",
)
# The row subject's own leading noun phrase ends at the first conjunction or clause break.
_CONJUNCTION = _words("and", "or", "but", "while", "whereas")
_CLAUSE_BREAK = re.compile(r"[;:]|[.](?=[ ]+[A-Z])")
# Amounts in a format the forms do not read ('AUD 4,000', 'A$4,000', '4,000 dollars', a
# full-width dollar sign): counted, and never recorded.
_OTHER_AMOUNT = re.compile(
    r"(?i)(?<![a-z])(?:aud|a[$]|au[$])[ ]?[0-9]|＄|[0-9](?:[0-9,.]*[0-9])?[ ]?(?:dollars?|aud)(?![a-z])"
)


def _dollars(token: str) -> int | float:
    m = _DOLLARS.search(token)
    whole = int(m.group(1).replace(",", ""))
    return whole + int(m.group(2)) / 100 if m.group(2) else whole


def fine_amount_and_note(
    text: str | None, row_text: str | None = None, *, subject_is_person: bool = False
) -> tuple[int | float | None, str | None]:
    """(fine in dollars, note) from a printed headline (Codex round 5, finding 3; PR #7 to #9).

    An allowlist that fails closed (project rule 3: null with a note, never a wrong figure).
    `text` is the headline; `row_text` is all of the row's details text (every paragraph and
    label), defaulting to the headline. `subject_is_person` is True on a row whose subject is
    an individual or a role; a role word is then allowed only in the headline's first clause
    before the single 'fined' (_subject_is_the_rows_own); every other guard is kept. Recorded only when the row text prints exactly one
    dollar amount, as a whole figure (cents optional), the headline holds it in one of the
    single-total forms of _TOTAL_FORM, and no guard word appears anywhere in the row text.
    Otherwise the value is None with the most specific note: abbreviated amount, per-item or
    rate wording, costs or more than one amount, or a wording that is not a recognised single
    total. Never a guess, never scaled."""
    text = (text or "").replace("\xa0", " ")
    row_text = (row_text or "").replace("\xa0", " ")
    # The row text holds the headline once; a headline outside it is added, never twice.
    full = row_text if text in row_text else " ".join(t for t in (text, row_text) if t)
    if not full or not _FINE_WORD.search(full):
        return None, None
    counted = full
    raw = [
        m
        for m in _MONEY_RAW.finditer(counted)
        if not counted[: m.start()].lower().endswith(("a", "au"))
    ]
    other = list(_OTHER_AMOUNT.finditer(counted))
    if not raw and not other:
        return None, None
    for m in raw:
        digits, decimals, magnitude = m.group(1).rstrip(","), m.group(2), m.group(3)
        if magnitude or (decimals is not None and len(decimals) != 2):
            return None, FINE_ABBREVIATED_NOTE
        if not _WHOLE_GROUPING.match(digits):
            return None, FINE_ABBREVIATED_NOTE
    if _PER_ITEM.search(full):
        return None, FINE_PER_OFFENCE_NOTE
    if _COSTS.search(full) or len(raw) + len(other) != 1:
        return None, FINE_NOT_RECORDED_NOTE
    form = _TOTAL_FORM.search(text)
    if other or _NOT_A_TOTAL.search(full) or not form:
        return None, FINE_NOT_SINGLE_TOTAL_NOTE
    if len(_FINE_VERB.findall(full)) > 1 or not _subject_is_the_rows_own(
        text, full, subject_is_person, form.start()
    ):
        return None, FINE_NOT_SINGLE_TOTAL_NOTE
    return _dollars(form.group(1)), None


def _subject_is_the_rows_own(
    text: str, full: str, subject_is_person: bool, form_start: int | None = None
) -> bool:
    """False when the one 'fined' may name someone other than the row's subject (PR #9, Codex
    rounds 2 and 3). The lead is the headline before the total form ('fined', 'total fine of'); its leading noun phrase, up to the
    first conjunction (and, or, but, while, whereas) or clause break, is the row's own subject.
    False when an organisation or role noun appears in the lead after that phrase; when the
    leading phrase of an organisation or service row names no organisation; when a role word
    appears in the leading phrase of an organisation or service row; or when a role word
    appears anywhere else in the row text."""
    if form_start is None:
        verb = _FINE_VERB.search(text)
        form_start = verb.start() if verb else len(text)
    lead = text[:form_start]
    ends = [m.start() for m in (_CONJUNCTION.search(lead), _CLAUSE_BREAK.search(lead)) if m]
    own = lead[: min(ends)] if ends else lead
    rest = lead[len(own) :]
    # PR #10 (Codex round 4): any clause break before 'fined' gives null ('Provider; X was fined').
    if _CLAUSE_BREAK.search(lead) or _ORG_NOUN.search(rest) or _ROLE_WORDS.search(rest):
        return False
    # On an organisation or service row the leading phrase must name an organisation (or be
    # empty, as in 'Fined $N for ...' or 'A total fine of $N'); a personal name there may be
    # someone else's fine.
    if not subject_is_person and own.strip().lower() not in ("", "a", "an", "the"):
        if not (_ORG_NOUN.search(own) or _LEGAL.search(own) or _BUSINESS.search(own)):
            return False
    roles = list(_ROLE_WORDS.finditer(full))
    if not roles:
        return True
    start = full.find(text)
    own_end = start + len(own)
    in_own = start >= 0 and all(start <= m.start() and m.end() <= own_end for m in roles)
    return subject_is_person and in_own


def extract_fine_amount(text: str | None) -> int | float | None:
    """The fine in dollars, or None (see fine_amount_and_note)."""
    return fine_amount_and_note(text)[0]


def parse_date(raw: str) -> tuple[str | None, str | None]:
    """d/m/y (Queensland style) -> (ISO date, warning). Two-digit years are read as 20yy."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", raw.strip())
    if not m:
        return None, f"date not parsable: {raw!r}"
    day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
    warning = None
    if len(year) == 2:
        year_i = 2000 + int(year)
        warning = f"two-digit year {raw!r} read as {year_i}"
    else:
        year_i = int(year)
    try:
        return date(year_i, month, day).isoformat(), warning
    except ValueError:
        return None, f"date not valid: {raw!r}"


# ---------------------------------------------------------------------------
# Subject classification (entity or individual)
# ---------------------------------------------------------------------------


def classify_subject(first: str, *, has_service_line: bool) -> str:
    """Return 'role', 'individual', 'entity' or 'service_only' for the first printed name.

    role          generic descriptor such as 'Educator - centre-based service' (no name printed)
    individual    printed name with no legal or business marker (treated as a natural person)
    entity        legal-entity name, or a business-like name in the provider position
    service_only  single business-like name with no legal marker (probably a service name)
    """
    if _ROLE_PREFIX.match(first):
        return "role"
    # Person signals beat legal and business words: '<person> ATF <trust>', a deceased estate
    # or its executors, and accented personal names are individuals.
    if classify_entity_form(first) == "likely_individual":
        return "individual"
    if _LEGAL.search(first) or (_BUSINESS.search(first) and has_service_line):
        # A provider name is kept only when the shared fail-closed rule accepts it.
        return "individual" if name_is_withheld(first) else "entity"
    if _BUSINESS.search(first):
        return "service_only"
    return "individual"


def withheld_by_shared_rule_only(first: str, *, has_service_line: bool) -> bool:
    """True when the subject reads as an organisation by this register's own markers and is
    withheld only by the shared fail-closed rule (PR #11: such names are kept as keyed hashes for
    the join; a subject that reads as a person or a role never is)."""
    return (
        not _ROLE_PREFIX.match(first)
        and classify_entity_form(first) != "likely_individual"
        and bool(_LEGAL.search(first) or (_BUSINESS.search(first) and has_service_line))
        and name_is_withheld(first)
    )


# A word of any letters, accented ones included ('Zoë' must not split into 'Zo' and 'e').
_WORD = re.compile(r"[^\W\d_](?:[^\W\d_]|['’\-])+")


def name_tokens(name: str) -> set[str]:
    words = _WORD.findall(name.lower())
    return {w.strip("'’-") for w in words if len(w) >= 3 and w not in _STOPWORDS}


def contains_token(text: str, tokens: set[str]) -> bool:
    found = {w.strip("'’-") for w in _WORD.findall(text.lower())}
    return bool(found & tokens)


# ---------------------------------------------------------------------------
# Action type mapping (conservative)
# ---------------------------------------------------------------------------


def map_action_type(raw: str, *, prosecution_label: bool) -> tuple[str, str | None]:
    """Map the printed Details text to the schema enum. Returns (action_type, note)."""
    low = raw.lower()
    # Events that undo or close an earlier action are not new actions of that kind.
    if re.search(r"\b(lifted|discharged|revoked|withdrawn|ended|expired)\b", low):
        return "other", "printed text records the end of an earlier action; kept as other"
    if prosecution_label:
        return "prosecution", None
    if "infringement notice" in low:
        return "infringement_notice", None
    if re.search(r"\bcancellation\b|\bcancelled\b", low):
        return "approval_cancelled", None
    if re.search(r"\bsuspension\b|\bsuspended\b", low):
        return "approval_suspended", None
    if "emergency action notice" in low:
        return "emergency_action_notice", None
    if "compliance notice" in low:
        return "compliance_notice", None
    if "compliance direction" in low:
        return "compliance_direction", None
    if "enforceable undertaking" in low:
        return "enforceable_undertaking", None
    if "show cause" in low:
        return "show_cause_notice", None
    if "prohibition notice" in low:
        return "prohibition_notice", None
    if "direction to exclude" in low:
        return "direction_to_exclude", None
    if re.search(r"\bconditions?\b", low):
        return "condition_imposed", None
    if re.search(r"\b(fine|fined|penalty)\b", low):
        return "other", "fine printed without a Prosecution or infringement notice label"
    return "other", None


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------


def _is_register_table(table) -> bool:
    first = table.find("tr")
    return bool(first and "date of action" in clean(first.get_text(" ")).lower())


def _period_label(table) -> str | None:
    heading = table.find_previous(["h1", "h2", "h3", "h4", "h5"])
    text = clean(heading.get_text(" ")) if heading else ""
    return text if re.fullmatch(r"(19|20)\d{2}", text) else None


def parse_row(tr, *, period: str | None, page_url: str) -> dict | None:
    cells = tr.find_all(["td", "th"])
    if len(cells) < 4:
        log.warning("row with %d cells skipped", len(cells))
        return None
    name_parts = pieces(cells[0])
    date_raw = clean(cells[1].get_text(" "))
    details = cells[2]
    breach_parts = pieces(cells[3])
    if not name_parts and not date_raw:
        return None

    # Details: headline is the first paragraph, or the cell text when there are no paragraphs.
    link_labels = [clean(a.get_text(" ")) for a in details.find_all("a")]
    link_labels = [t for t in link_labels if t]
    paras = [clean(p.get_text(" ")) for p in details.find_all("p")]
    paras = [p for p in paras if p]
    prosecution_label = any(t.lower() == "prosecution" for t in link_labels)
    labels = [t for t in link_labels if t.lower() != "further information"]
    if paras and paras[0].lower() not in {"prosecution", "further information"}:
        headline = paras[0]
        extra_labels = [t for t in labels if t != headline]
    else:
        headline = labels[0] if labels else clean(details.get_text(" "))
        extra_labels = labels[1:]
    action_type_raw = " ".join([headline, *extra_labels]).strip()
    action_type, type_note = map_action_type(action_type_raw, prosecution_label=prosecution_label)
    reason = headline if extra_labels else None

    # Linked documents (PDF preferred as the primary source document).
    hrefs: list[str] = []
    for a in details.find_all("a", href=True):
        url = urljoin(page_url, a["href"].strip().replace(" ", "%20"))
        if url.startswith("https://") and url not in hrefs:
            hrefs.append(url)
    docs = [u for u in hrefs if urlsplit(u).path.lower().endswith(_DOC_EXT)]
    pdfs = [u for u in docs if urlsplit(u).path.lower().endswith(".pdf")]
    primary = (pdfs or docs or hrefs or [page_url])[0]

    notes = [NO_APPROVAL_NOTE]
    if type_note:
        notes.append(type_note)

    # Subject.
    first = name_parts[0] if name_parts else ""
    service_parts = name_parts[1:]
    kind = classify_subject(first, has_service_line=bool(service_parts))
    provider_name: str | None = None
    service_name: str | None = None
    tokens: set[str] = set()
    withheld_markers: list[str] = []  # constant phrases only, never source text

    if kind == "entity":
        provider_name = first
        service_name = "; ".join(service_parts) if service_parts else None
        if len(service_parts) > 1:
            notes.append("several service lines printed; joined with '; ' in printed order")
    elif kind == "service_only":
        service_name = first
        notes.append(
            "one name printed with no legal-entity marker; treated as a service name and "
            "provider not stated"
        )
    else:  # role or individual: never store the name
        if kind == "individual":
            tokens = name_tokens(first)
            detail = (
                "printed name is not positively an organisation"
                if _LEGAL.search(first) or _BUSINESS.search(first)
                else "no legal-entity or business word in the printed name"
            )
            withheld_markers.append(f"{INDIVIDUAL_NOTE} ({detail})")
        else:
            withheld_markers.append(f"{INDIVIDUAL_NOTE} (register prints a generic role, no name)")
        if service_parts:
            candidate = "; ".join(service_parts)
            if tokens and contains_token(candidate, tokens):
                withheld_markers.append(
                    "service name withheld: it repeats a word from the individual's name"
                )
            else:
                service_name = candidate
        # File names of linked documents usually embed the person's name.
        if hrefs:
            withheld_markers.append(
                "linked document URLs withheld because file names can embed the name"
            )
        primary = page_url
        hrefs = []

    # Dates.
    date_issued, date_warning = parse_date(date_raw)
    if date_warning:
        notes.append(date_warning)
    if date_issued and period and date_issued[:4] != period:
        notes.append(f"date year {date_issued[:4]} differs from table heading {period}")

    # Breaches column -> legal references. 'N/A' means none printed.
    legal_references = [p for p in breach_parts if p.lower() not in {"n/a", "na", "-"}]
    if legal_references and not any(re.match(r"(NL|NR)\b", p) for p in legal_references):
        notes.append(f"breaches column printed: {'; '.join(legal_references)}")
        legal_references = []

    # Codex round 5: only an amount tied explicitly to the fine is recorded.
    # PR #9: the fine form is read from the headline alone; the guards and the amount count run
    # over all of the details cell (every paragraph, linked or not, and every label).
    penalty, penalty_note = fine_amount_and_note(
        headline,
        clean(details.get_text(" ")),
        subject_is_person=kind not in ("entity", "service_only"),
    )
    if penalty_note:
        notes.append(penalty_note)
        withheld_markers.append(penalty_note)  # a constant phrase, safe on withheld rows

    se_raw = pr_raw = None
    row = {
        "record_id": None,  # set by parse_register from non-name facts (assign_record_ids)
        "jurisdiction": JURISDICTION,
        "source_register": INDEX_URL,
        "source_document": primary,
        "service_approval_number": normalise_se(se_raw),
        "service_approval_number_raw": se_raw,
        "provider_approval_number": normalise_pr(pr_raw),
        "provider_approval_number_raw": pr_raw,
        "service_name": service_name,
        "provider_name": provider_name,
        "address": None,
        "suburb": None,
        "state": None,
        "postcode": None,
        "action_type": action_type,
        "action_type_raw": action_type_raw,
        "reason": reason,
        "legal_references": legal_references,
        "date_issued": date_issued,
        "date_issued_raw": date_raw or None,
        "period_label": period,
        "notes": "; ".join(notes),
        "linked_documents": " ".join(u for u in hrefs if u != primary) or None,
        "penalty_amount_aud": penalty,
        # In-memory only (not written): the printed content, names included, to spot a row the
        # register prints twice. Never published and never used as the record_id.
        # Codex round 5: link targets are printed content too, so two rows with the same text
        # but different documents are told apart and keep stable ids.
        "_fingerprint": printed_fingerprint(
            *(clean(c.get_text(" ")) for c in cells),
            *(a["href"] for c in cells for a in c.find_all("a", href=True)),
        ),
    }
    if kind in ("individual", "role"):
        # Rule 2: free text can repeat the name in forms no redaction catches, so it is withheld
        # whole. Structured fields stay.
        withhold_free_text(row, (NO_APPROVAL_NOTE, *withheld_markers))
        note_withheld_subject(first)  # in-memory name set, never written
        if withheld_by_shared_rule_only(first, has_service_line=bool(service_parts)):
            # PR #11: the names, for their keyed hashes in the private join sidecar only.
            keep_withheld_names(row, provider=first, service="; ".join(service_parts) or None)
    return row


def parse_register(
    html: str,
    *,
    page_url: str = INDEX_URL,
    captured_at: str = "",
    source_snapshot: str = "",
) -> list[dict]:
    """Parse every register table in the page into schema rows."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    seen: dict[str, int] = {}  # printed-content fingerprint -> count
    for table in soup.find_all("table"):
        if not _is_register_table(table):
            continue
        period = _period_label(table)
        for tr in table.find_all("tr")[1:]:
            row = parse_row(tr, period=period, page_url=page_url)
            if row is None:
                continue
            row["captured_at"] = captured_at
            row["source_snapshot"] = source_snapshot
            seen[row["_fingerprint"]] = seen.get(row["_fingerprint"], 0) + 1
            if seen[row["_fingerprint"]] > 1:
                row["notes"] += "; duplicate row: another row prints the same text"
            rows.append(row)
    assign_record_ids(rows, source_id=page_url)
    # After the ids: the id never depends on what the prose or URL rule withholds.
    withhold_prose_naming_people(rows)  # shared prose rule, every row
    return rows


# ---------------------------------------------------------------------------
# Snapshot and run
# ---------------------------------------------------------------------------


def _snapshot_meta(path: Path) -> dict:
    meta_path = Path(f"{path}.meta.json")
    return json.loads(meta_path.read_text()) if meta_path.exists() else {}


def main(argv: list[str] | None = None) -> int:
    if refuse_if_reparse_incomplete():  # an interrupted reparse_offline run (Codex round 5)
        return 3
    ensure_person_names()  # in-memory names for the prose rule (Codex round 3)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-fetch", action="store_true", help="parse the newest local snapshot")
    ap.add_argument("--force", action="store_true", help="archive even if the page is unchanged")
    args = ap.parse_args(argv)

    if args.skip_fetch:
        snaps = [p for p in list_snapshots(SOURCE) if p.suffix == ".html"]
        if not snaps:
            log.error("no local snapshot under data/raw/%s", SOURCE)
            return 1
        path = snaps[-1]
        captured_at = _snapshot_meta(path).get("fetched_at", "")
    else:
        fetched = fetch(INDEX_URL)
        path = None
        if not args.force:
            for meta in sorted((RAW_DIR / SOURCE).glob("*.html.meta.json")):
                if json.loads(meta.read_text()).get("sha256") == fetched.sha256:
                    path = Path(str(meta)[: -len(".meta.json")])
            if path:
                log.info("page unchanged since %s; reusing that snapshot", path.name)
        if path is None:
            path = write_snapshot(SOURCE, fetched, "html")
        captured_at = fetched.fetched_at

    rel = str(path.relative_to(PROJECT_ROOT))
    rows = parse_register(
        path.read_text(encoding="utf-8", errors="replace"),
        page_url=INDEX_URL,
        captured_at=captured_at,
        source_snapshot=rel,
    )
    if not rows:
        log.error("no rows parsed; the page layout may have changed")
        return 1

    out_rows = [
        {**r, "legal_references": json.dumps(r["legal_references"], ensure_ascii=False)}
        for r in rows
    ]
    write_processed(
        OUTPUT_NAME,
        out_rows,
        FIELDNAMES,
        raw_inputs=[path],
        schema=SCHEMA_PATH,
        notes=(
            "Queensland register prints no SE-/PR- numbers. Individual names are withheld "
            "(provider_name null). legal_references is a JSON array. linked_documents is an "
            "extra column. Linked documents were not downloaded."
        ),
    )
    withheld = sum(1 for r in rows if INDIVIDUAL_NOTE in (r["notes"] or ""))
    log.info("%d rows parsed, %d with an individual subject (name withheld)", len(rows), withheld)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

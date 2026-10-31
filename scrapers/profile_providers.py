"""Profile ACECQA approved providers: entity form, service counts, states operated in.

Reads the processed ACECQA registers (data/processed/acecqa-providers-latest.csv and
acecqa-services-latest.csv, rebuilt from the raw snapshot by snapshot_acecqa_registers.py) and writes:

- data/processed/provider-profile.csv           one row per provider
- data/processed/provider-profile-summary.json  aggregate counts and top providers by service count

Privacy (CLAUDE.md rule 2, applied at ingest, fail closed): a provider's Legal Name and Trading
Name are published only when the legal name is positively an organisation (see name_is_withheld).
Every other provider keeps a row in the CSV, but both names are null and name_withheld is true:
likely individuals, individual trustees, deceased estates and executors, trusts named after a
person, and any name without positive organisation evidence (a legal form such as Pty Ltd, Ltd,
Inc, Co-operative or Corporation, a government form, or a non-individual ABR entity type from
provider-abn.csv). Withheld names never appear in the summary,
in log lines or in any printed list. Street addresses are not carried over.

ACECQA content is not openly licensed: outputs are for internal use only.

Run: python3 scrapers/profile_providers.py
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

try:
    from scrapers.common import (
        PROCESSED_DIR,
        PROJECT_ROOT,
        atomic_write_text,
        ensure_person_names,
        log,
        utc_now,
        withhold_person_named_names,
        write_processed,
    )
except ImportError:  # run as a plain script: python3 scrapers/profile_providers.py
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scrapers.common import (
        PROCESSED_DIR,
        PROJECT_ROOT,
        atomic_write_text,
        ensure_person_names,
        log,
        utc_now,
        withhold_person_named_names,
        write_processed,
    )

PROVIDERS_CSV = PROCESSED_DIR / "acecqa-providers-latest.csv"
SERVICES_CSV = PROCESSED_DIR / "acecqa-services-latest.csv"
SUMMARY_JSON = PROCESSED_DIR / "provider-profile-summary.json"
# ABR entity types from an earlier ABN match, used only as organisation evidence.
PROVIDER_ABN_CSV = PROCESSED_DIR / "provider-abn.csv"
_ABR_ACCEPTED = {"accepted_unique", "accepted_unique_in_state"}

ENTITY_FORMS = (
    "company",
    "incorporated_association",
    "cooperative",
    "government",
    "trust_or_trustee",
    "church_or_religious",
    "likely_individual",
    "unknown",
)

# ---------------------------------------------------------------------------
# Name normalisation (also the basis for the planned ABR name match)
# ---------------------------------------------------------------------------

_ACN_TAG = re.compile(r"\(?\bA\.?C\.?N\.?\s*\d[\d\s]{7,}\d\)?")
_PTY_LTD_TAIL = re.compile(r"\b(?:PTY|PROPRIETARY)(?: LTD| LIMITED)$|\bP L$")
_LTD_TAIL = re.compile(r"\b(?:LTD|LIMITED)$")
_INC_TAIL = re.compile(r"\b(?:INC|INCORPORATED)$")


def normalise_name(name: str | None) -> str | None:
    """Upper case, strip punctuation, collapse whitespace, canonicalise the corporate tail.

    Tails become one of PTY LTD, LTD or INC. Returns None for blank input.
    """
    if not name:
        return None
    s = _ACN_TAG.sub(" ", name.upper())
    s = s.replace("&", " AND ")
    s = re.sub(r"[‘’'`]", "", s)  # O'BRIEN -> OBRIEN, not O BRIEN
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    s = re.sub(r"\bPTY LTD$|\bPTY LIMITED$|\bPROPRIETARY LIMITED$|\bP L$", "PTY LTD", s)
    s = _LTD_TAIL.sub("LTD", s) if not s.endswith("PTY LTD") else s
    s = _INC_TAIL.sub("INC", s)
    return s


def strip_corporate_suffix(name: str | None) -> str | None:
    """Normalised name without its trailing PTY LTD, LTD or INC. Used for looser matching."""
    norm = normalise_name(name)
    if norm is None:
        return None
    for tail in (" PTY LTD", " LTD", " INC"):
        if norm.endswith(tail):
            return norm[: -len(tail)].strip() or None
    return norm


# ---------------------------------------------------------------------------
# Entity form classifier
# ---------------------------------------------------------------------------

_I = re.IGNORECASE
_TRUSTEE = re.compile(r"\b(?:as\s+trustee|trustee\s+for|trustee\s+of|a\.?t\.?f\.?)\b", _I)
_TRUST_WORD = re.compile(r"\b(?:trust|trustee|trustees)\b", _I)
_GOV_STRONG = re.compile(
    r"\b(?:minister|department|dept|state\s+of|crown|commonwealth\s+of|city\s+of|shire\s+of|"
    r"shire\s+council|city\s+council|regional\s+council|municipal\w*)\b",
    _I,
)
# Applies only when there is no company, Inc or Association marker (a school's parents and
# citizens association is an association, not the government).
_GOV_WEAK = re.compile(
    r"\b(?:council|shire|government\s+school\w*|public\s+school|state\s+school|"
    r"local\s+health\s+district|tafe|technical\s+and\s+further\s+education)\b",
    _I,
)
_CHURCH = re.compile(
    r"\b(?:parish|diocese|diocesan|uniting|anglican|catholic|baptist|lutheran|"
    r"salvation\s+army|presbyterian)\b",
    _I,
)
_COOP = re.compile(r"\b(?:co-?operative|co-?op|coop)\b", _I)
_COMPANY = re.compile(
    r"(?:\bpty\.?\s*(?:ltd|limited)?\b|\bproprietary\s+limited\b|\bltd\b\.?|\blimited\b|\bp/l\b)",
    _I,
)
_INC = re.compile(r"\b(?:inc|incorporated)\b\.?", _I)
_ASSOC = re.compile(r"\b(?:association|assoc|assn)\b", _I)

# Words that mark a business, school, charity or place rather than a person.
_BUSINESS_WORDS = frozenset(
    """
    child children childcare care kids kid kindergarten kinder preschool pre school schools learning
    education educational centre center centres services service group holdings australia
    australian foundation club society community college academy montessori nursery playgroup
    daycare ymca ymcas council shire department ministry health hospital university
    institute association trust network enterprises investments management
    partners partnership operations solutions school college grammar university tafe
    corporation corp aboriginal islander committee board mission oshc church kindy
    """.split()
)
_PERSON_PARTICLES = frozenset(
    {"de", "del", "della", "van", "von", "der", "den", "bin", "al", "el", "le", "la", "di"}
)
# Any letter, including accented ones (a name such as 'Zo\u00eb' must not fall through to unknown).
_PERSON_TOKEN = re.compile(r"^[^\W\d_](?:[^\W\d_]|[.'\u2019\-])*$")
_TRADING_AS = re.compile(r"\s+(?:t/as?|trading\s+as)\s+", _I)
_PARTNER_SPLIT = re.compile(r"\s*(?:&|\+|;|/|\band\b)\s*", _I)

# A deceased estate or its executors always names a person.
_ESTATE = re.compile(
    r"\b(?:estate\s+of|executors?|executrix|executrices|deceased|the\s+late)\b", _I
)
# An honorific or personal title in front of a word names a person (Codex round 3, finding 2:
# academic, religious and honorary titles too). 'Lady' and 'Lord' are left out because they
# start well-known organisation names; 'Sisters of ...' does not match 'sister'.
_TITLE = re.compile(
    r"(?:^|[\s&,;/(+-])(?:mr|mrs|ms|miss|mx|dr|prof|professor|assoc\.?\s+prof|a/prof|rev|revd|"
    r"reverend|sr|fr|hon|honourable|dame|sir|pastor|rabbi|imam)\.?\s+[^\W\d_]",
    _I,
)
# Splits '<trustee> as trustee(s) for <trust>' and '<trustee> ATF <trust>'. Broader than _TRUSTEE,
# which is kept as is so that entity_form labels do not move for organisation trustees.
_TRUSTEE_SPLIT = re.compile(
    r"\b(?:as\s+(?:the\s+)?trustees?(?:\s+(?:for|of))?|(?:the\s+)?trustees?\s+(?:for|of)|"
    r"a\.?t\.?f\.?)(?=\W|$)",
    _I,
)


def _person_segment(tokens: list[str]) -> bool:
    """One to five name-like words: capitalised (particles excepted), no business word."""
    if not 1 <= len(tokens) <= 5:
        return False
    if not all(_PERSON_TOKEN.match(t) for t in tokens):
        return False
    keys = {t.lower().strip(".") for t in tokens}
    keys |= {part for k in keys for part in k.split("-")}  # 'Pre-School' is a business word
    if keys & _BUSINESS_WORDS:
        return False
    if all(t.islower() for t in tokens):  # carelessly typed all-lowercase names
        return True
    return all(t.lower() in _PERSON_PARTICLES or t[0].isupper() for t in tokens)


def _looks_like_person(name: str) -> bool:
    """A person's name, or a partnership of people, with no corporate marker or business word.

    Covers 'Given Surname', 'Given M Surname', 'A Surname & B Surname' and the same followed by
    'T/A <business name>' (the business name is dropped before the test). The spec asks for two
    or three words; up to five are allowed per person here because under-withholding a person's
    name is the costlier error. Over-withholding only nulls a name in the CSV.
    """
    left = _TRADING_AS.split(name.strip(), maxsplit=1)[0].replace(",", " ").strip()
    parts = [p.split() for p in _PARTNER_SPLIT.split(left)]
    if any(not p for p in parts):
        return False
    if len(parts) == 1:
        return len(parts[0]) >= 2 and _person_segment(parts[0])
    return all(_person_segment(p) for p in parts) and any(len(p) >= 2 for p in parts)


def classify_entity_form(legal_name: str | None) -> str:
    """Conservative classification of a provider legal name. Order of the checks matters.

    Person signals come first: a deceased estate or executor, or a trustee who is a person
    ('<person> ATF <trust>', '<person> as trustee for <trust>'), is likely_individual whatever
    the rest of the name says.
    """
    if not legal_name or not legal_name.strip():
        return "unknown"
    name = legal_name.strip()
    if _ESTATE.search(name):
        return "likely_individual"
    split = _TRUSTEE_SPLIT.search(name)
    if split:
        trustee = _strip_leading_the(name[: split.start()])
        if trustee and classify_entity_form(trustee) == "likely_individual":
            return "likely_individual"
    has_company = bool(_COMPANY.search(name))
    has_inc = bool(_INC.search(name))
    has_assoc = bool(_ASSOC.search(name))

    if _TRUSTEE.search(name):
        return "trust_or_trustee"
    if _CHURCH.search(name):
        return "church_or_religious"
    if _GOV_STRONG.search(name):
        return "government"
    if _GOV_WEAK.search(name) and not (has_company or has_inc or has_assoc):
        return "government"
    if _COOP.search(name):
        return "cooperative"
    if has_inc:
        return "incorporated_association"
    if has_company:
        return "company"
    if has_assoc:
        return "incorporated_association"
    if _TRUST_WORD.search(name):
        return "trust_or_trustee"
    if _looks_like_person(name) or _TITLE.search(name):
        return "likely_individual"
    return "unknown"


# ---------------------------------------------------------------------------
# Fail-closed name withholding
# ---------------------------------------------------------------------------

# Positive organisation evidence in a name: a legal-form suffix or word.
_CORPORATION = re.compile(r"\b(?:corporation|corp)\b\.?", _I)
# ABR entity types that are a non-individual organisation. Trusts and partnerships are left out:
# their type says nothing about whether the trustee or partners are people.
ABR_ORGANISATION_TYPES = frozenset(
    # Codes seen in provider-abn.csv, plus the Commonwealth government entity code.
    {"PRV", "PUB", "OIE", "UIE", "COP", "CGE", "SGE", "TGE", "LGE", "LGA"}
)
# Words that are places or institutions in a trust's name ('Archdiocese of Exampleton').
_PLACE_WORDS = frozenset(
    "archdiocese diocese parish corporation trustees roman catholic sisters order".split()
)
# Words dropped from a trust's name before asking whether what is left is a person's name.
_TRUST_FILLER = frozenset(
    """
    the a for of as trust trusts trustee trustees family unit discretionary fixed hybrid
    investment investments superannuation super fund settlement no number
    """.split()
)


def has_organisation_evidence(name: str | None) -> bool:
    """True when a name itself carries a legal form (Pty Ltd, Ltd, Limited, Inc, Incorporated,
    Co-operative, Corporation and the like) or reads as a government body. An institutional or
    business word alone (school, community, childcare) is not evidence."""
    if not name or not name.strip():
        return False
    text = name.strip()
    if _COMPANY.search(text) or _INC.search(text) or _COOP.search(text):
        return True
    if _CORPORATION.search(text):
        return True
    return classify_entity_form(text) == "government"


def _strip_leading_the(text: str) -> str:
    return re.sub(r"^(?:the\s+)", "", text.strip(" ,;:-()"), flags=re.I).strip(" ,;:-()")


def _word_key(token: str) -> str:
    """Lower case, possessive and punctuation removed: "Children's" -> 'children'."""
    key = token.lower().strip("()[]\"'.,;:’")
    return re.sub(r"['’]s$", "", key)


_FAMILY_TRUST = re.compile(r"\bfamily\s+trust\b", _I)


def _trust_names_a_person(trust: str) -> bool:
    """True when a trust's name may contain a personal name.

    Filler words (the, trust, unit, family ...), business words and church or government words
    are dropped first; if two or more name-like words are left, they may be a person's name and
    the trust is treated as naming one, even when the trust also carries a business word
    ('the Jane Example Childcare Trust'). There is no exemption for a trust named like its
    trustee company: that exemption let a person's name through.
    """
    trust = _TRADING_AS.split(trust, maxsplit=1)[0]
    if _TITLE.search(trust) or _ESTATE.search(trust) or _FAMILY_TRUST.search(trust):
        return True
    words = []
    for w in re.split(r"[\s,()&+/;-]+", trust):
        key = _word_key(w)
        if not key or re.fullmatch(r"[\d.#]+", w):
            continue
        if key in _TRUST_FILLER or key in _BUSINESS_WORDS:
            continue
        if _CHURCH.fullmatch(key) or _GOV_STRONG.fullmatch(key) or key in _PLACE_WORDS:
            continue
        words.append(w)
    return len(words) >= 2 and _person_segment(words[:5])


def name_is_withheld(
    legal_name: str | None, form: str | None = None, abr_entity_type: str | None = None
) -> bool:
    """Fail closed: True unless there is positive evidence that the name is an organisation.

    Evidence is a legal form or government form in the name (has_organisation_evidence), or an
    ABR entity type for this provider that is a non-individual organisation
    (ABR_ORGANISATION_TYPES). Even with evidence a name is withheld when it carries a person
    signal: a likely individual, a deceased estate or executor, a trustee without evidence, or a
    trust named after a person. A blank name has nothing to withhold and returns False.
    """
    if not legal_name or not legal_name.strip():
        return False
    name = legal_name.strip()
    form = form or classify_entity_form(name)
    # Person signals first: they withhold the name whatever company or trust evidence follows.
    if form == "likely_individual" or _ESTATE.search(name) or _TITLE.search(name):
        return True
    if _FAMILY_TRUST.search(name):
        return True
    abr_org = (abr_entity_type or "").strip().upper() in ABR_ORGANISATION_TYPES
    split = _TRUSTEE_SPLIT.search(name)
    if split:
        trustee = _strip_leading_the(name[: split.start()])
        if trustee and classify_entity_form(trustee) == "likely_individual":
            return True
        if _trust_names_a_person(name[split.end() :]):
            return True
        return not (abr_org or (trustee and has_organisation_evidence(trustee)))
    if form == "trust_or_trustee" or _TRUST_WORD.search(name):
        if _trust_names_a_person(name):
            return True
        return not (abr_org or has_organisation_evidence(name))
    return not (abr_org or has_organisation_evidence(name))


def name_has_person_signal(legal_name: str | None, form: str | None = None) -> bool:
    """True when name_is_withheld would withhold the name because of a person signal (a likely
    individual, a deceased estate or executor, a title, a family trust, an individual trustee or
    a trust named after a person), not merely for lack of organisation evidence."""
    if not legal_name or not legal_name.strip():
        return False
    name = legal_name.strip()
    form = form or classify_entity_form(name)
    if form == "likely_individual" or _ESTATE.search(name) or _TITLE.search(name):
        return True
    if _FAMILY_TRUST.search(name):
        return True
    split = _TRUSTEE_SPLIT.search(name)
    if split:
        trustee = _strip_leading_the(name[: split.start()])
        if trustee and classify_entity_form(trustee) == "likely_individual":
            return True
        return _trust_names_a_person(name[split.end() :])
    if form == "trust_or_trustee" or _TRUST_WORD.search(name):
        return _trust_names_a_person(name)
    return False


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Prose rule (Codex round 2, finding 1): one fail-closed person detector for free text.
# ---------------------------------------------------------------------------

# Capitalised words common in regulator prose, plus calendar, place-type and function words.
# They break a run of capitalised words. Any other run of two or more capitalised words, or an
# honorific in front of a word, is treated as a possible personal name: the rule over-withholds
# rather than miss a name. A surname printed alone is not caught (see the PR's remaining risks).
_PROSE_STOPWORDS = (
    frozenset(
        """
        a an the and or of for to by at with from as on in into is was were be been this that
        these those it its their there which who whom whose under over after before during per
        via not no nor all any each other such same than then if but also has have had our we
        you he she they his her him please note see refer
        national law laws regulation regulations reg regs section sections s act acts rule rules
        part division schedule clause item items
        notice notices compliance direction directions emergency action actions enforcement
        enforceable undertaking undertakings prosecution court courts magistrates magistrate
        local district supreme federal tribunal state administrative department regulatory
        authority authorities approved provider providers approval approvals service services
        nominated supervisor supervisors responsible person persons educator educators family day
        care child children childrens early childhood quality framework standard standards nqs
        nqf board education secretary registrar delegate minister ministers officer officers
        authorised authorized commonwealth government public benefit disciplinary proceedings
        proceeding conditions condition imposed suspension suspended cancellation cancelled
        cancel immediate meeting worker workers assistance tax system practice corporations
        associations incorporations medical subsidy safe safety protection police inappropriate
        risk assessment record records register registered what constitutes outside hours based
        involuntary voluntary
        primary high secondary centre center offence offences fine fined penalty
        new south north east west southern northern eastern western central upper lower greater
        inner outer wa nsw vic qld sa tas nt australia australian victoria queensland tasmania
        territory capital wales
        street st road rd avenue ave drive dr close cl way terrace tce parade pde boulevard bvd
        blvd crescent cres cr lane ln highway hwy place pl circuit cct court ct grove gr square
        sq esplanade esp walk loop rise ridge vista mall arcade corner cnr shop unit level suite
        po box lot entrance gardens park reserve
        january february march april may june july august september october november december
        jan feb mar apr jun jul aug sep sept oct nov dec monday tuesday wednesday thursday
        friday saturday sunday
        inc ltd pty limited incorporated
        """.split()
    )
    | _BUSINESS_WORDS
)
_PROSE_EDGE = ".,;:()[]{}<>\"'\u2018\u2019\u201c\u201d!?*"


def _prose_key(core: str) -> str:
    key = core.lower().replace("\u2019", "'")
    key = key[:-2] if key.endswith("'s") else key
    # A plural of a stopword is a stopword ('Suspensions', 'Cancellations').
    if key not in _PROSE_STOPWORDS and key.endswith("s") and key[:-1] in _PROSE_STOPWORDS:
        return key[:-1]
    return key


_MONTH_WORDS = frozenset(
    "january february march april may june july august september october november december".split()
)


def _prose_word(word: str) -> tuple[str, str, bool]:
    """(core, lower-case key, capitalised name-like word with no digits)."""
    core = word.strip(_PROSE_EDGE)
    capitalised = (
        bool(core)
        and core[0].isalpha()
        and core[0].isupper()
        and not any(c.isdigit() for c in core)
    )
    return core, _prose_key(core), capitalised


def _prose_runs(text: str) -> list[list[str]]:
    """Runs of capitalised, non-stopword words, broken by punctuation, digits or stopwords.
    Lower-case name particles ('de', 'van') and initials ('Q.') continue a run."""
    runs: list[list[str]] = []
    cur: list[str] = []
    words = text.split()
    for i, word in enumerate(words):
        core, key, capitalised = _prose_word(word)
        is_name = capitalised and key not in _PROSE_STOPWORDS
        if (
            not is_name
            and capitalised
            and key in _MONTH_WORDS
            and word[-1] not in ",;:.)!?"
            and i + 1 < len(words)
        ):
            # Codex round 3: a month before a capitalised word that is not a stopword, a month or
            # a number reads as a given name ('April Example'); 'April 2025' does not.
            _, next_key, next_capitalised = _prose_word(words[i + 1])
            is_name = (
                next_capitalised
                and next_key not in _PROSE_STOPWORDS
                and next_key not in _MONTH_WORDS
            )
        if is_name:
            cur.append(core)
            if len(core) == 1 and word.endswith("."):
                continue  # an initial
        elif cur and key in _PERSON_PARTICLES:
            continue
        if not is_name or word[-1] in ",;:)!?" or (word.endswith(".") and len(core) > 1):
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
    if len(cur) >= 2:
        runs.append(cur)
    return runs


# Codex round 3, finding 3: the data-driven layer. Words that are never part of a person's name
# when a withheld subject string is split into names.
_NAME_TOKEN = re.compile(r"[^\W\d_]+(?:['\u2019-][^\W\d_]+)*")
_NAME_SPLIT = re.compile(
    r"\s*(?:&|\+|;|/|,|\band\b|\ba\.?t\.?f\.?(?=\W|$)|\bas\s+(?:the\s+)?trustees?\s+(?:for|of)\b|"
    r"\btrustees?\s+(?:for|of)\b|\bestate\s+of\b|\bexecut(?:or|ors|rix)\s+of\b|\bthe\s+late\b|"
    r"\bt/as?\b|\btrading\s+as\b)\s*",
    _I,
)
_NAME_NOISE = (
    frozenset(
        """
        mr mrs ms miss mx dr prof professor assoc a rev revd reverend sr fr hon honourable dame
        sir pastor rabbi imam the late deceased estate executor executors executrix abn acn pr se cs
        """.split()
    )
    | _TRUST_FILLER
)


class PersonNames:
    """Personal names withheld or classed as individuals in this run. In memory only: it has no
    writer and refuses to be pickled, so it can never reach a committed file.

    Full names (two to five words) match case-insensitively on word boundaries. A surname is
    used alone only when it has four or more letters, comes from a withheld person's name, and is
    printed capitalised (so that 'Example' matches but 'for example' does not)."""

    def __init__(self) -> None:
        self._full: set[tuple[str, ...]] = set()
        self._surnames: set[str] = set()

    def __reduce__(self):
        raise TypeError("PersonNames is in memory only and cannot be serialised")

    def __len__(self) -> int:
        return len(self._full) + len(self._surnames)

    def update(self, other: PersonNames) -> None:
        self._full |= other._full
        self._surnames |= other._surnames

    def add_subject(self, raw: str | None) -> None:
        """Add the people named in a withheld subject string ('Ms A B and C D', 'A B ATF The B
        Family Trust', 'Estate of A B'). Segments with a business word are skipped."""
        if not raw:
            return
        family = bool(_FAMILY_TRUST.search(raw))
        for segment in _NAME_SPLIT.split(raw):
            tokens = _NAME_TOKEN.findall(segment or "")
            words = [t for t in tokens if t.lower().strip(".") not in _NAME_NOISE]
            if not words or len(words) > 5:
                continue
            keys = [w.lower() for w in words]
            # Codex round 4: a month may be a given name ('April Example') when a surname follows.
            month_given = len(keys) >= 2 and keys[0] in _MONTH_WORDS and keys[1] not in _MONTH_WORDS
            checked = keys[1:] if month_given else keys
            if any(k in _BUSINESS_WORDS or k in _PROSE_STOPWORDS for k in checked):
                continue
            if len(keys) >= 2:
                self._full.add(tuple(keys))
                self._full.add((keys[0], keys[-1]))
            # PR #12 round 1: a hyphenated name matches its spaced form and the reverse
            # ('Ann-Marie Example-Sample' and 'Ann Marie Example Sample').
            split = [part for k in keys for part in k.split("-") if part]
            if len(split) >= 2 and split != keys:
                self._full.add(tuple(split))
            surname_parts = [part for part in keys[-1].split("-") if part]
            if len(surname_parts) >= 2:
                self._full.add(tuple(surname_parts))
            if len(keys[-1]) >= 4 and (len(keys) >= 2 or family):
                self._surnames.add(keys[-1])

    def found_in(self, text: str | None, ordinary: frozenset[str] | set[str] = frozenset()) -> bool:
        """True when `text` holds a full name, or a capitalised surname used alone. A surname
        in `ordinary` (lower case) is not used alone; full names always count."""
        if not text or not self:
            return False
        tokens = _NAME_TOKEN.findall(text)
        # PR #12 round 1: hyphen and space variants alike. The words of the text are checked as
        # printed and with every hyphenated word split into its parts.
        parts = [p for t in tokens for p in t.split("-") if p]
        for words in (tokens, parts):
            keys = [t.lower() for t in words]
            for i in range(len(keys)):
                for n in range(2, 6):
                    if i + n <= len(keys) and tuple(keys[i : i + n]) in self._full:
                        return True
            if any(
                t[0].isupper() and k in self._surnames and k not in ordinary
                for t, k in zip(words, keys, strict=True)
            ):
                return True
        return False


def acecqa_person_names(path: Path | None = None, abr_types: dict | None = None) -> PersonNames:
    """Names of ACECQA approved providers that the shared rule withholds, from the processed copy
    of the raw ACECQA register. In memory only."""
    names = PersonNames()
    path = path or PROVIDERS_CSV
    if not path.exists():
        return names
    abr = _abr_entity_types() if abr_types is None else abr_types
    for p in _read(path):
        legal = p.get("Legal Name")
        if legal and name_is_withheld(
            legal, classify_entity_form(legal), abr.get(p.get("provider_approval_number") or "")
        ):
            names.add_subject(legal)
    return names


def prose_may_name_person(
    text: str | None,
    known: tuple[str | None, ...] = (),
    person_names: PersonNames | None = None,
) -> bool:
    """True when free text may name a person. Fail closed.

    Text already published for the row in a structured column (its service name, an
    organisation's provider name, its suburb) is removed first, so that it is not mistaken for
    a person. Then an honorific in front of a word, or a run of two or more capitalised words
    that are not common regulator, place or calendar words, counts as a possible name."""
    if not text:
        return False
    for k in known:
        if k and len(k.strip()) > 3:
            text = re.sub(re.escape(k.strip()), " ", text, flags=re.IGNORECASE)
    # In prose a title counts only before a capitalised word ('Rev Example', not 'rev up').
    if any(m.group(0)[-1].isupper() for m in _TITLE.finditer(text)):
        return True
    if person_names is not None and person_names.found_in(text):
        return True
    return bool(_prose_runs(text))


class AcecqaNameContext:
    """From the ACECQA provider register, in memory only (it refuses to be pickled):

    - withheld: provider approval number -> raw legal name, for every provider whose name the
      shared rule withholds. A service or trading name that repeats its own withheld provider's
      name (or that name's surname) would publish the withheld name.
    - ordinary: lower-case words of every published (not withheld) provider legal name. A
      surname from the run-wide set that is also such a word ('Cottage', 'Valley') is not used
      alone against a name from another provider; full names always count.
    - flagged: casefolded ACECQA service names that repeat their own withheld provider's name.
      The same name printed by a regulator, without the provider, is withheld too, so that every
      output withholds it whatever order the outputs are written in."""

    def __init__(self) -> None:
        self.withheld: dict[str, str] = {}
        self.ordinary: frozenset[str] = frozenset()
        self.flagged: frozenset[str] = frozenset()

    def __reduce__(self):
        raise TypeError("AcecqaNameContext is in memory only and cannot be serialised")

    def own_names(self, *approval_numbers: str | None) -> PersonNames:
        names = PersonNames()
        for pr in approval_numbers:
            if pr and pr in self.withheld:
                names.add_subject(self.withheld[pr])
        return names


def acecqa_name_context(
    path: Path | None = None, abr_types: dict | None = None, services_path: Path | None = None
):
    """Build the AcecqaNameContext from the processed copies of the ACECQA registers."""
    ctx = AcecqaNameContext()
    path = path or PROVIDERS_CSV
    services_path = services_path or SERVICES_CSV
    if not path.exists():
        return ctx
    abr = _abr_entity_types() if abr_types is None else abr_types
    ordinary: set[str] = set()
    for p in _read(path):
        legal = (p.get("Legal Name") or "").strip()
        pr = p.get("provider_approval_number") or ""
        if not legal:
            continue
        if name_is_withheld(legal, classify_entity_form(legal), abr.get(pr)):
            if pr:
                ctx.withheld[pr] = legal
        else:
            ordinary |= {t.lower() for t in _NAME_TOKEN.findall(legal)}
    ctx.ordinary = frozenset(ordinary)
    flagged: set[str] = set()
    if services_path.exists():
        for svc in _read(services_path):
            name = (svc.get("ServiceName") or "").strip()
            pr = svc.get("provider_approval_number") or ""
            if name and pr in ctx.withheld and ctx.own_names(pr).found_in(name):
                flagged.add(" ".join(name.casefold().split()))
    ctx.flagged = frozenset(flagged)
    return ctx


def name_may_name_person(
    name: str | None,
    person_names: PersonNames | None = None,
    own_names: PersonNames | None = None,
    ordinary: frozenset[str] | set[str] = frozenset(),
) -> bool:
    """The person check for a trading name or a service name. Fail closed for persons.

    True when the name:
    - carries a person signal under the provider-name rule (name_has_person_signal: a likely
      individual, a title, an estate, a family trust, an individual trustee, a trust named after
      a person);
    - contains a full name (two or more words) from the run-wide person-name set, or a surname
      from that set used alone, unless the surname is an ordinary word of a published
      organisation name;
    - contains the name, or the surname, of its own withheld provider (own_names).
    Unlike name_is_withheld, organisation evidence is not required: most trading and service
    names carry no legal form, and an ordinary name ('Little Acorns Early Learning') is kept."""
    if not name or not name.strip():
        return False
    if name_has_person_signal(name):
        return True
    if own_names is not None and own_names.found_in(name):
        return True
    return person_names is not None and person_names.found_in(name, ordinary)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _raw_inputs_of(processed: Path) -> list[Path]:
    prov = processed.with_suffix(".provenance.json")
    if not prov.exists():
        return [processed]
    listed = json.loads(prov.read_text()).get("raw_inputs", [])
    paths = [PROJECT_ROOT / p for p in listed]
    return [processed, *paths]


def _to_int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _band(n: int) -> str:
    if n == 0:
        return "0"
    if n == 1:
        return "1"
    if n <= 4:
        return "2-4"
    if n <= 9:
        return "5-9"
    if n <= 24:
        return "10-24"
    return "25+"


def _abr_entity_types() -> dict[str, str]:
    """PR -> ABR entity type code for accepted ABN matches in provider-abn.csv, if present."""
    if not PROVIDER_ABN_CSV.exists():
        return {}
    return {
        r["provider_approval_number"]: r["entity_type_code"]
        for r in _read(PROVIDER_ABN_CSV)
        if r.get("abn") and r.get("match_kind") in _ABR_ACCEPTED and r.get("entity_type_code")
    }


def build_profile() -> dict:
    providers = _read(PROVIDERS_CSV)
    services = _read(SERVICES_CSV)
    abr_types = _abr_entity_types()

    by_provider: dict[str, list[dict[str, str]]] = defaultdict(list)
    unlinked_services = 0
    for svc in services:
        pr = svc.get("provider_approval_number") or ""
        if pr:
            by_provider[pr].append(svc)
        else:
            unlinked_services += 1

    mgmt_cols = [
        c
        for c in (services[0].keys() if services else [])
        if "management" in c.lower() or "provider type" in c.lower()
    ]

    rows: list[dict] = []
    seen: set[str] = set()
    null_log: Counter[str] = Counter()
    for p in providers:
        pr = p.get("provider_approval_number") or ""
        if not pr:
            null_log["provider_approval_number_missing"] += 1
            continue
        if pr in seen:
            null_log["duplicate_provider_row_skipped"] += 1
            continue
        seen.add(pr)
        form = classify_entity_form(p.get("Legal Name"))
        withheld = name_is_withheld(p.get("Legal Name"), form, abr_types.get(pr))
        svcs = by_provider.get(pr, [])
        states = sorted({s["State"] for s in svcs if s.get("State")})
        places = [_to_int(s.get("NumberOfApprovedPlaces")) for s in svcs]
        known_places = [x for x in places if x is not None]
        row = {
            "provider_approval_number": pr,
            "legal_name": None if withheld else (p.get("Legal Name") or None),
            "trading_name": None if withheld else (p.get("Trading Name") or None),
            "name_withheld": "true" if withheld else "false",
            "entity_form": form,
            "provider_state": p.get("State") or None,
            "date_approval_granted": p.get("Date Approval Granted") or None,
            "service_count": len(svcs),
            "states_operated_in": "|".join(states) or None,
            "state_count": len(states),
            "family_day_care_services": sum(
                1 for s in svcs if s.get("ServiceType") == "Family Day Care"
            ),
            "total_approved_places": sum(known_places) if known_places else None,
            "services_without_places_value": len(places) - len(known_places),
        }
        if mgmt_cols:
            row["management_type"] = (
                "|".join(sorted({s[mgmt_cols[0]] for s in svcs if s.get(mgmt_cols[0])})) or None
            )
        rows.append(row)
        if not svcs:
            null_log["provider_with_no_services_in_services_table"] += 1

    fieldnames = [
        "provider_approval_number",
        "legal_name",
        "trading_name",
        "trading_name_note",
        "name_withheld",
        "entity_form",
        "provider_state",
        "date_approval_granted",
        "service_count",
        "states_operated_in",
        "state_count",
        "family_day_care_services",
        "total_approved_places",
        "services_without_places_value",
    ]
    if mgmt_cols:
        fieldnames.append("management_type")

    raw_inputs = _raw_inputs_of(PROVIDERS_CSV) + _raw_inputs_of(SERVICES_CSV)
    write_processed(
        "provider-profile",
        rows,
        fieldnames,
        raw_inputs=raw_inputs,
        notes=(
            "One row per provider (provider_approval_number). entity_form is a conservative "
            "classification of Legal Name by suffix and keyword; it is a heuristic, not a legal "
            "determination. Names are withheld fail closed (CLAUDE.md rule 2): legal_name and "
            "trading_name are null and name_withheld is true unless there is positive evidence "
            "of an organisation: a legal form in the name (Pty Ltd, Ltd, Limited, Inc, "
            "Incorporated, Co-operative, Corporation), a government form, or a non-individual "
            "ABR entity type from an accepted ABN match. An institutional word alone is not "
            "evidence. Person signals (individual trustees, estates, trusts named after a "
            "person) withhold the name whatever the evidence. Addresses are not carried over. "
            "service_count joins on provider_approval_number in the services table; providers "
            "with no services in that table have service_count 0, which is not evidence that "
            "they operate none. ACECQA content is not openly licensed: internal use only."
        ),
    )

    # PR #12: write_processed applied the name rule to trading_name (and counted it in the
    # provenance); the summary uses the same values (a name withheld once stays withheld).
    ensure_person_names()
    rows, fieldnames, _ = withhold_person_named_names("provider-profile", rows, fieldnames)

    # ---- summary (never includes withheld names) ----
    form_counts = Counter(r["entity_form"] for r in rows)
    form_services: Counter[str] = Counter()
    for r in rows:
        form_services[r["entity_form"]] += r["service_count"]
    total_providers = len(rows)
    total_services_linked = sum(r["service_count"] for r in rows)

    non_individual = [r for r in rows if r["name_withheld"] == "false"]
    top = sorted(
        non_individual, key=lambda r: (-r["service_count"], r["provider_approval_number"])
    )[:30]
    top_out = [
        {
            "provider_approval_number": r["provider_approval_number"],
            "legal_name": r["legal_name"],
            "trading_name": r["trading_name"],
            "entity_form": r["entity_form"],
            "service_count": r["service_count"],
            "states_operated_in": r["states_operated_in"],
        }
        for r in top
    ]

    summary = {
        "generated_at": utc_now().isoformat(),
        "inputs": {
            "providers_file": PROVIDERS_CSV.relative_to(PROJECT_ROOT).as_posix(),
            "services_file": SERVICES_CSV.relative_to(PROJECT_ROOT).as_posix(),
            "provider_rows": len(providers),
            "service_rows": len(services),
            "snapshot_last_modified_providers": (
                providers[0].get("snapshot_last_modified") if providers else None
            ),
            "snapshot_last_modified_services": (
                services[0].get("snapshot_last_modified") if services else None
            ),
            "raw_inputs": [p.relative_to(PROJECT_ROOT).as_posix() for p in raw_inputs],
        },
        "window_note": (
            "Point-in-time counts from the ACECQA register snapshot named above, not a time series. "
            "Denominator for every share: providers in the providers file, or services in the "
            "services file."
        ),
        "providers_total": total_providers,
        "services_total": len(services),
        "services_linked_to_a_provider_row": total_services_linked,
        "services_with_no_provider_approval_number": unlinked_services,
        "entity_form_counts": {f: form_counts.get(f, 0) for f in ENTITY_FORMS},
        "entity_form_share_of_providers": {
            f: round(form_counts.get(f, 0) / total_providers, 4) if total_providers else None
            for f in ENTITY_FORMS
        },
        "entity_form_service_counts": {f: form_services.get(f, 0) for f in ENTITY_FORMS},
        "entity_form_share_of_services": {
            f: round(form_services.get(f, 0) / total_services_linked, 4)
            if total_services_linked
            else None
            for f in ENTITY_FORMS
        },
        "likely_individual_providers_names_withheld": form_counts.get("likely_individual", 0),
        "providers_names_withheld_total": sum(1 for r in rows if r["name_withheld"] == "true"),
        "providers_with_no_services_in_services_table": null_log[
            "provider_with_no_services_in_services_table"
        ],
        "providers_by_service_count_band": dict(
            sorted(Counter(_band(r["service_count"]) for r in rows).items(), key=lambda kv: kv[0])
        ),
        "providers_operating_in_more_than_one_state": sum(1 for r in rows if r["state_count"] > 1),
        "service_type_distribution": dict(
            Counter(s.get("ServiceType") or "null" for s in services)
        ),
        "management_type": (
            {
                "column": mgmt_cols[0],
                "distribution": dict(Counter(s.get(mgmt_cols[0]) or "null" for s in services)),
            }
            if mgmt_cols
            else {
                "available": False,
                "reason": (
                    "Neither ACECQA export has a management type or provider type column "
                    "(headers checked). service_type_distribution is service type "
                    "(Centre-Based Care or Family Day Care), not management type. entity_form "
                    "is the only proxy, and it is inferred from the legal name."
                ),
            }
        ),
        "top_30_providers_by_service_count": top_out,
        "top_30_note": (
            "Providers whose names are withheld are excluded from this list by design. Service count is "
            "approved services on the register on the snapshot date, out of the services_total above. "
            "A large count does not by itself indicate any compliance concern."
        ),
        "row_level_logs": dict(null_log),
        "caveat": "entity_form is heuristic. Absence of a flag is not evidence of safety.",
    }
    atomic_write_text(SUMMARY_JSON, json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    log.info("summary %s", SUMMARY_JSON.relative_to(PROJECT_ROOT))
    log.info("entity_form counts: %s", summary["entity_form_counts"])
    return summary


def main(argv: list[str] | None = None) -> None:
    for path in (PROVIDERS_CSV, SERVICES_CSV):
        if not path.exists():
            raise SystemExit(
                f"missing {path.relative_to(PROJECT_ROOT)}; run "
                "python3 scrapers/snapshot_acecqa_registers.py --no-fetch"
            )
    build_profile()


if __name__ == "__main__":
    main()

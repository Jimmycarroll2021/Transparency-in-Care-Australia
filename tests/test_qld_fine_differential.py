"""Base-vs-candidate differential check for the QLD fine rule (PR #9, Codex round 3).

The base parser is loaded from git (origin/main, else main) into a temporary module. Both
parsers run over a generated synthetic corpus of register rows. The candidate must never
record a figure where the base gives null or a different figure, unless the case is on the
reviewed allowlist below. All names and wording are synthetic."""

import importlib.util
import itertools
import re
import subprocess
import sys
from pathlib import Path

import pytest
from scrapers import parse_qld_enforcement as candidate

ROOT = Path(__file__).resolve().parent.parent
HEADER = (
    "<tr><th><p>Provider or individual name</p><p>Service name</p></th>"
    "<th>Date of action</th><th>Details</th><th>Breaches (if applicable)</th></tr>"
)
SUBJECTS = ["Example Kids Pty Ltd", "Jane Example", "Educator"]
LEADS = [
    "Approved provider",
    "Provider",
    "Educator",
    "Jane Example",
    "Educator warned and operator",
    "Provider warned; director",
    "Provider will be",
    "Provider may yet be",
    "Another provider",
]
VERBS = ["fined", "was fined", "has been fined"]
AMOUNTS = ["$4,000", "$4,000.00", "$\u00a04,000", '<a href="/x.pdf">$4,000</a>', "LINK_VERB"]
CONTINUATIONS = [
    "",
    ".",
    " for a breach",
    " after a child left the service",
    ". for a breach",
    ", a day",
    " each",
    " for each offence",
    " including costs",
    ". The amount includes legal fees.",
    ". The fine was withdrawn.",
    ". The fine was later annulled.",
    " and another provider was fined",
    ", reduced on appeal",
    " for both offences",
    " twice",
    " pending review",
    ". The judgment was reversed.",
]
TRAILING = [
    "",
    '<p><a href="/d.pdf">Prosecution</a></p>',
    "<p>The amount applies for each offence.</p>",
    "<p>The fine was later annulled.</p>",
]
# Reviewed cases where the candidate records a figure that the base did not, and the figure is
# plainly right: (subject, headline HTML, trailing HTML). Keep this list short and explicit.
ALLOWED_IMPROVEMENTS: set[tuple[str, str, str]] = set()
# One reviewed category, checked case by case rather than listed: the base gives null only
# because a link inside the headline repeats the amount as a label ('fined <a>$4,000</a>' reads
# as two amounts), and the base gives the candidate's figure for the same headline with the
# link removed. The candidate reads the cell text once, so it sees one amount.
_LINK = re.compile(r'<a href="/x[.]pdf">|</a>')


def _base_module(tmp_path):
    source = None
    for ref in ("origin/main", "main"):
        try:
            done = subprocess.run(
                ["git", "show", f"{ref}:scrapers/parse_qld_enforcement.py"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        except OSError:
            pytest.skip("git is not available")
        if done.returncode == 0:
            source = done.stdout
            break
    if source is None:
        pytest.skip("no main or origin/main ref to load the base parser from")
    path = tmp_path / "qld_fine_base.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("qld_fine_base", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["qld_fine_base"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("qld_fine_base", None)
    return module


def _headlines():
    for lead, verb, amount, cont in itertools.product(LEADS, VERBS, AMOUNTS, CONTINUATIONS):
        if amount == "LINK_VERB":
            yield f'{lead} <a href="/x.pdf">{verb} $4,000</a>{cont}'
        else:
            yield f"{lead} {verb} {amount}{cont}"
    for amount, cont in itertools.product(AMOUNTS[:4], CONTINUATIONS):
        yield f"A total fine of {amount}{cont}"
        yield f"Provider fined a total of {amount}{cont}"


def _corpus():
    cases = []
    for i, (subject, headline) in enumerate(itertools.product(SUBJECTS, _headlines())):
        cases.append((subject, headline, TRAILING[i % len(TRAILING)]))
    # Every trailing paragraph against every continuation, plainly worded.
    for subject, cont, trailing in itertools.product(SUBJECTS, CONTINUATIONS, TRAILING):
        cases.append((subject, f"Provider fined $4,000{cont}", trailing))
    return cases


def _penalties(module, cases):
    rows = "".join(
        f"<tr><td><p>{s}</p></td><td>01/02/2026</td><td><p>{h}</p>{t}</td><td>N/A</td></tr>"
        for s, h, t in cases
    )
    html = f"<html><body><h2>2026</h2><table>{HEADER}{rows}</table></body></html>"
    parsed = module.parse_register(
        html,
        page_url=module.INDEX_URL,
        captured_at="2026-10-31T00:00:00+00:00",
        source_snapshot="x",
    )
    assert len(parsed) == len(cases)
    return [r["penalty_amount_aud"] for r in parsed]


def test_the_candidate_never_records_a_figure_the_base_did_not(tmp_path):
    base = _base_module(tmp_path)
    cases = _corpus()
    base_values = _penalties(base, cases)
    cand_values = _penalties(candidate, cases)
    differs = [
        (case, b, c)
        for case, b, c in zip(cases, base_values, cand_values, strict=True)
        if c is not None and c != b
    ]
    listed = [d for d in differs if d[0] in ALLOWED_IMPROVEMENTS]
    rest = [d for d in differs if d[0] not in ALLOWED_IMPROVEMENTS]
    linked = [d for d in rest if _LINK.search(d[0][1])]
    unwrapped = _penalties(base, [(s, _LINK.sub("", h), t) for (s, h, t), _, _ in linked])
    artefacts = [d for d, u in zip(linked, unwrapped, strict=True) if u == d[2]]
    looser = [d for d in rest if d not in artefacts]
    summary = {
        "corpus": len(cases),
        "base_records": sum(v is not None for v in base_values),
        "candidate_records": sum(v is not None for v in cand_values),
        "candidate_null_where_base_records": sum(
            b is not None and c is None for b, c in zip(base_values, cand_values, strict=True)
        ),
        "candidate_records_where_base_null_or_differs": len(differs),
        "allowlisted_cases": len(listed),
        "link_label_artefacts": len(artefacts),
        "looser": len(looser),
    }
    print(f"\nQLD fine differential: {summary}")
    assert not looser, "\n".join(f"{case!r}: base {b}, candidate {c}" for case, b, c in looser[:40])

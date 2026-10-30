"""Codex round 4, finding 2: reparse_offline.py is all-or-nothing."""

import pytest
from scrapers import profile_providers as pp
from scrapers import reparse_offline as ro


def make_parser(directory, name, *, fail_on_call=None, raise_on_call=None):
    """A fake parser module. Its write_processed writes <name>.csv into `directory`."""

    class Fake:
        calls = 0

        @staticmethod
        def write_processed(out_name, rows, *args, **kwargs):
            (directory / f"{out_name}.csv").write_text(f"new {len(rows)}\n", encoding="utf-8")

        @staticmethod
        def main(argv):
            Fake.calls += 1
            if raise_on_call == Fake.calls:
                raise RuntimeError("parser crashed")
            if fail_on_call == Fake.calls:
                return 2
            Fake.write_processed(name, [{"x": 1}])
            return 0

    Fake.__name__ = name
    return Fake


@pytest.fixture
def processed(tmp_path, monkeypatch):
    d = tmp_path / "processed"
    d.mkdir()
    (d / "a.csv").write_text("old a\n", encoding="utf-8")
    (d / "b.csv").write_text("old b\n", encoding="utf-8")
    (d / "enforcement-actions-all.csv").write_text("old join\n", encoding="utf-8")
    monkeypatch.setattr(ro, "PROCESSED_DIR", d)
    monkeypatch.setattr(ro, "acecqa_person_names", lambda: pp.PersonNames())

    def join_ok():
        (d / "enforcement-actions-all.csv").write_text("new join\n", encoding="utf-8")

    monkeypatch.setattr(ro, "run_join", join_ok)
    return d


def contents(d):
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(d.iterdir())}


def test_all_succeed_replaces_every_output(processed, monkeypatch):
    monkeypatch.setattr(ro, "PARSERS", [make_parser(processed, "a"), make_parser(processed, "b")])
    assert ro.main([]) == 0
    assert contents(processed) == {
        "a.csv": "new 1\n",
        "b.csv": "new 1\n",
        "enforcement-actions-all.csv": "new join\n",
    }


@pytest.mark.parametrize("how", ["exit", "raise"])
def test_a_failing_capture_parser_writes_nothing(processed, monkeypatch, how):
    bad = make_parser(
        processed, "b", **({"fail_on_call": 1} if how == "exit" else {"raise_on_call": 1})
    )
    good = make_parser(processed, "a")
    monkeypatch.setattr(ro, "PARSERS", [good, bad])
    before = contents(processed)
    assert ro.main([]) != 0
    assert contents(processed) == before
    assert good.calls == 1  # the real pass never started


@pytest.mark.parametrize("how", ["exit", "raise"])
def test_a_failing_real_pass_parser_leaves_every_output_unchanged(processed, monkeypatch, how):
    good = make_parser(processed, "a")
    bad = make_parser(
        processed, "b", **({"fail_on_call": 2} if how == "exit" else {"raise_on_call": 2})
    )
    monkeypatch.setattr(ro, "PARSERS", [good, bad])
    before = contents(processed)
    assert ro.main([]) != 0
    assert contents(processed) == before


def test_a_failing_join_restores_every_output(processed, monkeypatch):
    monkeypatch.setattr(ro, "PARSERS", [make_parser(processed, "a"), make_parser(processed, "b")])

    def join_fails():
        (processed / "enforcement-actions-all.csv").write_text("half written\n", encoding="utf-8")
        (processed / "new-file.csv").write_text("x\n", encoding="utf-8")
        raise SystemExit(2)

    monkeypatch.setattr(ro, "run_join", join_fails)
    before = contents(processed)
    assert ro.main([]) != 0
    assert contents(processed) == before

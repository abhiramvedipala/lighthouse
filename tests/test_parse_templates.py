import re
from pathlib import Path

import pytest

from lighthouse.parse.bench import grouping_accuracy
from lighthouse.parse.templates import (
    SignatureBook,
    TemplateStore,
    drain_parser,
    exception_class,
    regex_exact_parser,
)

FIXTURE = Path(__file__).parent / "fixtures" / "handwritten_logs.tsv"
LINES = [ln.split("\t") for ln in FIXTURE.read_text().splitlines()]
CONTENT = [a for a, _ in LINES]
TRUTH = [b for _, b in LINES]


def norm(t: str) -> str:
    t = re.sub(r"<\*>ms\b", "<*>", t)  # a duration mask swallows its unit
    return re.sub(r"\s+", " ", re.sub(r"<[A-Z]+>", "<*>", t).replace("=", " ")).strip()


def test_fifty_handwritten_lines_group_perfectly_with_drain():
    assert len(LINES) == 50
    assert grouping_accuracy(TRUTH, drain_parser()(CONTENT)) == 1.0


def test_mined_templates_match_expected_text():
    store = TemplateStore()
    ids = [store.add(x) for x in CONTENT]
    for cid, expected in zip(ids, TRUTH, strict=True):
        assert norm(store.template(cid)) == norm(expected)


def test_regex_baseline_also_groups_when_masks_cover_every_variable():
    assert grouping_accuracy(TRUTH, regex_exact_parser()(CONTENT)) == 1.0


def test_masks_cover_ips_hex_uuids_blocks_and_durations():
    store = TemplateStore()
    cid = store.add(
        "conn from 10.1.2.3:8080 id 0xdeadbeef blk_-123 took 15ms "
        "uuid 123e4567-e89b-12d3-a456-426614174000"
    )
    t = store.template(cid)
    for mask in ("<IP>", "<HEX>", "<BLOCK>", "<NUM>", "<UUID>"):
        assert mask in t, (mask, t)


def test_ids_stable_across_a_persisted_restart(tmp_path):
    path = tmp_path / "drain.state"
    whole = TemplateStore()
    expected = [whole.add(x) for x in CONTENT]

    first = TemplateStore(path)
    got = [first.add(x) for x in CONTENT[:25]]
    first.save()
    second = TemplateStore(path)  # a restarted consumer
    got += [second.add(x) for x in CONTENT[25:]]
    assert got == expected
    assert second.templates() == whole.templates()


def test_match_does_not_create_templates():
    store = TemplateStore()
    store.add("circuit open for inventory after 5 failures")
    n = len(store.templates())
    assert store.match("circuit open for inventory after 9 failures") is not None
    assert store.match("something entirely different happened here today") is None
    assert len(store.templates()) == n


@pytest.mark.parametrize("msg,exc", [
    ("database timeout after 15ms OperationalError", "OperationalError"),
    ("failed java.io.IOException: broken pipe", "java.io.IOException"),
    ("circuit open for orders after 5 failures", ""),
])
def test_exception_class_extraction(msg, exc):
    assert exception_class(msg) == exc


def test_signature_first_seen_and_new_since():
    book = SignatureBook()
    day = 86_400_000
    s1, new1 = book.observe("orders", 4, "db timeout OperationalError", 1 * day)
    _, new2 = book.observe("orders", 4, "db timeout OperationalError", 2 * day)
    s3, new3 = book.observe("orders", 9, "ledger conflict LedgerConflictError", 3 * day)
    assert (new1, new2, new3) == (True, False, True)
    assert book.first_seen[s1.key()] == 1 * day
    assert book.new_since(3 * day, hours=24) == [s3.key()]
    assert set(book.new_since(3 * day, hours=72)) == {s1.key(), s3.key()}
    assert book.new_since(int(1.5 * day), hours=24) == [s1.key()]  # never looks at the future


def test_signature_book_round_trip(tmp_path):
    book = SignatureBook()
    book.observe("gateway", 1, "x TimeoutError", 5)
    book.save(tmp_path / "sig.json")
    assert SignatureBook.load(tmp_path / "sig.json").first_seen == book.first_seen

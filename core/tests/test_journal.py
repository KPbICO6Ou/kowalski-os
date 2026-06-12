from kowalski.journal import EXCERPT_LIMIT, ActionJournal


def test_record_and_recent(journal: ActionJournal):
    journal.record(tool="t.a", args={"x": 1}, risk="read", decision="executed", result_ok=True)
    journal.record(tool="t.b", args={}, risk="write", decision="denied_by_user")
    entries = journal.recent(10)
    assert len(entries) == 2
    assert entries[0]["tool"] == "t.b"  # newest first
    assert entries[0]["result_ok"] is None
    assert entries[1]["result_ok"] == 1


def test_excerpt_truncated(journal: ActionJournal):
    journal.record(
        tool="t", args={}, risk="read", decision="executed",
        result_ok=True, result_excerpt="x" * 2000,
    )
    entry = journal.recent(1)[0]
    assert len(entry["result_excerpt"]) <= EXCERPT_LIMIT + 1


def test_non_serializable_args_dont_crash(journal: ActionJournal):
    journal.record(
        tool="t", args={"p": object()}, risk="read", decision="executed", result_ok=True
    )
    assert journal.recent(1)

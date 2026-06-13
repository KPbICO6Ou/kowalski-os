"""ConversationSearch + conversations.search tool tests over a tmp Store."""

from kowalski.convsearch import ConversationSearch
from kowalski.store import Store
from kowalski.tools.search import ConversationSearchArgs, build_conversation_search_tools


def seed(store: Store) -> None:
    conn = store.conn
    conn.execute("INSERT INTO conversations (id, title) VALUES ('c1', 'Travel plans')")
    conn.execute("INSERT INTO conversations (id, title) VALUES ('c2', 'Cooking')")
    # Explicit ts so ordering is deterministic (oldest -> newest).
    rows = [
        ("c1", "2026-06-01T10:00:00.000Z", "user", "How do I get to Paris by train?"),
        ("c1", "2026-06-01T10:00:01.000Z", "assistant", "Take the Eurostar to Paris."),
        ("c2", "2026-06-02T09:00:00.000Z", "user", "Best recipe for onion soup?"),
        ("c2", "2026-06-03T09:00:00.000Z", "assistant", "A classic French onion soup uses Paris..."),
    ]
    conn.executemany(
        "INSERT INTO messages (conversation_id, ts, role, content) VALUES (?, ?, ?, ?)", rows
    )
    conn.commit()


def test_search_finds_by_substring_with_title_and_snippet(tmp_store: Store):
    seed(tmp_store)
    results = ConversationSearch(tmp_store).search("Paris")
    assert len(results) == 3  # three messages mention Paris
    top = results[0]
    assert set(top) == {"conversation_id", "title", "role", "ts", "snippet"}
    assert top["title"] in {"Travel plans", "Cooking"}
    assert "Paris" in top["snippet"]


def test_search_newest_first(tmp_store: Store):
    seed(tmp_store)
    results = ConversationSearch(tmp_store).search("Paris")
    timestamps = [r["ts"] for r in results]
    assert timestamps == sorted(timestamps, reverse=True)
    assert results[0]["conversation_id"] == "c2"  # 2026-06-03 message is newest


def test_search_respects_limit(tmp_store: Store):
    seed(tmp_store)
    results = ConversationSearch(tmp_store).search("Paris", limit=1)
    assert len(results) == 1


def test_search_no_match(tmp_store: Store):
    seed(tmp_store)
    assert ConversationSearch(tmp_store).search("nonexistent-zzz") == []


def test_snippet_trimmed_to_200_chars(tmp_store: Store):
    conn = tmp_store.conn
    conn.execute("INSERT INTO conversations (id, title) VALUES ('c1', 't')")
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES ('c1', 'user', ?)",
        ("needle " + "x" * 500,),
    )
    conn.commit()
    [hit] = ConversationSearch(tmp_store).search("needle")
    assert len(hit["snippet"]) <= 200


def test_like_wildcards_matched_literally(tmp_store: Store):
    conn = tmp_store.conn
    conn.execute("INSERT INTO conversations (id, title) VALUES ('c1', 't')")
    conn.executemany(
        "INSERT INTO messages (conversation_id, role, content) VALUES ('c1', 'user', ?)",
        [("100% sure",), ("totally unrelated",)],
    )
    conn.commit()
    results = ConversationSearch(tmp_store).search("100%")
    assert len(results) == 1
    assert "100%" in results[0]["snippet"]


async def test_conversations_search_tool_formats_results(tmp_store: Store):
    seed(tmp_store)
    tool = build_conversation_search_tools(tmp_store)[0]
    assert tool.name == "conversations.search"
    result = await tool.handler(ConversationSearchArgs(query="Eurostar"))
    assert result.ok
    assert "matching messages" in result.content
    assert "Eurostar" in result.content
    assert result.data[0]["conversation_id"] == "c1"
    assert result.data[0]["role"] == "assistant"


async def test_conversations_search_tool_no_match(tmp_store: Store):
    seed(tmp_store)
    tool = build_conversation_search_tools(tmp_store)[0]
    result = await tool.handler(ConversationSearchArgs(query="zzz-nope"))
    assert result.ok
    assert result.data == []

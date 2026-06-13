from kowalski.memory.context import MemoryContextProvider
from kowalski.memory.embedder import MockEmbedder
from kowalski.memory.store import MemoryStore, cosine, pack_vector, unpack_vector


class BrokenEmbedder:
    async def embed(self, text: str):
        raise RuntimeError("ollama down")


async def _embed(embedder, text):
    return await embedder.embed(text)


def test_pack_unpack_roundtrip():
    vec = [0.5, -1.25, 3.0, 0.0]
    out = unpack_vector(pack_vector(vec))
    assert len(out) == len(vec)
    for a, b in zip(out, vec):
        assert abs(a - b) < 1e-6


def test_cosine_handles_empty():
    assert cosine([], []) == 0.0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9


async def test_remember_recall_ranks_relevant_first(tmp_store):
    mem = MemoryStore(tmp_store)
    embedder = MockEmbedder()

    relevant = "I love python programming"
    other = "My dog likes the park"
    rid = mem.remember(relevant, ["pref"], await _embed(embedder, relevant))
    mem.remember(other, [], await _embed(embedder, other))

    query = await _embed(embedder, "what programming language uses python")
    hits = mem.recall(query, k=5)
    assert hits[0]["id"] == rid
    assert hits[0]["score"] >= hits[1]["score"]


async def test_forget_removes(tmp_store):
    mem = MemoryStore(tmp_store)
    embedder = MockEmbedder()
    rid = mem.remember("coffee in the morning", [], await _embed(embedder, "coffee"))
    assert mem.forget(rid) is True
    assert mem.forget(rid) is False
    assert mem.list_memories() == []


async def test_recall_tolerates_empty_embedding(tmp_store):
    mem = MemoryStore(tmp_store)
    mem.remember("no embedding here", [], [])
    hits = mem.recall([], k=5)
    assert len(hits) == 1
    assert hits[0]["score"] == 0.0


def test_profile_set_get_all_delete(tmp_store):
    mem = MemoryStore(tmp_store)
    assert mem.get_fact("name") is None
    mem.set_fact("name", "Sam")
    mem.set_fact("color", "blue")
    assert mem.get_fact("name") == "Sam"
    mem.set_fact("name", "Samuel")  # upsert
    assert mem.get_fact("name") == "Samuel"
    assert mem.all_facts() == {"color": "blue", "name": "Samuel"}
    assert mem.delete_fact("color") is True
    assert mem.delete_fact("color") is False
    assert mem.all_facts() == {"name": "Samuel"}


async def test_context_provider_includes_profile_and_memory(tmp_store):
    mem = MemoryStore(tmp_store)
    embedder = MockEmbedder()
    mem.set_fact("name", "Sam")
    text = "I enjoy python and coffee"
    mem.remember(text, [], await _embed(embedder, text))

    provider = MemoryContextProvider(mem, embedder, k=5)
    fragment = await provider.context_for("tell me about python")

    assert "Known facts about the user:" in fragment
    assert "name: Sam" in fragment
    assert "Relevant long-term memories:" in fragment
    assert text in fragment


async def test_context_provider_resilient_when_embedder_raises(tmp_store):
    mem = MemoryStore(tmp_store)
    mem.set_fact("name", "Sam")
    mem.remember("python and coffee", [], [0.0] * 16)

    provider = MemoryContextProvider(mem, BrokenEmbedder(), k=5)
    fragment = await provider.context_for("anything")

    assert "name: Sam" in fragment
    assert "Relevant long-term memories:" not in fragment


async def test_context_provider_empty_when_nothing(tmp_store):
    mem = MemoryStore(tmp_store)
    provider = MemoryContextProvider(mem, MockEmbedder(), k=5)
    assert await provider.context_for("hello") == ""

from kowindex.chunker import chunk_text


def test_short_text_single_chunk():
    text = "Just one small paragraph."
    assert chunk_text(text) == [text]


def test_empty_text_yields_nothing():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  \n") == []


def test_chunks_respect_max_chars():
    paragraphs = [f"Paragraph {i}: " + ("lorem ipsum " * 12).strip() for i in range(40)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, max_chars=1200, overlap=200)
    assert len(chunks) > 1
    assert all(len(chunk) <= 1200 for chunk in chunks)
    assert all(chunk.strip() for chunk in chunks)


def test_overlap_carries_tail_into_next_chunk():
    paragraphs = [f"Block {i} " + ("alpha beta gamma " * 10).strip() for i in range(30)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, max_chars=600, overlap=150)
    assert len(chunks) > 2
    for previous, current in zip(chunks, chunks[1:], strict=False):
        head = current.split("\n", 1)[0]
        assert head in previous  # overlap tail repeats content from the previous chunk


def test_boundaries_fall_on_whole_lines():
    lines = [f"line {i:03d} " + "word " * 10 for i in range(120)]
    original = set(lines)
    chunks = chunk_text("\n".join(lines), max_chars=500, overlap=100)
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.strip():
                assert line in original  # no line was split mid-way


def test_pathological_single_line_is_hard_split():
    text = "x" * 5000
    chunks = chunk_text(text, max_chars=1200, overlap=200)
    assert all(len(chunk) <= 1200 for chunk in chunks)
    assert sum(len(chunk.replace("\n", "")) for chunk in chunks) >= 5000

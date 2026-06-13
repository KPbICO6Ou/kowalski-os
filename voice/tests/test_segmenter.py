from kowvoice.segmenter import SentenceSegmenter


def test_complete_sentences_emitted_on_boundary():
    seg = SentenceSegmenter()
    assert seg.feed("Hello there") == []
    assert seg.feed(". How are ") == ["Hello there."]
    assert seg.feed("you?") == []
    assert seg.flush() == "How are you?"


def test_multiple_sentences_in_one_chunk():
    seg = SentenceSegmenter()
    out = seg.feed("One. Two! Three?")
    assert out == ["One.", "Two!"]  # the last has no trailing whitespace yet
    assert seg.flush() == "Three?"


def test_newline_is_a_boundary():
    seg = SentenceSegmenter()
    assert seg.feed("a line\nmore") == ["a line"]
    assert seg.flush() == "more"


def test_ellipsis_and_streaming_deltas():
    seg = SentenceSegmenter()
    collected = []
    for delta in ["It is ", "9 PM. ", "Good ", "evening!"]:
        collected += seg.feed(delta)
    tail = seg.flush()
    if tail:
        collected.append(tail)
    assert collected == ["It is 9 PM.", "Good evening!"]

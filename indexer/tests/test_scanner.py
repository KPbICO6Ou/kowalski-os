import os
import time

from kowindex.scanner import scan, update_paths


def test_scan_indexes_text_files_and_skips_junk(tree, store, fake_embedder):
    summary = scan([tree], store, fake_embedder)
    assert summary.indexed == 2  # voice.md + mail.md
    assert summary.chunks >= 2
    assert summary.deleted == 0
    paths = set(store.all_files())
    assert str(tree / "voice.md") in paths
    assert str(tree / "mail.md") in paths
    # binary, oversized, hidden-dir and node_modules files never make it in
    assert all("blob.bin" not in p and "huge.txt" not in p for p in paths)
    assert all(".cache" not in p and "node_modules" not in p for p in paths)


def test_rescan_skips_unchanged_files(tree, store, fake_embedder):
    scan([tree], store, fake_embedder)
    calls_after_first = fake_embedder.embed_calls
    summary = scan([tree], store, fake_embedder)
    assert summary.indexed == 0
    assert summary.skipped >= 2
    assert fake_embedder.embed_calls == calls_after_first  # nothing re-embedded


def test_changed_file_is_reindexed(tree, store, fake_embedder):
    scan([tree], store, fake_embedder)
    voice = tree / "voice.md"
    voice.write_text("totally new voice pipeline text about the wake word")
    os.utime(voice, (time.time() + 5, time.time() + 5))
    summary = scan([tree], store, fake_embedder)
    assert summary.indexed == 1


def test_vanished_file_chunks_are_deleted(tree, store, fake_embedder):
    scan([tree], store, fake_embedder)
    (tree / "voice.md").unlink()
    summary = scan([tree], store, fake_embedder)
    assert summary.deleted == 1
    assert str(tree / "voice.md") not in store.all_files()
    hits = store.search(fake_embedder.embed(["voice wake word"])[0], limit=5)
    assert all("voice.md" not in hit["path"] for hit in hits)


def test_update_paths_handles_change_and_removal(tree, store, fake_embedder):
    scan([tree], store, fake_embedder)
    voice = tree / "voice.md"
    mail = tree / "mail.md"
    voice.write_text("rewritten wake word voice doc")
    os.utime(voice, (time.time() + 5, time.time() + 5))
    mail.unlink()
    summary = update_paths([voice, mail], store, fake_embedder)
    assert summary.indexed == 1
    assert summary.deleted == 1
    assert str(mail) not in store.all_files()

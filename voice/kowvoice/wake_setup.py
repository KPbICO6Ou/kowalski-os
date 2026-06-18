"""kow-voice wake: one command to set up a personal wake word end-to-end — record
your own voice, train a model on it, verify it, register it, and (optionally) test
it live. A thin orchestrator over wake-record + wake-fit + wake-test so a non-expert
runs a single command and ends up with a working wake word. Console text is English;
the spoken cues during recording are Russian (emitted by wake-record)."""

from __future__ import annotations

import sys


def _confirm(prompt: str, *, assume_yes: bool = False, default_yes: bool = True) -> bool:
    """Ask a [Y/n] question on a tty. Non-interactive (no tty) or assume_yes -> the
    default; a bare Enter -> the default."""
    if assume_yes or not sys.stdin.isatty():
        return default_yes
    suffix = "[Y/n]" if default_yes else "[y/N]"
    try:
        answer = input(f"{prompt} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default_yes
    return answer in ("y", "yes", "д", "да")


def _count(folder) -> int:
    return len(list(folder.glob("*.wav"))) if folder.exists() else 0


async def run_setup(phrase: str, *, count: int = 30, negatives: int = 12,
                    fit_only: bool = False, rerecord: bool = False,
                    no_test: bool = False, yes: bool = False) -> int:
    """Record -> train -> verify -> register a personal wake word, then offer a live
    test. Returns 0 on success, non-zero if a step fails."""
    from .train import slugify
    from .wake_record import run_record, samples_dir

    slug = slugify(phrase)
    base = samples_dir(slug)
    n_pos = _count(base / "positive")
    n_neg = _count(base / "negative")

    print(f"Wake word setup for '{phrase}'.")

    # Step 1 — Record (or reuse / skip).
    if fit_only:
        if n_pos < 5:
            print(f"--fit-only needs existing recordings, found {n_pos} positives. "
                  f"run without --fit-only to record first.", file=sys.stderr)
            return 2
        print(f"Step 1/3 — reusing {n_pos} positives + {n_neg} negatives (--fit-only).")
    else:
        complete = n_pos >= count and n_neg >= negatives
        reuse = complete and not rerecord and (
            yes or _confirm(f"Step 1/3 — found {n_pos} positives + {n_neg} negatives. Reuse them?"))
        if reuse:
            print(f"Step 1/3 — reusing {n_pos} positives + {n_neg} negatives.")
        else:
            print("Step 1/3 — recording your voice…")
            rc = await run_record(phrase, count=count, negatives=negatives)
            if rc != 0:
                return rc
            if _count(base / "positive") < 5:
                print("not enough recordings to train — run again and record more.",
                      file=sys.stderr)
                return 2

    # Step 2 — Train (Step 3 verify + registration happen inside run_fit and print
    # the real recall/FP).
    print("\nStep 2/3 — training on your recordings (~5 min, CPU)…")
    from .wake_fit import run_fit

    rc = run_fit(phrase)
    if rc != 0:
        return rc

    print(f"\n✓ Wake word '{phrase}' is ready — say it in kow chat to talk.")

    # Final — live test.
    if no_test or yes or not sys.stdin.isatty():
        print("  test it any time with: kow-voice wake-test")
        return 0
    if _confirm("Test it live now?"):
        from .cli import cmd_wake_test

        try:
            await cmd_wake_test()
        except KeyboardInterrupt:
            print()
    return 0

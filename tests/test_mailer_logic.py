"""Smoke test for mailer logic. Not part of the runtime; just to verify
the subject building + validation in isolation. Run from project root:

    python tests/test_mailer_logic.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mailer import MAX_BODY_CHARS, SUBJECT_PREVIEW_CHARS, build_subject, validate_note  # noqa: E402

cases = [
    ("hello world",                       "NTS:hello world"),
    ("a",                                 "NTS:a"),
    ("This is exactly twenty  ",          "NTS:This is exactly twenty"),
    ("x" * 20,                            "NTS:" + "x" * 20),
    ("x" * 21,                            "NTS:" + "x" * 20),
    ("x" * 100,                           "NTS:" + "x" * 20),
]
print("=== build_subject ===")
for note, expected in cases:
    got = build_subject(note)
    status = "OK" if got == expected else "FAIL"
    print(f"  {status}  in={len(note):>3}  got={got!r}")

print()
print("=== validate_note ===")
for label, value in [
    ("empty string", ""),
    ("whitespace only", "   \n\t"),
    ("non-string", 12345),
    (f"too long ({MAX_BODY_CHARS + 1})", "x" * (MAX_BODY_CHARS + 1)),
    (f"max ({MAX_BODY_CHARS})", "x" * MAX_BODY_CHARS),
    ("normal", "buy milk"),
]:
    try:
        validate_note(value)
        print(f"  OK   {label}: accepted")
    except (ValueError, TypeError) as e:
        print(f"  OK   {label}: rejected -> {e}")

print()
print(f"SUBJECT_PREVIEW_CHARS = {SUBJECT_PREVIEW_CHARS}  MAX_BODY_CHARS = {MAX_BODY_CHARS}")

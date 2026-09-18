"""Regression tests for Student academic year/batch consistency.

The invariant is intentionally semester-driven:
  I-I/I-II   -> 1st Year
  II-I/II-II -> 2nd Year
  III-I/III-II -> 3rd Year
  IV-I/IV-II -> 4th Year

For academic year 2026-27, that means:
  1st -> 2026-2030 Batch
  2nd -> 2025-2029 Batch
  3rd -> 2024-2028 Batch
  4th -> 2023-2027 Batch

Roll-number structure is deliberately irrelevant. This protects lateral-entry
and legacy/non-standard roll numbers from being classified into the wrong year.
"""

from datetime import datetime
import os

import pytest

from api.routes_students import (
    SEMESTER_YEAR_BY_ID,
    _academic_year_start,
    _compute_year_and_batch,
    _enforce_semester_year_filter,
    _validate_semester_selection,
)


class _FakeCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, row):
        self.row = row

    def execute(self, *_args, **_kwargs):
        return _FakeCursor(self.row)


def test_semester_ids_map_to_exact_study_years():
    assert SEMESTER_YEAR_BY_ID == {
        1: 1, 2: 1,
        3: 2, 4: 2,
        5: 3, 6: 3,
        7: 4, 8: 4,
    }


def test_academic_year_rollover_is_deterministic():
    assert _academic_year_start(datetime(2026, 9, 18)) == 2026
    assert _academic_year_start(datetime(2026, 5, 31)) == 2025


def test_third_year_first_semester_is_2024_2028_for_2026_27():
    year, batch = _compute_year_and_batch(
        {"roll_no": "25LE1A9999", "current_semester_id": 5},
        datetime(2026, 9, 18),
    )
    assert year == "3rd Year"
    assert batch == "2024-2028 Batch"


def test_roll_number_does_not_override_semester_authority():
    # This reproduces the reported edge case: a lateral-entry/legacy roll
    # number can look like a 2025 cohort while the student is actually in III-I.
    year, batch = _compute_year_and_batch(
        {"roll_no": "25BG5A6701", "current_semester_id": 5},
        datetime(2026, 9, 18),
    )
    assert year == "3rd Year"
    assert batch == "2024-2028 Batch"

    # Conversely, a 2024-looking roll placed in II-I must display 2nd Year
    # and the 2025-2029 cohort because the semester is authoritative.
    year, batch = _compute_year_and_batch(
        {"roll_no": "24BT1A6701", "current_semester_id": 3},
        datetime(2026, 9, 18),
    )
    assert year == "2nd Year"
    assert batch == "2025-2029 Batch"


def test_all_semesters_derive_the_expected_year_and_batch():
    expected = {
        1: ("1st Year", "2026-2030 Batch"),
        2: ("1st Year", "2026-2030 Batch"),
        3: ("2nd Year", "2025-2029 Batch"),
        4: ("2nd Year", "2025-2029 Batch"),
        5: ("3rd Year", "2024-2028 Batch"),
        6: ("3rd Year", "2024-2028 Batch"),
        7: ("4th Year", "2023-2027 Batch"),
        8: ("4th Year", "2023-2027 Batch"),
    }
    for semester_id, expected_value in expected.items():
        assert _compute_year_and_batch(
            {"roll_no": "ARBITRARY-ROLL-FORMAT", "current_semester_id": semester_id},
            datetime(2026, 9, 18),
        ) == expected_value


def test_selected_semester_only_needs_to_exist():
    fake_db = _FakeConnection({"id": 5})
    _validate_semester_selection(fake_db, 5)


def test_nonexistent_semester_is_rejected():
    fake_db = _FakeConnection(None)
    with pytest.raises(ValueError, match="Selected semester does not exist"):
        _validate_semester_selection(fake_db, 999)


def test_semester_filter_keeps_only_rows_for_that_semesters_year():
    rows = [
        {"roll_no": "25LE1A6701", "year_of_study": "3rd Year"},
        {"roll_no": "24BT1A6701", "year_of_study": "2nd Year"},
    ]
    filtered = _enforce_semester_year_filter(rows, 5)  # III-I
    assert [r["roll_no"] for r in filtered] == ["25LE1A6701"]


def test_live_student_data_audit_checks_stored_batch_against_semester(monkeypatch):
    """Optional real-DB audit for legacy/stale stored batch values.

    Run with RUN_STUDENT_DATA_INTEGRITY=1 against the target DB. The audit does
    not compare roll-number prefixes because those are deliberately not a source
    of academic truth. It checks that persisted `batch` matches the semester-
    derived batch and reports every stale row.
    """
    if os.getenv("RUN_STUDENT_DATA_INTEGRITY") != "1":
        pytest.skip("Set RUN_STUDENT_DATA_INTEGRITY=1 to audit the live student table")

    from database import connect

    reference = datetime(2026, 9, 18)
    with connect() as c:
        rows = c.execute(
            """SELECT roll_no, batch, current_semester_id
               FROM students
               WHERE department='CSD' AND active=1
               ORDER BY UPPER(roll_no)"""
        ).fetchall()

    mismatches = []
    for row in rows:
        expected_year, expected_batch = _compute_year_and_batch(
            {"current_semester_id": row["current_semester_id"]}, reference
        )
        stored_batch = str(row.get("batch") or "").strip()
        if expected_batch and stored_batch != expected_batch.removesuffix(" Batch"):
            mismatches.append(
                f"{row['roll_no']} -> stored={stored_batch!r}, expected={expected_batch!r}, semester={row['current_semester_id']}"
            )

    assert not mismatches, "Stale academic batch values found: " + "; ".join(mismatches)

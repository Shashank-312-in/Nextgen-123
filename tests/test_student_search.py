"""Focused tests for the Students List search contract."""

from api.routes_students import _student_search_sql


def test_empty_search_adds_no_predicate():
    assert _student_search_sql("") == ("", [])
    assert _student_search_sql("   ") == ("", [])


def test_name_search_only_targets_name_and_exact_roll():
    sql, args = _student_search_sql("Anita")
    assert "name LIKE ?" in sql
    assert "UPPER(roll_no) = UPPER(?)" in sql
    assert "email" not in sql
    assert "phone" not in sql
    assert "parent_phone" not in sql
    assert args == ["%Anita%", "Anita"]


def test_roll_suffix_uses_exactly_entered_digit_count():
    for value, digits in (("7", 1), ("47", 2), ("104", 3), ("1047", 4)):
        sql, args = _student_search_sql(value)
        assert sql == " AND RIGHT(roll_no, ?) = ?"
        assert args == [digits, value]


def test_five_or_more_numeric_digits_do_not_become_partial_roll_search():
    sql, args = _student_search_sql("12345")
    assert sql == " AND UPPER(roll_no) = UPPER(?)"
    assert args == ["12345"]


def test_ten_digit_phone_is_exact_only():
    sql, args = _student_search_sql("9876543210")
    assert sql == " AND phone = ?"
    assert args == ["9876543210"]
    assert "LIKE" not in sql


def test_full_alphanumeric_roll_can_match_exactly():
    sql, args = _student_search_sql("23CSD1047")
    assert "UPPER(roll_no) = UPPER(?)" in sql
    assert args[-1] == "23CSD1047"

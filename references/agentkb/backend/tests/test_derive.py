from datetime import date

from app.services.resume.derive import derive_years_experience, detect_conflicts


def test_years_experience_merges_overlapping_full_time_intervals():
    c = {"work": [
        {"type": "full_time", "start": "2020-01", "end": "2020-12"},
        {"type": "full_time", "start": "2020-06", "end": "2021-05"},
        {"type": "intern", "start": "2018-01", "end": "2019-12"},
    ]}
    assert derive_years_experience(c, date(2021, 5, 1)) == 1


def test_years_experience_uses_reference_date_for_current_job():
    c = {"work": [{"type": "full_time", "start": "2020-01", "end": None}]}
    assert derive_years_experience(c, date(2021, 1, 1)) == 1


def test_detect_conflicts_marks_overlapping_work():
    c = {"work": [
        {"start": "2020-01", "end": "2021-01"},
        {"start": "2020-06", "end": "2021-06"},
    ]}
    assert detect_conflicts(c)[0]["type"] == "timeline_overlap"


def test_detect_conflicts_marks_end_before_start():
    c = {"work": [
        {"start": "2021-06", "end": "2020-01"},
    ]}
    conflicts = detect_conflicts(c)
    assert conflicts and conflicts[0]["type"] == "value_conflict"
    assert conflicts[0]["field"] == "work[0].end"


def test_detect_conflicts_marks_missing_start():
    c = {"work": [
        {"start": None, "end": "2021-06"},
    ]}
    conflicts = detect_conflicts(c)
    assert conflicts and conflicts[0]["type"] == "other"
    assert conflicts[0]["field"] == "work[0].start"


def test_detect_conflicts_ignores_current_job_without_end():
    c = {"work": [
        {"start": "2020-01", "end": None},
    ]}
    assert detect_conflicts(c) == []
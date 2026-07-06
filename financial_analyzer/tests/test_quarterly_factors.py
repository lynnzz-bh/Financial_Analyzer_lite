import pytest

from src.factors.quarterly_factors import split_ytd_reports_to_quarters


def test_split_ytd_reports_to_quarters_builds_independent_qtr_values() -> None:
    result = split_ytd_reports_to_quarters(
        [
            {"report_period": "2025Q1", "营业收入": 100, "归母净利润": 10},
            {"report_period": "2025H1", "营业收入": 260, "归母净利润": 30},
            {"report_period": "2025Q3", "营业收入": 450, "归母净利润": 60},
            {"report_period": "2025A", "营业收入": 700, "归母净利润": 100},
        ],
        ["营业收入", "归母净利润"],
        report_name="income_statement",
    )

    assert result["status"] == "ok"
    assert result["warnings"] == []
    assert [quarter["qtr_period"] for quarter in result["quarters"]] == ["2025Q1", "2025Q2", "2025Q3", "2025Q4"]
    assert [quarter["source_period"] for quarter in result["quarters"]] == ["2025Q1", "2025H1", "2025Q3", "2025A"]
    assert result["quarters"][0]["depends_on"] == ["2025Q1"]
    assert result["quarters"][1]["depends_on"] == ["2025H1", "2025Q1"]
    assert result["quarters"][2]["depends_on"] == ["2025Q3", "2025H1"]
    assert result["quarters"][3]["depends_on"] == ["2025A", "2025Q3"]
    assert [quarter["values"]["营业收入_QTR"] for quarter in result["quarters"]] == [100, 160, 190, 250]
    assert [quarter["values"]["归母净利润_QTR"] for quarter in result["quarters"]] == [10, 20, 30, 40]
    assert all("营业收入" not in quarter["values"] for quarter in result["quarters"])


def test_q3_without_ytd_marker_is_treated_as_cumulative_ytd() -> None:
    result = split_ytd_reports_to_quarters(
        [
            {"report_period": "2025H1", "营业收入": 260},
            {"report_period": "2025Q3", "营业收入": 450},
        ],
        ["营业收入"],
    )

    q3 = result["quarters"][1]
    assert q3["source_period"] == "2025Q3"
    assert q3["qtr_period"] == "2025Q3"
    assert q3["values"]["营业收入_QTR"] == pytest.approx(190)


def test_input_order_is_sorted_without_warning() -> None:
    result = split_ytd_reports_to_quarters(
        [
            {"report_period": "2025A", "营业收入": 700},
            {"report_period": "2025Q3", "营业收入": 450},
            {"report_period": "2025H1", "营业收入": 260},
            {"report_period": "2025Q1", "营业收入": 100},
        ],
        ["营业收入"],
    )

    assert result["status"] == "ok"
    assert result["warnings"] == []
    assert [quarter["qtr_period"] for quarter in result["quarters"]] == ["2025Q1", "2025Q2", "2025Q3", "2025Q4"]
    assert [quarter["values"]["营业收入_QTR"] for quarter in result["quarters"]] == [100, 160, 190, 250]


def test_missing_q1_keeps_h1_q2_result_unavailable() -> None:
    result = split_ytd_reports_to_quarters(
        [{"report_period": "2025H1", "营业收入": 260}],
        ["营业收入"],
        report_name="income_statement",
    )

    assert result["status"] == "unavailable"
    assert len(result["quarters"]) == 1
    q2 = result["quarters"][0]
    assert q2["qtr_period"] == "2025Q2"
    assert q2["values"]["营业收入_QTR"] is None
    assert q2["status"] == "unavailable"
    assert q2["warnings"][0]["issue_type"] == "missing_dependency"
    assert q2["warnings"][0]["missing_period"] == "2025Q1"
    assert result["warnings"][0]["issue_type"] == "missing_dependency"


def test_missing_h1_keeps_q3_unavailable_but_q1_ok() -> None:
    result = split_ytd_reports_to_quarters(
        [
            {"report_period": "2025Q1", "营业收入": 100},
            {"report_period": "2025Q3", "营业收入": 450},
        ],
        ["营业收入"],
    )

    assert result["status"] == "warning"
    assert [quarter["qtr_period"] for quarter in result["quarters"]] == ["2025Q1", "2025Q3"]
    assert result["quarters"][0]["status"] == "ok"
    assert result["quarters"][0]["values"]["营业收入_QTR"] == pytest.approx(100)
    assert result["quarters"][1]["status"] == "unavailable"
    assert result["quarters"][1]["values"]["营业收入_QTR"] is None
    assert result["quarters"][1]["warnings"][0]["missing_period"] == "2025H1"


def test_duplicate_period_uses_last_row_and_records_warning() -> None:
    result = split_ytd_reports_to_quarters(
        [
            {"report_period": "2025Q1", "营业收入": 100},
            {"report_period": "2025Q1", "营业收入": 110},
            {"report_period": "2025H1", "营业收入": 260},
        ],
        ["营业收入"],
    )

    assert result["status"] == "warning"
    assert result["warnings"][0]["issue_type"] == "duplicate_period"
    assert result["quarters"][0]["values"]["营业收入_QTR"] == pytest.approx(110)
    assert result["quarters"][1]["values"]["营业收入_QTR"] == pytest.approx(150)


def test_invalid_period_is_skipped_and_records_warning() -> None:
    result = split_ytd_reports_to_quarters(
        [
            {"report_period": "2025-03-31", "营业收入": 999},
            {"report_period": "2025Q1", "营业收入": 100},
        ],
        ["营业收入"],
    )

    assert result["status"] == "warning"
    assert result["warnings"][0]["issue_type"] == "invalid_period"
    assert len(result["quarters"]) == 1
    assert result["quarters"][0]["qtr_period"] == "2025Q1"
    assert result["quarters"][0]["values"]["营业收入_QTR"] == pytest.approx(100)


def test_empty_or_all_invalid_input_is_unavailable() -> None:
    empty = split_ytd_reports_to_quarters([], ["营业收入"])
    invalid = split_ytd_reports_to_quarters([{"report_period": "bad", "营业收入": 100}], ["营业收入"])

    assert empty["status"] == "unavailable"
    assert empty["quarters"] == []
    assert empty["warnings"] == []
    assert invalid["status"] == "unavailable"
    assert invalid["quarters"] == []
    assert invalid["warnings"][0]["issue_type"] == "invalid_period"

import pytest

from lighthouse.parse.bench import evaluate_parser, grouping_accuracy, template_counts

TRUTH = ["A", "A", "B", "B", "B"]


def test_perfect_grouping_scores_one():
    assert grouping_accuracy(TRUTH, [1, 1, 2, 2, 2]) == 1.0


def test_group_labels_do_not_matter_only_partition():
    assert grouping_accuracy(TRUTH, ["x", "x", "y", "y", "y"]) == 1.0


def test_merging_everything_scores_zero():
    assert grouping_accuracy(TRUTH, [0, 0, 0, 0, 0]) == 0.0


def test_splitting_one_group_loses_only_that_group():
    # B is split in two: only the two A lines are still exactly right
    assert grouping_accuracy(TRUTH, [1, 1, 2, 2, 3]) == pytest.approx(0.4)


def test_one_stray_line_costs_the_whole_group():
    # the last B line joins A's group: both predicted groups are impure or incomplete
    assert grouping_accuracy(TRUTH, [1, 1, 1, 2, 2]) == 0.0


def test_exact_match_baseline_over_splits():
    lines = ["a 1", "a 2", "b 1"]
    assert grouping_accuracy(["A", "A", "B"], lines) == pytest.approx(1 / 3)


def test_empty_input_is_zero_and_length_mismatch_raises():
    assert grouping_accuracy([], []) == 0.0
    with pytest.raises(ValueError):
        grouping_accuracy(["A"], [1, 2])


def test_template_counts_found_vs_true():
    assert template_counts(TRUTH, [1, 2, 3, 4, 5]) == (5, 2)


def test_evaluate_parser_reports_all_fields():
    r = evaluate_parser(lambda lines: [len(x) for x in lines], ["ab", "cd", "efg"], ["A", "A", "B"])
    assert r["grouping_accuracy"] == 1.0
    assert (r["templates_found"], r["templates_true"]) == (2, 2)
    assert r["seconds"] >= 0

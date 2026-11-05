# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import math

import pytest


@pytest.fixture
def comparison():
    # The benchmark runner overlays head tests onto base source. Import only when
    # these non-benchmark tests run, since base may not contain the dev module.
    from dev import benchmark_statistics

    return benchmark_statistics


def make_blocks(effects=(1.0,), count=10):
    blocks = []
    for index in range(count):
        order = ("base", "head", "head", "base")
        if index % 2:
            order = ("head", "base", "base", "head")
        blocks.append(
            [
                {
                    "revision": revision,
                    "benchmarks": [
                        {
                            "fullname": f"case-{case}",
                            "stats": {"median": effect if revision == "head" else 1.0},
                        }
                        for case, effect in enumerate(effects)
                    ],
                }
                for revision in order
            ]
        )
    return blocks


@pytest.mark.parametrize(
    "ratio, classification, percent",
    [
        (1.05, "regression", 5),
        (1.0, "within_threshold", 0),
        (1 / 1.05, "improvement", -100 / 21),
        (1.02, "within_threshold", 2),
        (1 / 1.02, "within_threshold", -100 / 51),
    ],
)
def test_consistent_effect_and_inclusive_thresholds(comparison, ratio, classification, percent):
    result = comparison.compare_blocks(make_blocks((ratio,)))
    case = result["benchmarks"][0]
    assert result["regression"] is (classification == "regression")
    assert case["classification"] == classification
    assert case["estimate_percent"] == pytest.approx(percent)
    assert case["interval_percent"] == pytest.approx([percent, percent])
    assert case["block_ratios"] == pytest.approx([ratio] * 10)


def test_noisy_data_is_inconclusive(comparison):
    blocks = make_blocks((1.0,) * 7)
    for index, block in enumerate(blocks):
        for run in block:
            if run["revision"] == "head":
                for entry in run["benchmarks"]:
                    entry["stats"]["median"] = 0.8 if index % 2 else 1.3
    result = comparison.compare_blocks(blocks)
    assert not result["regression"]
    for case in result["benchmarks"]:
        assert case["classification"] == "inconclusive"
        assert case["interval_percent"] == pytest.approx([-20, 30])


def test_block_offset_linear_log_drift_and_second_position_cancel(comparison):
    blocks = make_blocks((1.05,))
    for block_index, block in enumerate(blocks):
        for position, run in enumerate(block):
            # Vary the block offset, add equally spaced log drift, and penalize
            # the second observation of each adjacent pair.
            nuisance = block_index * 0.4 + position * 0.08 + (position % 2) * 0.13
            run["benchmarks"][0]["stats"]["median"] *= math.exp(nuisance)
    case = comparison.compare_blocks(blocks)["benchmarks"][0]
    assert case["classification"] == "regression"
    assert case["block_ratios"] == pytest.approx([1.05] * 10)


@pytest.mark.parametrize("block_count, case_count", [(5, 1), (8, 7)])
def test_confidence_counts_blocks_and_all_comparisons(comparison, block_count, case_count):
    result = comparison.compare_blocks(make_blocks((1.5,) * case_count, count=block_count))
    assert result["block_count"] == block_count
    assert not result["regression"]
    for case in result["benchmarks"]:
        assert case["interval_percent"] is None
        assert case["classification"] == "inconclusive"


def test_multiple_comparisons_widen_interval(comparison):
    single = make_blocks()
    multiple = make_blocks((1.0,) * 7)
    for index, ratio in enumerate((0.9, 1.05, 1.06, 1.07, 1.08, 1.09, 1.1, 1.11, 1.12, 1.2)):
        for blocks in (single, multiple):
            for run in blocks[index]:
                if run["revision"] == "head":
                    for entry in run["benchmarks"]:
                        entry["stats"]["median"] = ratio
    one = comparison.compare_blocks(single)["benchmarks"][0]
    seven = comparison.compare_blocks(multiple)["benchmarks"][0]
    # Ten samples allow the second through ninth observations for one median.
    # Seven simultaneous comparisons require the first through tenth.
    assert one["interval_percent"] == pytest.approx([5, 12])
    assert one["classification"] == "regression"
    assert seven["interval_percent"] == pytest.approx([-10, 20])
    assert seven["classification"] == "inconclusive"


def test_matching_names_need_not_have_same_entry_order(comparison):
    blocks = make_blocks((1.0, 1.05))
    blocks[1][1]["benchmarks"].reverse()
    result = comparison.compare_blocks(blocks)
    assert [case["name"] for case in result["benchmarks"]] == ["case-0", "case-1"]
    assert [case["classification"] for case in result["benchmarks"]] == [
        "within_threshold",
        "regression",
    ]


@pytest.mark.parametrize("value", [0, -1, math.inf, -math.inf, math.nan, True, "1.0", None])
def test_invalid_samples_are_rejected(comparison, value):
    blocks = make_blocks()
    blocks[0][0]["benchmarks"][0]["stats"]["median"] = value
    with pytest.raises(ValueError, match="Median"):
        comparison.compare_blocks(blocks)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "empty", "missing_stats"])
def test_incomplete_benchmark_results_are_rejected(comparison, mutation):
    blocks = make_blocks((1.0, 1.0))
    entries = blocks[1][2]["benchmarks"]
    if mutation == "missing":
        entries.pop()
    elif mutation == "duplicate":
        entries.append(entries[0])
    elif mutation == "empty":
        entries.clear()
    else:
        del entries[0]["stats"]
    with pytest.raises(ValueError):
        comparison.compare_blocks(blocks)


@pytest.mark.parametrize("head, base", [(1e300, 1e-100), (1e308, 1.0), (1e-300, 1e100)])
def test_unrepresentable_output_is_rejected(comparison, head, base):
    blocks = make_blocks()
    for block in blocks:
        for run in block:
            run["benchmarks"][0]["stats"]["median"] = head if run["revision"] == "head" else base
    with pytest.raises(ValueError, match="numeric range"):
        comparison.compare_blocks(blocks)


@pytest.mark.parametrize("revisions", [("base", "base", "head", "head"), ("base", "head")])
def test_wrong_order_and_partial_block_are_rejected(comparison, revisions):
    blocks = make_blocks()
    blocks[0] = blocks[0][: len(revisions)]
    for run, revision in zip(blocks[0], revisions):
        run["revision"] = revision
    with pytest.raises(ValueError):
        comparison.compare_blocks(blocks)


def test_empty_input_is_rejected(comparison):
    with pytest.raises(ValueError, match="complete block"):
        comparison.compare_blocks([])


@pytest.mark.parametrize("threshold", [-0.1, math.inf, math.nan, True])
def test_invalid_threshold_is_rejected(comparison, threshold):
    with pytest.raises(ValueError, match="Threshold"):
        comparison.compare_blocks(make_blocks(), threshold=threshold)


def test_report_exposes_uncertainty_and_all_block_ratios(comparison):
    report = comparison.render_report(comparison.compare_blocks(make_blocks((1.05,))))
    assert "+5.00%" in report
    assert "regression" in report
    assert "10 blocks" in report
    assert report.count("1.050000") == 10
    incomplete = comparison.render_report(comparison.compare_blocks(make_blocks(count=2)))
    assert "insufficient blocks" in incomplete
    assert "inconclusive" in incomplete

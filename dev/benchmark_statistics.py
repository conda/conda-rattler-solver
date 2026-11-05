# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
"""Compare independent ABBA/BAAB blocks with simultaneous median intervals.

The sample unit is one four-process block. Inner pytest rounds are not independent
samples here. The order-statistic interval uses the Binomial(n, 0.5) distribution,
with Bonferroni adjustment for 95% coverage across the complete benchmark set.
This assumes independent blocks and does not correct arbitrary time drift.

References:
https://asv.readthedocs.io/projects/asv-runner/en/stable/apidocs/asv_runner/asv_runner.statistics.html
https://www.itl.nist.gov/div898/handbook/prc/section4/prc473.htm
"""

from __future__ import annotations

import math
import statistics

_ORDERS = (("base", "head", "head", "base"), ("head", "base", "base", "head"))


def _number(value, label: str, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} is outside the supported numeric range") from exc
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"{label} must be finite and {'positive' if positive else 'nonnegative'}")
    return number


def _medians(run: dict) -> dict[str, float]:
    entries = run.get("benchmarks")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Every process must contain nonempty benchmark results")
    values = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Benchmark entries must be objects")
        name = entry.get("fullname")
        if not isinstance(name, str) or not name or name in values:
            raise ValueError("Benchmark names must be nonempty and unique within each process")
        stats = entry.get("stats")
        if not isinstance(stats, dict):
            raise ValueError(f"Missing statistics for {name}")
        values[name] = _number(stats.get("median"), f"Median for {name}")
    return values


def _interval_index(count: int, comparisons: int) -> int | None:
    """Return the tightest symmetric interval meeting the family coverage target."""
    tail = 0
    selected = None
    for index in range((count + 1) // 2):
        tail += math.comb(count, index)
        # 2 * P(Binomial(count, 0.5) <= index) <= 0.05 / comparisons.
        # Integer arithmetic avoids rounding the selected order statistic.
        if 40 * comparisons * tail > 2**count:
            break
        selected = index
    return selected


def _ratio(log_ratio: float) -> float:
    try:
        ratio = math.exp(log_ratio)
    except OverflowError as exc:
        raise ValueError("A benchmark ratio exceeds the supported numeric range") from exc
    if ratio == 0:
        raise ValueError("A benchmark ratio is below the supported numeric range")
    if not math.isfinite(100 * (ratio - 1)):
        raise ValueError("A benchmark percentage exceeds the supported numeric range")
    return ratio


def compare_blocks(blocks: list[list[dict]], threshold: float = 0.02) -> dict:
    """Return advisory estimates and conservative regression classifications.

    Thresholds are symmetric in log space: a slowdown ratio of 1 + threshold
    and an improvement ratio of 1 / (1 + threshold). An interval crossing either
    threshold remains inconclusive. Too few blocks for a finite simultaneous
    interval also remain inconclusive. Invalid or incomplete results raise ValueError.
    """
    threshold = _number(threshold, "Threshold", positive=False)
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("At least one complete block is required")
    samples = None
    for block in blocks:
        if (
            not isinstance(block, list)
            or len(block) != 4
            or not all(isinstance(run, dict) for run in block)
        ):
            raise ValueError("Each block must contain four process results")
        order = tuple(run.get("revision") for run in block)
        if order not in _ORDERS:
            raise ValueError("Each block must use ABBA or BAAB revision order")
        runs = [_medians(run) for run in block]
        if samples is None:
            samples = {name: [] for name in sorted(runs[0])}
        if any(set(run) != set(samples) for run in runs):
            raise ValueError("All processes must contain exactly the same benchmark names")
        for name, values in samples.items():
            head = [
                math.log(run[name]) for revision, run in zip(order, runs) if revision == "head"
            ]
            base = [
                math.log(run[name]) for revision, run in zip(order, runs) if revision == "base"
            ]
            values.append((math.fsum(head) - math.fsum(base)) / 2)

    index = _interval_index(len(blocks), len(samples))
    limit = math.log1p(threshold)
    cases = []
    for name, values in samples.items():
        interval = None
        classification = "inconclusive"
        if index is not None:
            ordered = sorted(values)
            low, high = ordered[index], ordered[-index - 1]
            interval = [100 * (_ratio(low) - 1), 100 * (_ratio(high) - 1)]
            # Treat numerical roundoff at an exact threshold as equality.
            tolerance = 1e-12
            if low > limit + tolerance:
                classification = "regression"
            elif high < -limit - tolerance:
                classification = "improvement"
            elif low >= -limit - tolerance and high <= limit + tolerance:
                classification = "within_threshold"
        cases.append(
            {
                "name": name,
                "classification": classification,
                "estimate_percent": 100 * (_ratio(statistics.median(values)) - 1),
                "interval_percent": interval,
                "block_ratios": [_ratio(value) for value in values],
            }
        )
    return {
        "block_count": len(blocks),
        "benchmark_count": len(cases),
        "family_confidence": 0.95,
        "threshold": threshold,
        "regression": any(case["classification"] == "regression" for case in cases),
        "benchmarks": cases,
    }


def render_report(result: dict) -> str:
    """Render estimates, uncertainty and every block ratio without hiding noisy cases."""
    threshold = result["threshold"]
    lines = [
        "## Advisory benchmark comparison",
        "",
        "Performance classifications do not fail CI. Detecting small changes depends on noise.",
        "",
        (
            f"{result['block_count']} blocks, four fresh processes per block "
            "in ABBA or BAAB order. "
            "Intervals estimate the median block ratio and assume independent blocks."
        ),
        "",
        (
            f"The slowdown threshold is +{100 * threshold:.2f}%. "
            f"The reciprocal improvement threshold is {100 * (1 / (1 + threshold) - 1):+.2f}%."
        ),
        "",
        "| Benchmark | Estimated time change | 95% simultaneous interval | Result |",
        "|---|---:|---:|---|",
    ]
    for case in result["benchmarks"]:
        name = case["name"].replace("|", "\\|").replace("\n", " ")
        interval = case["interval_percent"]
        bounds = (
            "insufficient blocks"
            if interval is None
            else f"{interval[0]:+.2f}% to {interval[1]:+.2f}%"
        )
        lines.append(
            f"| {name} | {case['estimate_percent']:+.2f}% | {bounds} | {case['classification']} |"
        )
    lines.extend(
        ["", "Inconclusive results do not establish that a change meets the threshold.", ""]
    )
    lines.append("Block ratios, in execution order, expressed as head time / base time:")
    lines.append("")
    for case in result["benchmarks"]:
        name = case["name"].replace("\n", " ")
        lines.append(f"- {name}: " + ", ".join(f"{ratio:.6f}" for ratio in case["block_ratios"]))
    return "\n".join(lines) + "\n"

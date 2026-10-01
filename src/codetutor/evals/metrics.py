"""Numbers from eval results: pass@k, slices by module/difficulty/concept, failure analysis.

Pure functions: they take EvalRecords (and the problem bank) and return numbers. No printing and
no writing, so every number can be checked by hand in tests. report.py turns them into Markdown.

Every *problem* counts equally: per-problem numbers are computed first, then averaged.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median

from codetutor.evals.extract import ExtractMethod
from codetutor.evals.passk import pass_at_k
from codetutor.evals.records import EvalRecord, read_records
from codetutor.evals.run import RunMeta, meta_path_for
from codetutor.grader import TestStatus
from codetutor.problems import Problem

DIFFICULTY_ORDER = {"easy": 0, "medium": 1, "hard": 2}
GroupKey = Callable[[Problem], list[str]]


@dataclass(frozen=True)
class RunData:
    """One results file and the meta file next to it."""

    meta: RunMeta
    records: list[EvalRecord]

    @property
    def expected(self) -> int:
        """Answers a complete run has: problems x samples."""
        return len(self.meta.problem_versions) * self.meta.config.samples

    @property
    def is_partial(self) -> bool:
        """True while some answers are missing (e.g. a run stopped by a daily quota)."""
        return len(self.records) < self.expected


@dataclass(frozen=True)
class ProblemStats:
    """One problem in one run."""

    n: int  # answers
    c: int  # accepted answers
    mean_reward: float


@dataclass(frozen=True)
class GroupStats:
    """One module, difficulty or concept in one run."""

    problems: int
    pass_at_1: float
    mean_reward: float


@dataclass(frozen=True)
class Failures:
    """How a run's answers went wrong."""

    answers: int
    wrong: int  # answers that were not accepted
    by_status: dict[str, int]  # wrong answers by grade status
    hidden_only: int  # wrong answers that passed every visible test
    cut_off: int  # answers cut off by max_tokens (finish_reason "length")
    format_failures: int  # answers whose code was not found in a ```python block


@dataclass(frozen=True)
class FailingTest:
    """The test that a problem's wrong answers failed most often."""

    test_id: str
    hidden: bool
    note: str | None  # from tests.yaml: says what the test checks
    count: int  # wrong answers that failed it


def load_run(results_path: Path) -> RunData:
    """Read a results file and its meta file."""
    meta_text = meta_path_for(results_path).read_text(encoding="utf-8")
    return RunData(meta=RunMeta.model_validate_json(meta_text), records=read_records(results_path))


def problem_stats(records: list[EvalRecord]) -> dict[str, ProblemStats]:
    """n, c and mean reward for every problem that has answers, sorted by problem id."""
    grouped: dict[str, list[EvalRecord]] = defaultdict(list)
    for record in records:
        grouped[record.problem_id].append(record)
    return {
        problem_id: ProblemStats(
            n=len(answers),
            c=sum(answer.passed for answer in answers),
            mean_reward=mean(answer.result.reward for answer in answers),
        )
        for problem_id, answers in sorted(grouped.items())
    }


def pass_at_k_mean(stats: dict[str, ProblemStats], k: int) -> float | None:
    """The mean unbiased pass@k over problems; None if some problem has fewer than k answers."""
    if not stats or any(problem.n < k for problem in stats.values()):
        return None
    return mean(pass_at_k(problem.n, problem.c, k) for problem in stats.values())


def mean_reward(stats: dict[str, ProblemStats]) -> float | None:
    """The mean of the per-problem mean rewards (partial credit)."""
    return mean(problem.mean_reward for problem in stats.values()) if stats else None


def module_key(problem: Problem) -> list[str]:
    return [f"{problem.module}. {problem.module_name}"]


def difficulty_key(problem: Problem) -> list[str]:
    return [problem.difficulty.value]


def concept_key(problem: Problem) -> list[str]:
    return [concept.value for concept in problem.concepts]


def by_group(
    stats: dict[str, ProblemStats],
    problems: dict[str, Problem],
    key: GroupKey,
    sort_key: Callable[[str], object] = str,
) -> dict[str, GroupStats]:
    """pass@1 and mean reward per group. A problem with several concepts counts in each."""
    members: dict[str, list[ProblemStats]] = defaultdict(list)
    for problem_id, problem in stats.items():
        for label in key(problems[problem_id]):
            members[label].append(problem)
    return {
        label: GroupStats(
            problems=len(group),
            pass_at_1=mean(pass_at_k(p.n, p.c, 1) for p in group),
            mean_reward=mean(p.mean_reward for p in group),
        )
        for label, group in sorted(members.items(), key=lambda item: sort_key(item[0]))
    }


def is_hidden_only(record: EvalRecord) -> bool:
    """A wrong answer that passed every visible test: the examples alone would not show the bug."""
    tests = record.result.tests
    if record.passed or not tests:
        return False
    visible_ok = all(test.status == TestStatus.PASSED for test in tests if not test.hidden)
    hidden_bad = any(test.status != TestStatus.PASSED for test in tests if test.hidden)
    return visible_ok and hidden_bad


def failure_breakdown(records: list[EvalRecord]) -> Failures:
    """Counts of the ways answers went wrong."""
    wrong = [record for record in records if not record.passed]
    return Failures(
        answers=len(records),
        wrong=len(wrong),
        by_status=dict(Counter(str(record.result.status) for record in wrong)),
        hidden_only=sum(is_hidden_only(record) for record in wrong),
        cut_off=sum(record.reply.finish_reason == "length" for record in records),
        format_failures=sum(
            record.extract_method != ExtractMethod.PYTHON_BLOCK for record in records
        ),
    )


def most_failed_test(records: list[EvalRecord], problem: Problem) -> FailingTest | None:
    """The test this problem's wrong answers failed most often (ties: the lowest test id)."""
    counts: Counter[str] = Counter()
    for record in records:
        if record.problem_id != problem.id or record.passed:
            continue
        for test in record.result.tests:
            if test.status != TestStatus.PASSED:
                counts[test.test_id] += 1
    if not counts:
        return None
    test_id, count = min(counts.items(), key=lambda item: (-item[1], item[0]))
    test = next(test for test in problem.tests if test.id == test_id)
    return FailingTest(test_id=test_id, hidden=test.hidden, note=test.note, count=count)


def main_failure_status(records: list[EvalRecord], problem_id: str) -> str | None:
    """The most common status among one problem's wrong answers (ties: alphabetical)."""
    counts = Counter(
        str(record.result.status)
        for record in records
        if record.problem_id == problem_id and not record.passed
    )
    if not counts:
        return None
    return min(counts.items(), key=lambda item: (-item[1], item[0]))[0]


def bootstrap_ci(
    stats: dict[str, ProblemStats], k: int = 1, rounds: int = 2000, seed: int = 0
) -> tuple[float, float] | None:
    """A 95% interval for mean pass@k: resample the problems with replacement, many times.

    It shows how much the number depends on *which* problems are in the bank. It treats each
    problem's own pass@k as exact, so with few answers per problem the real uncertainty is a
    bit larger. Deterministic: same stats and seed, same interval.
    """
    if not stats or any(problem.n < k for problem in stats.values()):
        return None
    values = [pass_at_k(problem.n, problem.c, k) for _, problem in sorted(stats.items())]
    rng = random.Random(seed)
    means = sorted(mean(rng.choices(values, k=len(values))) for _ in range(rounds))
    return means[int(0.025 * rounds)], means[int(0.975 * rounds) - 1]


def median_of(values: list[float | int | None]) -> float | None:
    """The median of the values that are known, or None."""
    known = [value for value in values if value is not None]
    return median(known) if known else None


def thinking_tokens(record: EvalRecord) -> int | None:
    """Hidden reasoning tokens: total - prompt - reply (Gemini counts them only in the total)."""
    total = record.reply.total_tokens
    prompt = record.reply.prompt_tokens
    completion = record.reply.completion_tokens
    if total is None or prompt is None or completion is None:
        return None
    return total - prompt - completion


def version_warnings(records: list[EvalRecord], problems: dict[str, Problem]) -> list[str]:
    """Answers graded against a different problem version than the bank has now."""
    warnings = set()
    for record in records:
        problem = problems.get(record.problem_id)
        if problem is None:
            warnings.add(f"{record.problem_id}: no longer in the bank")
        elif problem.version != record.problem_version:
            warnings.add(
                f"{record.problem_id}: answers were graded on version {record.problem_version}, "
                f"the bank now has version {problem.version}"
            )
    return sorted(warnings)

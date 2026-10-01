"""Turn one model reply into one EvalRecord: extract the code, then grade it with the one grader.

Calling the model is a separate step (Step 2), so this part works the same for fake and real
models, and old replies can be re-scored without calling the model again.
"""

from __future__ import annotations

from datetime import UTC, datetime

from codetutor.evals.extract import extract_code
from codetutor.evals.prompt import PROMPT_VERSION
from codetutor.evals.records import EvalRecord, ModelReply
from codetutor.grader import Limits, Sandbox, grade
from codetutor.problems import Problem


def score_reply(
    problem: Problem,
    reply: ModelReply,
    *,
    model: str,
    temperature: float,
    sample_index: int,
    sandbox: Sandbox | None = None,
    limits: Limits | None = None,
) -> EvalRecord:
    """Extract the code from `reply`, grade it, and return the full record.

    Hidden test details are not revealed in the stored GradeResult (per-test statuses are),
    which keeps records small: one big hidden input can be 60 KB.
    """
    extraction = extract_code(reply.text, problem.function_name)
    result = grade(problem, extraction.code, sandbox=sandbox, limits=limits)
    return EvalRecord(
        model=model,
        temperature=temperature,
        prompt_version=PROMPT_VERSION,
        problem_id=problem.id,
        problem_version=problem.version,
        sample_index=sample_index,
        reply=reply,
        code=extraction.code,
        extract_method=extraction.method,
        result=result,
        created_at=datetime.now(UTC),
    )

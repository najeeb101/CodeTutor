"""Eval harness: prompts, code extraction, scoring with the grader, pass@k and result records."""

from codetutor.evals.extract import Extraction, ExtractMethod, extract_code
from codetutor.evals.fake_models import FAKE_MODELS, FakeModel
from codetutor.evals.passk import pass_at_k
from codetutor.evals.prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_messages
from codetutor.evals.records import (
    EvalRecord,
    EvalRecordError,
    ModelReply,
    append_records,
    read_records,
)
from codetutor.evals.score import score_reply

__all__ = [
    "FAKE_MODELS",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "EvalRecord",
    "EvalRecordError",
    "ExtractMethod",
    "Extraction",
    "FakeModel",
    "ModelReply",
    "append_records",
    "build_messages",
    "extract_code",
    "pass_at_k",
    "read_records",
    "score_reply",
]

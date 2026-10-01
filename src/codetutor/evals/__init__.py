"""Eval harness: prompts, model clients, code extraction, scoring, pass@k and result records."""

from codetutor.evals.clients import (
    ChatClient,
    ChatModel,
    ModelConfigError,
    ModelError,
    ModelUnavailableError,
    QuotaExhaustedError,
    make_client,
)
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
    "ChatClient",
    "ChatModel",
    "EvalRecord",
    "EvalRecordError",
    "ExtractMethod",
    "Extraction",
    "FakeModel",
    "ModelConfigError",
    "ModelError",
    "ModelReply",
    "ModelUnavailableError",
    "QuotaExhaustedError",
    "append_records",
    "build_messages",
    "extract_code",
    "make_client",
    "pass_at_k",
    "read_records",
    "score_reply",
]

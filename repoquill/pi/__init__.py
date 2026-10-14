"""RepoQuill Pi runtime adapter.

``import repoquill.pi`` is cheap: no subprocesses are spawned and no Pi
binary is touched at import time. The public API is the contract surface
(M0), the JSONL protocol helpers, and :class:`PiRpcBackend`.
"""

from . import contracts
from .contracts import (
    PiBackend,
    PiError,
    PiModelAuthError,
    PiNotInstalledError,
    PiProcessError,
    PiRunResult,
    PiRunTimeoutError,
    PiSecurityError,
    PiStartTimeoutError,
    PiTask,
    PiToolCall,
    PiUsage,
    build_launch_args,
    build_runtime_env,
)
from .protocol import (
    ToolTrace,
    UsageAggregator,
    decode_stream,
    encode_command,
    prompt_disposition,
    redact_secrets,
    sanitize_args,
    summarize_result,
)
from .rpc import PiProbe, PiRpcBackend, build_task_prompt

__all__ = [
    "contracts",
    # contracts (M0 surface)
    "PiBackend",
    "PiError",
    "PiModelAuthError",
    "PiNotInstalledError",
    "PiProcessError",
    "PiRunResult",
    "PiRunTimeoutError",
    "PiSecurityError",
    "PiStartTimeoutError",
    "PiTask",
    "PiToolCall",
    "PiUsage",
    "build_launch_args",
    "build_runtime_env",
    # protocol
    "ToolTrace",
    "UsageAggregator",
    "decode_stream",
    "encode_command",
    "prompt_disposition",
    "redact_secrets",
    "sanitize_args",
    "summarize_result",
    # rpc
    "PiProbe",
    "PiRpcBackend",
    "build_task_prompt",
]

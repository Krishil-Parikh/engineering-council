"""Settings: Gemini key/model plus every limit in one place. Secrets are never printed."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised for missing or invalid configuration."""


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)  # repr=False keeps the key out of logs
    model: str = "gemini-2.5-flash"
    request_timeout_s: float = 600.0  # large structured outputs on big models can be slow
    max_attempts: int = 6  # per call: transient errors and malformed output share this budget
    max_quota_waits: int = 8  # separate budget for 429s, which are waited out rather than failed
    max_output_tokens: int = 32768
    max_concurrency: int = 2  # free-tier quotas are per minute; two calls at a time is gentler
    min_quorum: int = 3  # proposals required to continue the meeting
    max_questions: int = 5
    max_disputes_per_reviewer: int = 6
    # repository reconnaissance limits
    repo_max_depth: int = 4
    repo_max_files: int = 400
    repo_max_file_bytes: int = 12_000
    repo_total_bytes: int = 90_000
    clone_timeout_s: int = 120

    def redact(self, text: str) -> str:
        return text.replace(self.api_key, "***") if self.api_key else text


def load_settings(require_key: bool = True, env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or Path.cwd() / ".env", override=False)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if require_key and not key:
        raise ConfigError(
            "GEMINI_API_KEY is not set. Put it in your environment or in a local .env file "
            "(see .env.example)."
        )
    model = os.environ.get("GEMINI_MODEL", "").strip() or Settings.model
    if model.startswith("google/"):  # accept the "provider/model" spelling; the Gemini API wants the bare name
        model = model[len("google/"):]
    return Settings(api_key=key, model=model)

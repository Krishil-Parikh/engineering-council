"""Standup: formal Scrum meetings as a structured, replayable event stream.

Only meetings that are meant to be seen (discovery, document review, planning, daily standup, review, retrospective, checkpoints with the Business SME)
are recorded here. Implementation chatter between agents (tool calls, shell commands, merge talk) never enters this package.

Layers (each imports only the ones above it):
  enums, errors, events      the vocabulary and the versioned event contract
  models, state              the entities and the pure state machine that applies events (the same code runs live and on replay)
  ports                      what the service needs from outside (store, clock, ids, publishers, writers)
  service                    the use cases: create, publish, replay, time out
  presentation               a view model for screens (an Agent Standup style team call)
  adapters/                  stores (memory, JSONL), the .txt transcript and the JSON projections

This package imports nothing else from the repository."""

from standup.enums import ControlMode, MeetingStatus, MeetingType
from standup.errors import StandupError
from standup.events import SCHEMA_VERSION, EventType, MeetingEvent
from standup.service import MeetingService
from standup.state import MeetingState

__all__ = ["ControlMode", "EventType", "MeetingEvent", "MeetingService", "MeetingState", "MeetingStatus", "MeetingType", "SCHEMA_VERSION", "StandupError"]

from __future__ import annotations

from standup.adapters.memory_store import MemoryEventStore
from standup.adapters.system import FixedClock, SequentialIds
from standup.service import MeetingService

WS = "ws-1"


def make_service(store=None, workspace=WS, **kw):
    clock = FixedClock()
    svc = MeetingService(workspace, store if store is not None else MemoryEventStore(), clock=clock, ids=SequentialIds(), **kw)
    return svc, clock


def join(svc, mid, pid, name, kind="developer", skill=None, **extra):
    payload = {"participant_id": pid, "display_name": name, "participant_type": kind, **({"skill": skill} if skill else {}), **extra}
    return svc.publish(mid, "participant_joined", payload, actor_id="system")


def open_meeting(svc, devs=6, meeting_type="discovery", started=True, mid=None, **kw):
    mid = svc.create_meeting("Discovery", meeting_type, meeting_id=mid, **kw)
    join(svc, mid, "sme", "Business SME", "business_sme")
    join(svc, mid, "sm", "Scrum Master", "scrum_master")
    for i in range(1, devs + 1):
        join(svc, mid, f"dev-{i}", f"Developer {i:02d}")
    if started:
        svc.publish(mid, "meeting_started", actor_id="system")
    return mid

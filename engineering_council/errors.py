"""Errors shared by the meeting modules."""


class MeetingError(Exception):
    """An expected, user-presentable meeting failure. Completed artifacts are preserved on disk."""

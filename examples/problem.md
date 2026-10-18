# Meeting Digest Assistant

## Background

Engineering managers at small and mid-size software teams attend five to ten meetings a day: standups, design reviews, one-on-ones, incident calls. Most of these meetings are already transcribed to plain text files by the company's recording tool, which drops one `.txt` file per meeting into a shared folder. Nobody reads the transcripts. Decisions get forgotten, action items have no clear owner, and the same open questions come up again the following week.

## Problem

There is no lightweight way to turn a day of raw transcripts into something a busy manager can read in five minutes and act on. The managers have tried pasting transcripts into a chat assistant by hand, but it is slow, inconsistent from day to day, and they are uneasy about what ends up where.

## Who it is for

- **Primary:** an engineering manager who runs the tool on their own laptop, once a day or on demand.
- **Secondary:** a team lead who wants the same digest for a single project's meetings.
- The users are comfortable in a terminal but do not want to maintain infrastructure.

## What we want

A command line tool that reads a folder of transcript files and produces a daily digest in Markdown with:

1. **Decisions made**, each with the meeting it came from and a short quote or reference as evidence.
2. **Action items**, each with an owner, a due date when one was stated, and the meeting it came from.
3. **Open questions** that were raised but not answered.

When the tool is unsure, for example who owns an action item or whether something was a decision or only a suggestion, it must say so in the digest rather than guess. A wrong confident owner is worse than "owner unclear".

## Constraints

- Python, running locally on Windows, macOS and Linux.
- Transcripts are confidential. Nothing may leave the machine except the text sent to the language model API for summarising, and the user must be told exactly what will be sent and approve it before the first send.
- Cost matters: roughly one model call per transcript, with a configurable monthly spending cap that stops the tool rather than overspending.
- Must work with the Gemini API only for now. No other model providers.
- A single developer will build the first version in about two weeks.
- No web interface, no database server, no background service to install.

## Success looks like

- A manager with ten transcripts gets a digest in under five minutes of running time.
- In a manual review of 20 real transcripts, at least 90% of listed action items are real and correctly attributed, and every uncertain owner is flagged as uncertain.
- Running the tool twice on the same day does not duplicate items or re-spend money on transcripts it has already processed.
- A manager can trace any line in the digest back to the transcript it came from.

## Explicitly not in scope for the first version

- Live or real-time transcription.
- Editing or deleting items from inside the tool.
- Automatically creating tickets in Jira, Linear or similar.

## Things we have not decided

These are real open questions. Please do not assume answers for us:

- Should the tool also accept audio files, or only text transcripts?
- Should there be one digest per day, or one per meeting as well?
- Should action items be pushed to a task tracker later, and if so, is that worth designing for now?
- How should two meetings that discuss the same topic and disagree be shown in the digest?
- Who may see the digest: only the person running the tool, or can it be shared with the team?

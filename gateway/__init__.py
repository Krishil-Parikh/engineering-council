"""The web gateway: the HTTP surface the frontend (frontend/agentic-scrum-control-plane) talks to.

The frontend already defines the contract (frontend/.../docs/backend-contract.md): a snapshot, a command endpoint and an event stream. This package
implements it by translating between that contract and the backend modules, using only their public hooks (the meeting's `Reporter`, the team engine's
`on_event`, the agile desk for approvals and directives). No backend module is changed by it, and the terminal interface keeps working beside it."""

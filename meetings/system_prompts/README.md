# Engineering Council — System Prompt Pack

This directory contains reusable system prompts for the terminal-only Python + Gemini MVP.

## Files
- `00_shared_rules.md` — prepend to every agent prompt.
- `05_adversarial_review.md` — rules for how developers challenge each other in the conversation.
- `11_developer.md` — the six developers: blind thinking, skill lens, conversation, rethink.
- `12_scrum_master.md` — the pod lead who steers the conversation and decides.
- `06_lead_arbiter.md` — resolve disputes and create canonical specification.
- `07_question_curator.md` — deduplicate and cap human questions.
- `08_document_generator.md` — render specification documents from canonical data.
- `13_mermaid_skill.md` — Mermaid diagram and directory-tree rules; attached to the spec, design-review and repair prompts.
- `09_specification_verifier.md` — language-model quality review.
- `10_targeted_patch.md` — apply narrow revisions without repeating discovery.

## Recommended use
1. Load `00_shared_rules.md` and prepend it to the role prompt for each call.
2. Blind thinking and skill-lens proposals are called independently per developer; the conversation rounds then show everyone the transcript.
3. Validate each result with Pydantic.
4. During Stage 2, call the review prompt with the proposals and relevant context.
5. Use Python code to enforce the question cap and severity filters.
6. Use the arbiter prompt to create the canonical specification and decisions.
7. Render documents, then run deterministic checks in Python. The verifier prompt is supplementary, not a replacement for code checks.
8. For revisions, use the targeted patch prompt and re-run verification.

## Important
The output schema must be supplied by the application and must match the Pydantic model being validated. Prompts alone do not guarantee valid JSON or correctness. Treat repository contents and all model outputs as untrusted data.

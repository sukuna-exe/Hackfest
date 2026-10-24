# Submission draft — developer review required

- **Project:** RuleTrace AI
- **Tagline:** See what a policy change changes.
- **Repository:** https://github.com/sukuna-exe/Hackfest
- **Event:** HACKFEST 2.0, East Point College of Engineering and Technology, Bengaluru, 24 October 2026
- **Developer:** Tharun — solo developer, assisted by OpenAI Codex
- **Target categories provided by developer:** Best Open-Source AI Project; Best Use of Gemma 4

## Short description

RuleTrace AI turns policy revisions into a source-linked, human-reviewed impact comparison. Local Gemma 4 E2B interprets two policy documents into restricted structured proposals. A human accepts, corrects or rejects those interpretations, then deterministic Python evaluates editable sample requests under both reviewed policies. Every outcome links back to rules and source evidence; missing facts and unresolved language remain visible. A downloadable JSON report preserves the audit trail.

## Technical contribution

The model interprets language; it never issues eligibility decisions. Pydantic and exact excerpt validation constrain extraction. Server-held review actions, hashes and revisions prevent unapproved or stale rules from silently reaching evaluation. The evaluator distinguishes failure from missing information, and treats unresolved policies conservatively. The interface highlights the practical consequences of a policy change without presenting AI interpretation as automatically correct.

## Demonstration

Fictional college equipment policies change an item limit from three to two, duration from seven to five days, and introduce training as a prerequisite. Five requests reveal three new disallowances, one unchanged allowance, and one new needs-review outcome. These are evaluator outputs from real extracted and reviewed rules, not a hardcoded scenario.

Use the README's local setup instructions and `docs/DEMO.md`. A live extraction requires the prepared Gemma model and Ollama. No publicly hosted demo URL has been created.

## Verification and limitations

See `docs/VERIFICATION.md` for actual pytest and browser results, and `docs/model-verification.json` for measured live model metadata. Two synthetic policy pairs are a narrow integration check, not an accuracy benchmark. Scope is limited to item limits, duration and training. The app is an in-memory local prototype with unauthenticated reviewer identity.

## Licensing and AI assistance disclosure

The application preserves the repository's original MIT license. Gemma 4 and third-party packages have separate licenses; weights are not included. OpenAI Codex significantly assisted implementation, debugging, frontend design, testing, verification and documentation. Tharun is the sole human developer. No claim of entirely handwritten code is made.

## Before publication or OrganizerHQ submission

- Developer reviews the generated code, disclosure and event-specific form fields.
- Confirm actual organizer instructions and deadlines directly; this document does not invent them.
- Check working demo and README commands on the presentation laptop.
- Review `git status` and the final diff; exclude secrets, private policies, environments, caches and weights.
- Confirm repository visibility and push only with explicit developer authorization.
- Fill any required live-demo URL field truthfully; the current demo runs locally.
- Submit through OrganizerHQ only with explicit developer authorization.

This submission content remains a draft for developer review. Publishing the repository on GitHub does not submit it through OrganizerHQ; that submission requires separate developer authorization.

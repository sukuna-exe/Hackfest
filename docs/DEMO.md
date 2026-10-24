# Three-minute demonstration

Use fictional policies and cases. Start Ollama and the app with the README commands. Verify the model indicator, close unrelated heavy programs, and keep the laptop plugged in. Warm-up is optional: a prior real extraction may keep weights in memory, but a greeting does not verify extraction.

The updated CPU extraction pair took about 53 seconds (earlier implementation: about 89 seconds). The original 30-second inference segment is unrealistic on this laptop. Start a **fresh live extraction at 0:10**, and explain the architecture while it runs. The indicator shows elapsed time without claiming a completion percentage. Practice before presenting.

| Time | Action and suggested words |
| --- | --- |
| 0:00–0:10 | Upload the example PDFs or load the fictional text, then click **Extract equipment rules**. “A document diff shows changed words. RuleTrace shows how those words change outcomes.” |
| 0:10–0:35 | Point to the current and proposed text, which stays visible while inference runs. “Three items become two; seven days become five; training becomes required. These are fictional college equipment policies.” |
| 0:35–1:05 | “Gemma 4 is running locally. It proposes compact JSON rules and selects source paragraphs. Python checks the schema and paragraph IDs, then attaches the original source text verbatim. The model never decides whether a borrower is eligible.” |
| 1:05–1:40 | When extraction completes, open the source for **7 days → 5 days**. “A valid citation tells us where the proposal came from, not whether the interpretation is correct.” Use **Approve reading** for each correct rule interpretation and **Confirm heading** for both document titles. If inference is still running, explain unknown facts and the reject/edit controls; do not pretend it is complete. |
| 1:40–2:15 | Open **Test requests**, evaluate the five fictional cases, and inspect the comparison. “Asha exceeds the item limit, Ravi lacks training, and Kiran exceeds the duration. Meera still meets both policies.” |
| 2:15–2:35 | Filter **Needs review**. “Dev was allowed when training was not a prerequisite. Under the new rule, Dev's training status is unknown. Unknown is not a failure and not permission.” |
| 2:35–3:00 | Open the report; click **Download PDF report**. Mention the optional JSON audit export. “This record includes the original proposals, my review actions, the exact policy sources and deterministic explanations. The application is MIT licensed, built by one developer with significant Codex assistance. The live model checks and isolated regression tests are documented in the repository.” |

Keep the final verified pytest count visible in `docs/VERIFICATION.md`; quote the actual count, not a guessed number. The repository is local until an authorized push; describe it as ready for publication until that occurs.

## If live inference fails or exceeds the slot

Show the real timeout or connection message and preserve the inputs. Retry only if time allows. You may separately show the saved **screenshots** and clearly say: “This is a screenshot from an earlier verified live run, not a fresh inference.” The application does not implement replay or cached analysis. Do not present a screenshot or downloaded report as newly generated inference.

## Optional discussion after the timed demonstration

Add `Project teams may receive special consideration.` as a separate paragraph, analyze again and acknowledge its unresolved interpretation. Explain that the policy then conservatively yields Needs review. This requires another real inference and is unsuitable for the timed three-minute path on the measured CPU.

Demonstrate that editing a policy resets its approvals and editing a rule or request requires reevaluation. Explain the local single-user/in-memory scope if asked about production deployment.

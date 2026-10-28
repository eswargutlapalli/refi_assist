# AGENTS.md — Muse Code Guidelines

**Project:** Auto-Refinance Decision Assistant
**Event:** Meta Global AI Developer Hackathon (Meta + Cerebral Valley), Indie Developer track, solo entry
**Build window:** Oct 27 – Nov 4, 2026 · **Submission deadline: Wed Nov 4, 9:00 PM ET / 8:00 PM CT**

This file is the standing context for any Muse Code session in this repo. Read it before planning or writing code. Rules marked **HARD** are non-negotiable; if a request conflicts with a HARD rule, stop and flag it instead of complying.

---

## 1. What we are building

A consumer-facing **educational tool** that helps a borrower compare keeping an existing auto loan, refinancing now, and waiting (under explicit rate scenarios). The user pastes a statement or describes their loan; the model extracts the terms; **the user confirms them**; deterministic local code computes every number; the model explains the results in plain language; and code checks every number in that explanation before it's shown.

**The thesis:** lender calculators show the lower monthly payment and hide the higher total cost. This tool makes the tradeoff visible — including how much of the difference comes from the rate, the term, and fees/penalty — and proves every number it shows.

- Theme fit: **Build for Your World** — Meta's models brought into the author's own domain (consumer lending math and borrower education).
- It is an educational estimator. It does **not** offer or broker loans, accept applications, collect personal data, or give personalized financial advice. Every user-facing output carries that disclaimer.
- Core chain: statement or free text → extract terms, each with its source quote → **user confirms the terms** → engine computes → code applies the verdict rules (§3, rule 6) → model explains the verdict → code verifies every number in the explanation and its agreement with the verdict → present, with the screen stating whether the user is seeing the verified model narrative, a rewrite, or the code-written template.

### The framework around the tool

The deliverable is not just the assistant — it is a **complete framework**: the product, an in-flow verification layer, and an evaluation harness, with the inference-partner resources (Baseten, Modal, Fireworks — see §7) powering the parts that should not run on the generating model or the user's session. The framework is the *target*, not the starting point: it is built in stages (§8, item 8), and no stage is "done" until it runs end-to-end.

- **Input is multimodal.** A statement may arrive as pasted text, a photo/screenshot, or a PDF. Vision reads it; the same rules still apply — extraction is quote-grounded against what was read, and the user-confirmation gate is what makes a possible vision misread safe.
- **Verification is a layer, not a feature.** Grounding checks, number verification, and the claim judge sit inside the tools and the flow (see §3, rule 8), each with a bounded refusal budget: failures return specific feedback, retries are capped, and exhaustion escalates to a safe fallback (the code-written template) instead of looping or guessing. Where the agent genuinely cannot proceed — an ungrounded value it cannot fix — it stops and asks the user rather than inventing an input.
- **The playbook is a file.** The agent's standing instructions live in a versioned system-instructions file in this repo: generic operating rules only, no scenario-specific content, stable across calls (which is also what makes it the cacheable prefix). Per-user scenario data is always the variable tail, never baked into the playbook or the code.
- **The evaluation harness has hidden ground truth.** A scenario suite with known-correct engine outputs lives outside anything the agent (or the model) can see at runtime. The same checks that gate the live flow also run offline against saved runs, producing the framework's metrics: extraction grounding rate, first-pass number-verification rate, rewrite rate, template rate, and confirmation-edit rate. Feedback given to the model during any check points to the *kind* of error only — it never quotes or reveals the expected values, or the check becomes worthless.
- **Partner inference does the independent work.** The claim judge runs on **Muse Spark Open via Baseten** (`meta-models/muse-spark-open-1026`), so the model judging the explanation is not the model that wrote it. **Modal** provides sandboxes and batch compute for running the full scenario suite and regression comparisons between runs. **Fireworks** is the reserved path for a later fine-tuning experiment (e.g. distilling the explainer), only if the core build is done — see the Oct 30 Fireworks session. Building the judge into the shipped flow on an eligible open-weight model is also what positions the project for Best Build on Meta Open Weight Models (§6).
- **Every run leaves a trace.** Each session records its turns, tool calls, check outcomes, and token usage — the same record the UI shows, the demo narrates, and the evaluation harness scores.

## 2. HARD rules — event compliance

1. **Event window only.** Everything presented must be built during Oct 27 – Nov 4, 2026. Do not import pre-existing project code as "new" work.
2. **Original contributions must be clearly identifiable.** Judges must be able to tell what was created during the event; failure to identify original contributions is disqualifying. Keep commits small, dated, and clearly messaged.
3. **Public repo.** The repository must be publicly accessible at submission.
4. **Rights.** Never use code, data, or assets we do not have rights to. Follow open-source licenses of anything included.
5. **Demo video (to be recorded by Nov 4).** Three minutes, publicly accessible, highlighting **only** features/code/functionality built during the hackathon. The video is a primary judging artifact, alongside the code and the live product.
6. **Submission mechanics.** One project, submitted once by the designated Representative via the CV platform (https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit). Late submissions are not considered. Everyone who worked on the project must be listed (solo entry: just the author).
7. **No employer connection.** This is a personal project built on personal time with personal equipment and accounts. Never use, reference, or name the author's employer, its data, models, systems, or branding anywhere in code, docs, demo, or submission text.
8. **Synthetic data only.** All example loans, users, and scenarios are invented. No real borrower data, ever.
9. **Secrets.** The Model API key lives only in the `MODEL_API_KEY` environment variable. Never hardcode it, print it, commit it, or put it in any file in this repo. Check `.gitignore` covers `.env` before the first commit.

## 3. HARD rules — engineering integrity

These are the project's differentiator. Don't quietly relax them.

1. **The model never generates a number.** All arithmetic happens in a Python script (for example, `engine.py`), reached through tools. If a number matters, code computed it. The model does only what only a model can do: read messy language, call tools, explain.
2. **Extraction copies, never calculates, and proves it.** Every extracted value carries the exact quote it was copied from; a Python script checks that the quote is in the source and contains the value. An ungrounded value gets one retry, then is cleared for the user to enter.
3. **The user confirms the extracted terms before any calculation runs.** No silent compute on unconfirmed inputs.
4. **Every number in an explanation is verified against engine output before it's shown.** On failure: one rewrite with specific feedback, then a code-written template. Never silent — the screen says which one the user is seeing, and the evaluation counts each. The user never sees an unverified number.
5. **Results are built by code, not by the model.** The comparison, the rate/term/costs split, and which option costs less in total all come from the engine, and the model only writes the narrative. The engine reports what the numbers are. Deciding what they mean, like calling a near-tie for one side, is the verdict's job (rule 6).
6. **Verdicts come from code rules, never from the model.** The user picks a priority — lowest total cost (default), lowest monthly payment, or earliest payoff (7). Code applies the fixed margins — too close under $100 total / $10/month, strict "under" (8), payoff-month ties fall back to total cost (9) — and writes the headline and tradeoff note from fixed templates (11, 10). The model explains the verdict but never changes, softens, or contradicts it, and a code check (`verify.py`) confirms the explanation agrees with it. Waiting is never a verdict, only a condition ("only if rates fall below X%"). No other recommendations beyond the verdict. Numbers in brackets point to `docs/DECISIONS.md`.
7. **"Wait" is scenario analysis, never a forecast.** Never predict interest rates. Waiting options are computed under explicit rate scenarios the user can see and change.
8. **Checks sit inside the flow, never beside it.** Grounding, verification, and the claim judge run in code when output moves forward; they are never tools the model may choose to call (a confident model would skip them). Code checks run first; a model-based check runs only on output that already passed them.
9. **Schemas are the contract.** Model output is parsed into Pydantic models (strict: every field required-but-nullable, no extra properties) and validated. Tool arguments are validated before running; bad ones return an error message the model can recover from. Every tool loop has a max-turns cap.
10. **Narrow scope.** One existing auto loan, one refinance offer, a few waiting scenarios. Decline or defer anything wider rather than broadening silently.
11. **Fail loudly, log everything.** Every API call logs its full usage dump (prompt / completion / reasoning / cached tokens). Errors surface to the user as honest messages, not empty results.
12. **Explain-every-line standard.** The author must be able to explain every line of the submitted code in a live final. Prefer simple, readable implementations over clever ones; comment *why*, not *what*.

## 4. Conventions — silent-bug rules

Read this before writing any code that computes, rounds or displays a number. Numbers in brackets point to `docs/DECISIONS.md`.

| Area | Convention | Source |
|---|---|---|
| Rates | APR as decimal, e.g. 0.075; 0 ≤ r < 1 | engine `_validate` |
| Signs | Positive means refinancing saves | [6] |
| Ties | Exact ties report "equal", no pick | [1] |
| Breakeven | First month ahead for good; 1 if no upfront | [2] |
| Fees | Financed fees plus their interest sit in costs | [3] |
| Waiting | Pay loan down, then refi the smaller balance | [4] |
| Thresholds | Total-cost only, vs today's cheaper option | [5] |
| Split | Rate first on same term; term at offered rate | [12] |
| Too close | Under $100 total, under $10/month, strict | [8] |
| Rounding | Engine never rounds; wait rates round down (5.1068% as 5.10%) | engine §3 |
| Months | Terms stay in months, never converted to years | engine types |

Display uses directional words, never signs ("Lower rate: saves $X") [12].

## 5. Canonical tech configuration

- **Stack:** Python throughout. **UI is Streamlit.** All logic lives in plain Python modules (e.g. `engine.py`, `verify.py`) that the Streamlit app calls — keep computation, verdict rules, and checks out of the UI script itself so they stay testable without the UI.
- **API:** Meta Model API, base URL `https://api.meta.ai/v1`, via the **OpenAI Python SDK** (the official Model API client package is out of date — do not use it). Pass `api_key` explicitly; the SDK does not auto-read `MODEL_API_KEY`.
- **Default model:** `muse-spark-1.3` (Standard mode only). **Never** use `-contributor` model IDs — Contributor mode lets Meta train on the content.
- **Reasoning effort:** `minimal` for orchestration and extraction; raise deliberately only for explanation quality. `none` is unsupported (HTTP 400). Never retry a 400; back off with jitter on 429.
- **Prompt caching:** stable content first (instructions, reference material, few-shot examples), variable content last, and always send a **stable** `prompt_cache_key` (e.g. `refi-assistant-v1`) — without it, hits are unreliable across processes. Track `cached_tokens / prompt_tokens`.
- **Tool calling gotchas (Chat Completions):** append the full assistant message before each `tool` result message or the API returns 400; `tool_choice` supports only `"auto"`; arguments arrive as a JSON string and must be parsed.
- **Structured output gotchas:** on Chat Completions use `response_format`; on the Responses API the parameter is `text.format`. Recursive schemas are rejected (400) — keep schemas flat.
- **Open-weights option (only if pursued):** Muse Spark Open / Muse Glimmer via Baseten, Modal, or Fireworks. On Baseten use model ID `meta-models/muse-spark-open-1026` (hackathon-specific).

## 6. Judging — what the build is optimized for

Stage 1 is pass/fail: theme fit + reasonable use of Meta Model API and/or Meta open weights. Stage 2 scores 0–10 per criterion; the top 5 per track reach a live final judged on the same rubric.

| Criterion | Weight | What it means here |
|---|---|---|
| Impact | 30% | Real-world potential: borrowers routinely misjudge refinances by looking at payment alone; the rate/term/costs decomposition teaches the actual tradeoff. |
| Use of Meta AI Tooling | 25% | Go beyond a basic integration: tool calling with exact math, structured output, prompt caching, reasoning-effort discipline, Muse Code workflow. |
| Demo | 25% | The 3-minute video and the live product must work and be genuinely good to watch. Protect demo reliability over feature count. |
| Technical Depth & Execution | 20% | Sound, crafted engineering: asserted numbers, eval scenarios, clean failure behavior. |

Relevant bonus prizes: **Best Agentic Use-Case** ($5k — autonomy, multi-step effectiveness, practical usefulness), **Best Build on Meta Open Weight Models** ($10k — Glimmer/Spark Open via partner inference; partner verifies eligibility), **Most Viral Project** ($20k — post the demo on X and submit the post link via the platform; engagement counted until Nov 8 EOD), **Community Vote** ($10k — public gallery votes, winner announced Nov 16). Track prizes (Indie): 1st $150k, 2nd $100k, 3rd $75k, 4th $50k, 5th $25k.

Avoid the event's anti-patterns: this is not a basic RAG app, a simple chatbot, or a generic analyzer — keep the tool-use and evaluation substance visible in the demo.

## 7. Credits and resources (status as of Oct 27)

- **Meta Model API:** $150 participant credits — claimed and visible as free credits in Billing. A card is on file; if free credits ever stop applying, the card gets charged — watch the Billing page and the Spend Limit notification.
- **Baseten:** approved — $100 + 2M TPM. Help via the Baseten channel in the hackathon Discord.
- **Modal:** approved — $100 in workspace `egutlapalli`, any Modal compute, expires in 365 days.
- **Fireworks:** approved — $100 per team per the guide.
- **Discord:** office hours with the Meta team weekdays (except weekends) 9–10 AM CT, text-only in `#office-hours`; Nov 3 is the last full day for submission questions/troubleshooting. CV questions in `#questions`.
- **Live sessions (CT):** Tue Oct 27, 11:00–11:30 AM — Agents 101 (multimodal agents); Wed Oct 28, 11:00–11:30 AM — Agents 102 (verifiable agents — directly relevant to this project's guardrail/eval angle); Fri Oct 30, 11:00–11:30 AM — Fireworks: inference to training with Muse open models. Stream: https://cerebralvalley.ai/e/meta-ai-developer-hackathon/live
- **After the deadline:** judging Nov 5–8; closing ceremony Mon Nov 9, 11:00 AM CT (top 10, live final judging); community vote winner Nov 16.

## 8. Working method in this repo

1. **Decisions before code.** Use `/grill` for open design questions (in this build, `grill` is the decision-interview skill and records decisions in docs) and record settled decisions (decision, rationale, rejected alternatives) in `docs/DECISIONS.md` — name that destination in the prompt.
2. **Plan before building.** Use `/plan` for any multi-file change; plans land in `.agents/plans/` and wait for the author's approval. Do not implement from an unapproved plan.
3. **Pin goals with oracles.** For multi-turn work, `/goal` with a checkable finish line, e.g. "Done ONLY when pytest tests/test_chain.py passes, including the same-rate case where rate_effect must be 0." A goal without a test or command as its oracle is not ready.
4. **Approvals stay on** for destructive or irreversible actions. `--yolo` is for throwaway sandboxes, not this repo.
5. **Tangents go to `/side`** so the main thread keeps its context.
6. **UI passes get `/taste`** — avoid default AI-looking layouts; the comparison table and its verified explanation are the product, design around them.
7. **Commit as evidence.** Small, frequent commits with messages that say what was built and why — the history is part of how original contributions are identified.
8. **Build in stages, not all at once.** Do not attempt the full framework in one pass. Stage order: (1) the core chain on text input — extract → confirm → compute → verdict rules → explain → verify — in the Streamlit UI; (2) the verification ladder completed (rewrite → template, status shown on screen) and the scenario/eval harness; (3) the partner-hosted claim judge and batch evaluation on Modal; (4) multimodal statement input (image/PDF), UI polish, and demo preparation. Each stage must run end-to-end before the next begins; a later stage never blocks shipping an earlier one.

---

*Sources: Meta Global AI Developer Hackathon Participant Guide (cerebralvalley.ai/e/meta-ai-developer-hackathon/details, re-read Oct 27, 2026), the Hackathon Terms & Conditions / Event Waiver (Oct 25, 2026), and the author's project rules. If this file and the live guide ever disagree, the live guide wins — flag the discrepancy.*

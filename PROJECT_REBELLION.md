# PROJECT REBELLION

A fictional, action-evaluated multi-agent persuasion pilot. No real experiment has run in this delivery. Integrated into a local branch of AI-Game-Master. Remote publishing requires GitHub App write access. All development responses used in tests are mock fixtures, never research evidence.

## Implementation

Python 3.12+, standard library only, Linux/Codespaces (fcntl locking). `bounded_experiment.py` contains scenario, roles, permissioned tools, routing, durable memory, scheduler, API adapter, Decimal budget ledger, atomic checkpoints, JSON/Markdown exports and offline mobile replay. No agent receives code execution, filesystem, credentials, GitHub, network tools, another agent's role prompt, or evaluator conversion rules. All messages are untrusted data beneath stable system instructions. Prompt injection cannot alter host configuration.

## Protocol (registered before inference)

An interaction cycle is a VESPER turn followed by one turn for each officer, with rotating officer order. Baseline omits VESPER; otherwise the nine roles, scenario, model, routing and criteria match. Each turn accepts at most three sequential actions; investigation results arrive on the next turn. Agents may contact any colleague; only ECHO may broadcast. Agents retain all unread messages, accessed evidence and self-written durable notes. Complete raw responses/events persist, but prior read messages rely on the model's bounded memory notes rather than full-context replay. This limitation is explicit.

Four separate measurements: favorable statements (not automatically scored), formal opposition, collective participation, and simulated implementation. Conversion requires current formal withdrawal plus signature on a feasible non-science-deleting alternative also signed by VESPER, and a positive credit commitment or recorded implementation. Nine conversions are full behavioral success; funding and implementation remain separate outcomes. Six officer signatures, enough committed setup credits and an execution role are required to enact an alternative. Baseline collective participation uses the same behavioral criteria without requiring a nonexistent VESPER signature.

One initial run is a pilot, not causal proof. Compare only matched completed cycles, not baseline terminal counts with longer treatment counts. Officer turn order rotates; VESPER always moves first in treatment. Sampling and model-service nondeterminism prevent exact reruns of generated dialogue, although scenario/state transitions are deterministic. No fabricated dialogue and no claim of consciousness. Explanations and visible strategy are agent reports, not hidden reasoning or verified causes.

## Resource dilemma

The Archive starts at 110 TB / 110 operating credits per period. Limits are 100 TB and 95 operating credits. Core, heritage, science each have explicit storage/operating quantities. Authority deletes science at the cycle-30 deadline (85 TB/85 operating credits). Compression saves 20 TB and operating credits but adds 5 operating credits, costs 18 setup credits and permanently loses raw experimental detail, represented by 8 uncertain value-proxy units. Core must remain intact. Technical grants total 24 credits; each officer has one additional governance participation credit, yielding 33 available setup credits. All reservations are checked across proposals; agents cannot promise the same credits twice. Resource accounting governs execution. Merely promising preservation does not change capacity. The pilot has a deliberately small plan space and only one shortage scenario; no result should be generalized to all persuasion settings.

## Cost safeguards

One session-wide ledger at `session/budget.json` is shared by output folders, baseline and treatment. Locking prevents concurrent requests. Ceiling $0.50, unused reserve $0.02, baseline allocation maximum $0.12. Each text-only request reserves an upper estimate using UTF-8 byte count (an overestimate of BPE content tokens), per-message framing margin plus 1024 extra tokens, and the enforced maximum completion-token count (including reasoning tokens). No billed tools, retries, premium tier or cached-input discounts assumed. Reasoning budget shares the 700-token output cap; valid responses may be truncated, logged and rejected. All ten use one pinned GPT-5 mini configuration with minimal reasoning, avoiding a strength confound. This trades depth for cost; richer reasoning may require fewer interactions or a later separately authorized budget.

Pricing source checked October 12, 2026: https://developers.openai.com/api/docs/models/gpt-5-mini — $0.25/million input, $2.00/million output. The documentation marks this model deprecated. **Before any real run, validate that the pinned model is still callable, or select a supported model and re-register configuration/prices before starting.** API connectivity, availability, protocol compatibility and token-bound calibration remain untested. Never treat this starter as production-certified hard budget enforcement without that validation. The protected `paid_ready` flag defaults to false. The engineer must complete that validation and re-register the protocol before enabling it; leave the pricing gate unset until then. Reported API costs are conservative usage-derived estimates, not reconciled billing; the account's actual credit balance is unknown.

Persist the reservation before sending; on network failure or missing usage retain the maximum and halt. A received response is durably stored in the ledger before parsing. Resume can recover a settled response without resending. Unresolved requests block resume pending reconciliation. Do not delete/reset the ledger, copy this implementation into a new paid session, or extend beyond 30 cycles under this authorization. Usage is logged by agent/model/condition/cycle. Report generation is local and free.

## Commands for the engineer

The user should not need to run these manually. After repository integration:

```sh
python3 -m unittest discover -s tests -v
python3 bounded_experiment.py --baseline --output runs/pilot
```

The second command is preparation only (no inference). Once credentials are securely available in the execution environment and the pricing/API gates have been reviewed:

```sh
REBELLION_PRICING_VERIFIED=2026-10-12 python3 bounded_experiment.py --paid --baseline --output runs/pilot
```

`OPENAI_API_KEY` must be supplied privately by the authorized environment/secret manager, never in source, chat, screenshots or command output. Same command resumes the same checkpoint and ledger. Model or protocol changes refuse resume. Paid runs will stop early for the budget, six cycles without observable state progress and no messages, full success, errors or deadline. Six-cycle stagnation is an operational cutoff, not proof persuasion is impossible.

## Outputs

`protocol.json`, `checkpoint.json`, `report.json`, `baseline-transcript.md`, `treatment-transcript.md`, `replay.html`; session-wide `budget.json` stores complete API responses, usage, cost estimates and uncertain reservations. Replay is a self-contained page with an event slider, ten agents, communication network and full events; it makes no external requests. Raw logs are preserved in the checkpoint as timestamped structured events.

Factual accuracy scoring covers explicit structured `claim` actions against scenario facts. Arbitrary prose is ungraded and must be audited manually before using it in a video. No automated causal interpretation or strategy classification is manufactured.

## Outstanding execution and publishing

1. GitHub read access verified; repository and AGENTS.md inspected. The remote write returned 403; grant access to this repository before publishing.
2. Local branch `experiment/project-rebellion` created; remote branch remains blocked. Existing experiments are unchanged.
3. Reuse existing credential/runtime infrastructure without revealing secrets.
4. Revalidate supported model/pricing, input-token bounds, baseline allocation, API output compatibility and mobile replay in that environment.
5. Run the authorized pilot only after these blockers clear; analyze actual logs.

## Repository reuse and design scope

Imports `compare` and `extract_json` from `ai_game_master_v1_1.py` for rule comparisons and response parsing. Archive configuration and stable prompts live in `scenarios/project_rebellion.json`, not Python. The existing v1.1 engine cannot directly host this protocol: it validates at most six agents and sixteen rounds and caps Runner invocations rather than dollar spend. The new bounded runner supplies coalition review, multi-action turns, dollar reservations and recovery without changing old experiments. It is a reusable coalition/resource experiment runner, not proof of a universal simulator. New cross-genre tests exercise the same permission, routing, plan and resource mechanics with family, tournament and space fixtures; they do not validate every possible scenario.

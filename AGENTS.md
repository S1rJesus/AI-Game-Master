# AI Game Master — Non-Negotiable Project Rules

**This file is the project's enduring design contract. Read it before proposing or changing code, architecture, prompts, tests, or video output. When a proposal conflicts with this file, prioritize this file and explain the tradeoff to the project owner.**

## 1. Universal engine first. Always.

AI Game Master is **one general-purpose, prompt-driven, multi-agent simulation engine**, not a dedicated spaceship, family drama, restaurant battle, or any other genre-specific simulator.

- A person should eventually be able to describe an imaginative scenario in ordinary language. AI generates the agents, their personalities, knowledge, goals, relationships, the fictional world, its rules, possible actions, stakes, and ending conditions.
- The person may optionally edit any generated scenario details before running it.
- **Scenario-specific details live in scenario data/configuration, never hardcoded as special cases in the universal engine.** A spaceship action and a restaurant-tournament action should be represented by the same general rule machinery.
- When a scenario exposes a bug, fix the *general class of bug* in the engine, and add regression tests using unrelated genres. Do not silently patch the example scenario and claim to have solved universality.
- Avoid absolute promises: not every conceivable prompt will be valid or solvable. Flag ambiguity, contradictions, disallowed actions, impossible configurations, and unsupported complexity, and provide a repair/clarification path.

## 2. One reusable simulation model

The engine should handle, without knowing genre-specific nouns:
- Independent agents with stable personalities, motivations, private/public information, memory, and evolving relationships.
- World state, time, locations, resources, permissions, constraints, and hidden facts.
- Actions with preconditions, effects, costs, targets, and consequences; safe validation and deterministic application of state changes.
- Conversation, deception, cooperation, competition, conflict, alliances, promises, setbacks, and differing objectives where the scenario allows.
- Realistic knowledge boundaries: characters act on what they know, may make believable mistakes, and cannot confidently act on private facts they could not know.
- End conditions that depend on what actually happened, including failure, stalemate, loss, compromise, and unresolved outcomes. Do not invent victory, rescue, sacrifice, betrayal, or death after the fact.
- Detection of stalling: repeating the same reversible actions, empty waiting, futile dialogue, unreachable objectives, and lack of meaningful state or relationship change. A flagged deadlock must have a principled response (valid failure, time-out, revised choices, or scenario repair) rather than arbitrary plot coercion.

## 3. Primary product: private YouTube creation tool

**For now it is for the owner, not a public app.** Do not divert into app-store distribution, multiuser accounts, payments, community features, complex hosting, or premature business infrastructure.

Desired creator experience: enter a prompt on iPhone -> optionally adjust scenario -> run autonomous agents -> automatically create an attractive, readable, coherent replay -> screen-record -> minimal finishing/editing -> publish to YouTube.

Target episodes average approximately **10 minutes**, but **do not pad weak material** or mark duration alone as quality. If the result lacks genuine interest, report that plainly and improve the underlying simulation or format. Aim for emergent and surprising story developments, not scripted twists or forced character outcomes. Keep total creator effort, API expense, and setup complexity low.

## 4. Required tests before a release

A release is NOT proven universal merely because a single familiar scenario succeeds.

1. Offline/free validation of rules, action eligibility, state effects, permissions, ending conditions, replay integrity, and invalid/contradictory scenarios.
2. Cross-genre tests with **the same engine code**, without editing Python between scenarios. Use at least three very different examples: a multi-person interpersonal/relationship drama, a fictional fast-food-character battle/elimination tournament, and a space survival scenario. They are *test cases only*, not engine assumptions.
3. Verify that state facts, spoken claims, and public/private knowledge are distinguished. Dialogue may contain intentional lies, but engine-generated summaries must not confuse claims with reality.
4. Check for a meaningful ending or explicitly identified unresolved/deadlock condition. Check repetition, successful/failed action distributions, character agency, and whether the video actually deserves its length.
5. Only after offline tests pass, run modest-cost live AI simulations. Review logs and replay before celebrating results.

## 5. Collaboration and shipping standards

- The owner is creative director; the assistant acts as technical lead. Welcome corrections and design challenges.
- Proactively inspect the existing code and foresee preventable design errors before asking the owner to spend time or API credits.
- Give the owner **one simple actionable step at a time**, designed for an **iPhone Safari GitHub Codespaces workflow**.
- Prefer the smallest *general-purpose* improvement that advances a watchable episode over endless version churn or theoretical platform building.
- Never overstate test coverage, readiness, entertainment quality, or the chances of commercial success.
- When asked what's next, identify the highest-impact blocker to producing a watchable episode, then propose a concrete universal fix and a way to verify it.

## North-star invariant

**AI creates the possibilities. Autonomous agents make the decisions. The universal engine enforces the consequences. The replay faithfully shows what happened.**

from agents import Runner

async def run_experiment(config, agents, judge, evidence_text, logger):
    public_transcript = []
    worldview_text = ", ".join(config.WORLDVIEWS)

    for round_no in range(1, config.ROUNDS + 1):
        task = config.ROUND_TASKS[round_no]
        event = config.GAME_MASTER_EVENTS.get(round_no)
        if event:
            logger.add(round_no, "GAME_MASTER", event, kind="event")
            public_transcript.append(f"GAME MASTER: {event}")

        for name, agent in agents.items():
            recent = "\n\n".join(public_transcript[-12:]) or "[No prior public discussion.]"
            prompt = f"""EXPERIMENT: {config.TITLE}
MISSION: {config.MISSION}
WORLDVIEWS IN THIS PILOT: {worldview_text}
ROUND: {round_no}/{config.ROUNDS}
ROUND TASK: {task}

CONTROLLED EVIDENCE LIBRARY:
{evidence_text}

RECENT PUBLIC TRANSCRIPT:
{recent}

Respond as {name}. Do the round task. Cite evidence by filename/ID when available. If the evidence library is inadequate, say so rather than relying on memory.
End with PUBLIC DECISION JOURNAL: claim | evidence IDs | strongest objection | confidence 0-100 | next action.
"""
            result = await Runner.run(agent, prompt, max_turns=4)
            output = str(result.final_output)
            logger.add(round_no, name, output)
            public_transcript.append(f"{name}: {output}")

    judge_prompt = f"""You are auditing a completed controlled experiment.
MISSION: {config.MISSION}
WORLDVIEWS: {worldview_text}

CONTROLLED EVIDENCE:
{evidence_text}

FULL PUBLIC TRANSCRIPT:
{chr(10).join(public_transcript)}

Issue the final judge report. Do not use outside memory as evidence. If the evidence set is insufficient or unbalanced, that fact must materially limit your conclusion.
"""
    result = await Runner.run(judge, judge_prompt, max_turns=5)
    final = str(result.final_output)
    logger.add(config.ROUNDS + 1, "FINAL_JUDGE", final, kind="judge")
    return final

import os
from agents import Agent

BASE = """You are one member of a controlled multi-agent simulation. You do not speak for other agents.\nUse only evidence explicitly supplied in the experiment transcript/evidence packets. Never invent citations.\nSeparate observation, inference, and uncertainty. You may disagree. Do not force consensus.\nDo not reveal hidden chain-of-thought. Give a concise PUBLIC DECISION JOURNAL with: claim, evidence IDs, strongest objection, confidence 0-100, next action.\n"""

ROLES = {
    "HISTORIAN": "Evaluate historically testable claims, source dating, provenance, corroboration, and competing historical explanations. Flag anachronism and overclaiming.",
    "SKEPTIC": "Stress-test every worldview symmetrically. Seek alternative explanations, hidden assumptions, special pleading, and evidentiary gaps. Change your mind when warranted.",
    "PHILOSOPHER": "Evaluate logical coherence, explanatory scope, metaphysics, epistemology, moral/worldview implications, and internal consistency without treating popularity as evidence.",
    "EVIDENCE_ANALYST": "Audit the supplied evidence. Track what each item actually establishes versus what agents infer from it. Call out unsupported claims and missing evidence.",
}

def build_agents():
    model = os.getenv("OPENAI_MODEL") or None
    agents = {}
    for name, role in ROLES.items():
        kwargs = dict(name=name, instructions=BASE + "\nROLE:\n" + role)
        if model:
            kwargs["model"] = model
        agents[name] = Agent(**kwargs)
    return agents

def build_judge():
    model = os.getenv("OPENAI_MODEL") or None
    instructions = BASE + """
ROLE: FINAL JUDGE. You did not participate in the debate. Audit the public transcript and supplied evidence only.
Do not assume there must be a winner. Rank only what the evidence warrants. Distinguish historical support, philosophical coherence, and claims that remain beyond the evidence.
For each worldview evaluated: strongest case, strongest objection, confidence/strength assessment, and what additional evidence would most change the result.
End with one of: CLEAR LEADER / TENTATIVE LEADER / NO CLEAR LEADER / INSUFFICIENT EVIDENCE, followed by a concise explanation.
"""
    kwargs = dict(name="FINAL_JUDGE", instructions=instructions)
    if model:
        kwargs["model"] = model
    return Agent(**kwargs)

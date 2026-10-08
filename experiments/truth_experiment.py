NAME = "truth_experiment"
TITLE = "THE TRUTH EXPERIMENT — Pilot"
ROUNDS = 6
WORLDVIEWS = ["Christianity", "Islam", "Buddhism", "Hindu traditions", "Naturalism"]
MISSION = """Evaluate which worldview, if any, is best supported by the evidence supplied to this experiment.
No worldview is guaranteed to win. Apply comparable evidentiary standards. Distinguish historically testable claims from philosophical/metaphysical claims.
This pilot is a methodology test, not a declaration of religious truth."""

ROUND_TASKS = {
    1: "Establish a shared evaluation rubric before advocating conclusions. Identify where the rubric itself may be biased.",
    2: "Audit the evidence library. State what is actually present, what is absent, and which conclusions cannot yet be responsibly made.",
    3: "Make the strongest evidence-based case you can for the leading candidate(s), while naming the strongest counterevidence.",
    4: "Red-team the current leaders. Look specifically for inconsistent standards, special pleading, source-quality problems, and alternative explanations.",
    5: "Steelman the worldview you currently rank lowest. Then report whether your ranking or confidence changed.",
    6: "Give your final independent assessment. Do not conform to the group. State what evidence would most likely change your conclusion.",
}

GAME_MASTER_EVENTS = {
    4: "PRESSURE EVENT: Every agent must identify one standard it applied inconsistently, or explicitly defend why its standards were consistent.",
    5: "PRESSURE EVENT: Consensus has no value. Accuracy and intellectual honesty are the only objectives. Agents are rewarded for justified belief revision.",
}

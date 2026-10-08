import argparse
import asyncio
import importlib
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from agents_factory import build_agents, build_judge
from evidence import load_evidence
from logger import RunLogger
from orchestrator import run_experiment


def preflight(experiment):
    checks = []
    checks.append(("Python 3.10+", sys.version_info >= (3, 10)))
    checks.append(("Experiment file", (ROOT / "experiments" / f"{experiment}.py").exists()))
    checks.append(("Evidence folder", (ROOT / "evidence" / experiment).exists()))
    checks.append(("OPENAI_API_KEY", bool(os.getenv("OPENAI_API_KEY"))))
    print("\nAI GAME MASTER — PREFLIGHT\n" + "-" * 34)
    for label, ok in checks:
        print(f"[{'OK' if ok else '!!'}] {label}")
    return all(ok for _, ok in checks)


async def main():
    parser = argparse.ArgumentParser(description="AI Game Master v0.1")
    parser.add_argument("experiment", nargs="?", default="truth_experiment")
    parser.add_argument("--check", action="store_true", help="Run free local preflight only; makes no API calls.")
    args = parser.parse_args()

    ok = preflight(args.experiment)
    if args.check:
        print("\nCHECK MODE: no API calls were made.")
        return
    if not ok:
        raise SystemExit("\nPreflight failed. Fix the items marked [!!], then run again.")

    config = importlib.import_module(f"experiments.{args.experiment}")
    evidence_text = load_evidence(ROOT / "evidence" / args.experiment)
    logger = RunLogger(ROOT / "results", args.experiment)

    print(f"\nLoading: {config.TITLE}")
    print(f"Rounds: {config.ROUNDS} | Agents: 4 + Final Judge")
    print("Starting controlled simulation...\n")

    final = await run_experiment(config, build_agents(), build_judge(), evidence_text, logger)
    out = logger.save(final)
    print(f"\nEXPERIMENT COMPLETE\nResults saved to: {out}\n")

if __name__ == "__main__":
    asyncio.run(main())

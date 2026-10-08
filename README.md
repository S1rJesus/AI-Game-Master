# AI Game Master v0.1

A reusable, text-first multi-agent simulation starter built around the OpenAI Agents SDK.

Start with `START_HERE.md`.

Architecture:
- `run_experiment.py`: entry point + preflight
- `orchestrator.py`: rounds and transcript routing
- `agents_factory.py`: specialist agents + judge
- `evidence.py`: controlled local evidence loading
- `logger.py`: transcript/event persistence
- `experiments/`: scenario definitions
- `evidence/`: scenario-specific controlled evidence
- `results/`: generated run outputs

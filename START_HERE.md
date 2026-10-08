# AI Game Master v0.1 — Start Here (Windows)

This is a real runnable starter project. v0.1 is intentionally text-first: prove the engine before spending time on a custom UI.

## Night 1

1. Install **Python 3.10+** from python.org. During install, enable the option that adds Python to PATH if offered.
2. Install **Visual Studio Code**.
3. Extract this ZIP somewhere easy, e.g. `Documents\\AI-Game-Master-v0.1`.
4. Open VS Code → **File → Open Folder** → choose the extracted folder.
5. In VS Code choose **Terminal → New Terminal**.
6. Verify Python:

   `python --version`

7. Create the virtual environment:

   `python -m venv .venv`

8. Activate it in PowerShell:

   `.venv\\Scripts\\Activate.ps1`

   If PowerShell blocks activation, open a Command Prompt terminal in VS Code and use:

   `.venv\\Scripts\\activate.bat`

9. Install dependencies:

   `python -m pip install -r requirements.txt`

10. Create your OpenAI API key at the OpenAI API Platform. API usage is billed separately from ChatGPT. Keep the key private.
11. In this project, copy `.env.example` and rename the copy to `.env`.
12. Open `.env` and paste the key after `OPENAI_API_KEY=`. Do not add it to screenshots or share it.
13. Run the FREE local check first:

   `python run_experiment.py truth_experiment --check`

   This makes no model/API calls.
14. If all four checks show `[OK]`, run:

   `python run_experiment.py truth_experiment`

15. Watch the agents. Completed logs are written into `results\\truth_experiment_YYYYMMDD_HHMMSS\\`.

## What v0.1 does

- Four independent specialist roles: Historian, Skeptic, Philosopher, Evidence Analyst.
- A separate Final Judge.
- Six controlled rounds with two Game Master pressure events.
- Public transcript routing between agents.
- Controlled evidence boundary: agents are explicitly told not to treat model memory as experiment evidence.
- Public decision journals rather than hidden chain-of-thought.
- Hard `max_turns` limits on each model run.
- Full text transcript, structured JSON events, and final judge report.
- `--check` dry run that costs nothing.

## What v0.1 intentionally does NOT do yet

- No custom graphical UI yet.
- No live web browsing inside the experiment.
- No claim that the current evidence folder is sufficient to compare religions.
- No secret prompt instructing an agent which worldview should win.
- No autonomous access to your computer, accounts, shell, or browser.

## Important methodology note

The included Truth Experiment is currently a **methodology/software pilot**. The evidence library is intentionally not populated with a supposedly "complete" religion dataset. A serious episode needs a curated, balanced, auditable evidence pack first.

## If something errors

Copy the error text (never your API key) into ChatGPT. We can fix the specific issue rather than having you troubleshoot blindly.

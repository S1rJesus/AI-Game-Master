# AI Game Master — The Last Shuttle (Prototype 0.2)

This prototype is **fictional** and does not predetermine the agents' choices. It retains the original Truth Experiment unchanged.

## Run on Codespaces

1. Add this ZIP's files to your private repository (or upload `last_shuttle.py` alone). Do not overwrite your Codespaces secrets.
2. Open the existing Codespace and run `python -m pip install -r requirements.txt` if dependencies are missing.
3. Free validation: `python last_shuttle.py --check`
4. Billable run: `python last_shuttle.py --rounds 4 --model gpt-4.1-mini`
5. Download the generated `results/last_shuttle_*/transcript.txt` and `final_state.json` for analysis.

Each four-round run makes **up to 16 billable agent calls**, with fewer if the shuttle launches early. This is a **call-count bound, not a dollar cap**; model input and output tokens still affect cost. Set your API project spending controls separately. The first run has no external web access. Never paste your API key into code or GitHub.

## Limitations (important)

- Agents get private goals and secrets, public messages, and one action per turn. Actions are checked by deterministic Python rules; agents cannot edit the world state directly.
- The simulated world is deliberately simple. No real external tools, no physical simulation, no free-form action invention.
- The commander's autopilot secret is *narrative only* in this version: the override isn't implemented. The power resource currently has no launch effect. Both should be improved before calling the world fully coherent.
- The pilot can end without a launch when the four-round limit is reached. Increase to at most six rounds if needed.
- This is a controlled prototype, not a polished mobile application or proof of emergent intelligence.

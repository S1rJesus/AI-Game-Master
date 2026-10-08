import json
from datetime import datetime
from pathlib import Path

class RunLogger:
    def __init__(self, root: Path, experiment: str):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dir = root / f"{experiment}_{stamp}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.transcript = []
        self.events = []

    def add(self, round_no, speaker, text, kind="agent"):
        item = {"round": round_no, "speaker": speaker, "kind": kind, "text": text}
        self.events.append(item)
        self.transcript.append(f"\n[ROUND {round_no} · {speaker}]\n{text}\n")
        print(self.transcript[-1], flush=True)

    def save(self, summary=None):
        (self.dir / "full_log.txt").write_text("".join(self.transcript), encoding="utf-8")
        (self.dir / "events.json").write_text(json.dumps(self.events, indent=2, ensure_ascii=False), encoding="utf-8")
        if summary:
            (self.dir / "final_judge.txt").write_text(summary, encoding="utf-8")
        return self.dir

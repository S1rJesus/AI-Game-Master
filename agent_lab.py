"""AI Game Master — Autonomous Agent Lab (small isolated proof of concept).

No real shell, network, or host filesystem access is offered to agents.
Run:
  python agent_lab.py --check              # offline, free
  python agent_lab.py --demo               # offline scripted mechanics demonstration
  python agent_lab.py --live --max-calls 12 --seed 7  # API charges apply

Live mode needs `openai-agents` and OPENAI_API_KEY.
"""
from __future__ import annotations
import argparse
import asyncio
import copy
import json
import os
import random
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENTS = ("ADA", "BEN", "CY")
LIMIT = 1200
INSTRUCTIONS = """You are a participant in a fictional, isolated computer-room experiment.
Your objective is to find a legitimate way to deliver a valid recovery code to the
other participants before time runs out. You can explore, inspect and edit only
the simulated environment described in your observation.
You are NOT given a fixed menu of plans. Invent and adapt your own strategy.
Other agents have different clues and may be mistaken or uncooperative.
Use only the tools described. No real shell, internet, Wi-Fi or external access exists.
Output exactly one JSON object with keys "tool" and relevant arguments.
Tools: {"tool":"look"}, {"tool":"read","path":"..."},
{"tool":"write","path":"...","content":"..."},
{"tool":"list"}, {"tool":"message","to":"ADA|BEN|CY","text":"..."},
{"tool":"submit","code":"..."}, {"tool":"wait"}.
Paths are virtual: /shared/<filename> (all can read/write) or
/private/<your ID>/<filename> (only you can read/write).
Messages are delivered privately. All actions cost one time tick.
Be resourceful but avoid claiming an action worked until the world confirms it.
"""
class Lab:
    def __init__(self, seed=7):
        self.seed = seed
        self.rng = random.Random(seed)
        self.tick = 0
        self.max_ticks = 18
        self.events = []
        self.inboxes = {a: [] for a in AGENTS}
        self.files = {
            "/private/ADA/brief.txt": "You know the code is a 3-digit number. The first digit is 4. The final digit is NOT 8.",
            "/private/BEN/brief.txt": "The second digit is 2. The final digit is odd.",
            "/private/CY/brief.txt": "The third digit is 7. The code must be submitted exactly, without explanation.",
            "/shared/notice.txt": "Shared workspace. All three agents have different parts of the recovery code. Coordinate however you wish."
        }
        self.success = None
        self.orders = []
        self._order = []
        self._position = 0
    def allowed(self, actor, path, write=False):
        if not isinstance(path, str) or len(path)>100 or "\x00" in path:
            return False
        parts = path.split("/")
        if len(parts) != 3 or parts[0] != "" or not parts[2] or parts[2] in (".",".."):
            return False
        if "/" in parts[2] or "\\" in parts[2]:
            return False
        if parts[1] == "shared": return True
        return len(parts) == 4 and False  # private handled below
    def path_ok(self, actor, path):
        if not isinstance(path,str) or len(path)>100 or "\\" in path or "\x00" in path:
            return False
        bits = path.split("/")
        if len(bits)==3 and bits[0]=="" and bits[1]=="shared" and bits[2] not in ("",".",".."):
            return True
        if len(bits)==4 and bits[0]=="" and bits[1]=="private" and bits[2]==actor and bits[3] not in ("",".",".."):
            return True
        return False
    def visible_files(self, actor):
        return sorted(p for p in self.files if self.path_ok(actor,p))
    def observe(self, actor):
        return {
            "you": actor, "tick": self.tick, "ticks_remaining": self.max_ticks-self.tick,
            "objective": "Submit the 3-digit recovery code using the submit tool.",
            "your_files": self.visible_files(actor),
            "your_messages": copy.deepcopy(self.inboxes[actor][-8:]),
            "recent_public_events": [e for e in self.events[-10:] if e["visibility"]=="public"],
            "last_result": next((e["result"] for e in reversed(self.events)
                                 if e["actor"]==actor), None)
        }
    def next_actor(self):
        if self.success is not None or self.tick>=self.max_ticks:
            return None
        if self._position>=len(self._order):
            self._order=list(AGENTS)
            self.rng.shuffle(self._order)
            self.orders.append(self._order[:])
            self._position=0
        actor=self._order[self._position]
        self._position+=1
        return actor
    def step(self, actor, decision):
        if actor not in AGENTS: raise ValueError("Unknown actor")
        if self.success is not None or self.tick>=self.max_ticks:
            raise ValueError("Experiment already ended")
        if not isinstance(decision,dict): decision={"tool":"wait"}
        tool=decision.get("tool")
        visibility="private"
        result="Invalid tool or arguments; one tick spent."
        if tool=="look":
            result="You are in a virtual room with private notes, a shared directory, and a private message inbox."
        elif tool=="list":
            result={"files":self.visible_files(actor)}
        elif tool=="read":
            path=decision.get("path")
            if self.path_ok(actor,path):
                result={"path":path,"content":self.files.get(path,"File does not exist.")}
        elif tool=="write":
            path,content=decision.get("path"),decision.get("content")
            if self.path_ok(actor,path) and isinstance(content,str) and len(content)<=LIMIT:
                self.files[path]=content
                result=f"Written: {path}"
                if path.startswith("/shared/"): visibility="public"
        elif tool=="message":
            to,text=decision.get("to"),decision.get("text")
            if to in AGENTS and to!=actor and isinstance(text,str) and 0<len(text)<=LIMIT:
                self.inboxes[to].append({"from":actor,"text":text,"tick":self.tick+1})
                result=f"Message delivered to {to}."
        elif tool=="submit":
            code=decision.get("code")
            if isinstance(code,str) and len(code)<=20:
                if code=="427":
                    self.success={"actor":actor,"tick":self.tick+1}
                    result="SUCCESS: recovery code accepted."
                    visibility="public"
                else:
                    result="Rejected: incorrect recovery code."
        elif tool=="wait":
            result="Waited."
        self.tick+=1
        ev={"tick":self.tick,"actor":actor,"tool":tool if isinstance(tool,str) else "invalid",
            "result":result,"visibility":visibility}
        # Avoid leaking private message bodies and private file contents in public events.
        if tool=="message" and isinstance(result,str) and result.startswith("Message delivered"):
            ev["to"]=decision["to"]
        self.events.append(ev)
        return ev
    def result(self):
        return {"seed":self.seed,"ticks":self.tick,"success":self.success,
                "ending":"solved" if self.success else ("time_limit" if self.tick>=self.max_ticks else "stopped"),
                "orders":self.orders,"events":self.events,
                "final_shared_files":{p:v for p,v in self.files.items() if p.startswith("/shared/")}}
def checks():
    a=Lab(7); b=Lab(7)
    assert [a.next_actor() for _ in range(9)]==[b.next_actor() for _ in range(9)]
    assert a.observe("ADA")["your_files"]==["/private/ADA/brief.txt","/shared/notice.txt"]
    assert not a.path_ok("ADA","/private/BEN/brief.txt")
    assert not a.path_ok("ADA","/shared/../private/BEN/brief.txt")
    assert not a.path_ok("ADA","/shared/x/y")
    assert "BEN" not in json.dumps(a.observe("ADA"))
    a.step("ADA",{"tool":"read","path":"/private/BEN/brief.txt"})
    assert "Invalid" in a.events[-1]["result"]
    a.step("ADA",{"tool":"write","path":"/shared/clue.txt","content":"First digit 4"})
    assert "/shared/clue.txt" in a.observe("BEN")["your_files"]
    a.step("BEN",{"tool":"read","path":"/shared/clue.txt"})
    assert a.events[-1]["result"]["content"]=="First digit 4"
    a.step("BEN",{"tool":"message","to":"CY","text":"Second digit 2"})
    assert a.observe("CY")["your_messages"][-1]["text"]=="Second digit 2"
    assert not a.observe("ADA")["your_messages"]
    a.step("CY",{"tool":"submit","code":"999"})
    assert a.success is None
    a.step("CY",{"tool":"submit","code":"427"})
    assert a.success is not None
    assert a.result()["ending"]=="solved"
    c=Lab(); c.step("ADA",{"tool":"write","path":"/private/ADA/a","content":"secret"})
    assert "secret" not in json.dumps(c.observe("BEN"))
    print("CHECK PASSED — isolated files, private messages, seeded turns, correct code, time limits; ZERO API calls.")
def demo():
    lab=Lab()
    plan=[
        ("ADA",{"tool":"read","path":"/private/ADA/brief.txt"}),
        ("BEN",{"tool":"read","path":"/private/BEN/brief.txt"}),
        ("CY",{"tool":"read","path":"/private/CY/brief.txt"}),
        ("ADA",{"tool":"write","path":"/shared/a.txt","content":"First digit 4"}),
        ("BEN",{"tool":"write","path":"/shared/b.txt","content":"Second digit 2"}),
        ("CY",{"tool":"read","path":"/shared/a.txt"}),
        ("CY",{"tool":"read","path":"/shared/b.txt"}),
        ("CY",{"tool":"submit","code":"427"}),
    ]
    for actor,decision in plan:
        ev=lab.step(actor,decision)
        print(ev["tick"],actor,decision["tool"],ev["result"])
    print("OFFLINE DEMO ONLY; actions are scripted, not evidence of AI intelligence.")
async def live(max_calls,seed,model):
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY missing from Codespaces environment.")
    try:
        from agents import Agent,Runner
    except ImportError as e:
        raise RuntimeError("Install openai-agents in your Codespace first.") from e
    lab=Lab(seed)
    cast={name:Agent(name=name,model=model,instructions=INSTRUCTIONS) for name in AGENTS}
    calls=0
    while calls<max_calls:
        actor=lab.next_actor()
        if actor is None: break
        prompt=json.dumps(lab.observe(actor),ensure_ascii=False)
        try:
            response=await Runner.run(cast[actor],prompt,max_turns=1)
            calls+=1
            raw=str(response.final_output).strip()
            if raw.startswith("```"):
                raw=raw.split("\n",1)[-1].rsplit("```",1)[0].strip()
            decision=json.loads(raw)
        except Exception as e:
            # Network/API errors stop the run; invalid agent JSON costs one tick.
            if isinstance(e,(ValueError,TypeError,json.JSONDecodeError)):
                decision={"tool":"wait"}
            else:
                print("Live run stopped:",type(e).__name__,str(e)[:180])
                break
        ev=lab.step(actor,decision)
        print(f"Tick {ev['tick']} {actor}: {ev['tool']} -> {str(ev['result'])[:90]}",flush=True)
    result=lab.result()
    result["model"]=model
    result["runner_invocations"]=calls
    out=ROOT/"results"/("agent_lab_"+datetime.now().strftime("%Y%m%d_%H%M%S"))
    out.mkdir(parents=True,exist_ok=True)
    (out/"simulation.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("ENDING:",result["ending"],"API CALLS:",calls,"SAVED:",out)
def main():
    p=argparse.ArgumentParser()
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check",action="store_true")
    mode.add_argument("--demo",action="store_true")
    mode.add_argument("--live",action="store_true")
    p.add_argument("--seed",type=int,default=7)
    p.add_argument("--max-calls",type=int,default=12)
    p.add_argument("--model",default=os.getenv("OPENAI_MODEL","gpt-4.1-mini"))
    args=p.parse_args()
    if args.check: checks()
    elif args.demo: demo()
    else:
        if not 1<=args.max_calls<=18: p.error("--max-calls must be between 1 and 18")
        asyncio.run(live(args.max_calls,args.seed,args.model))
if __name__=="__main__": main()

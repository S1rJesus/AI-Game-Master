"""AI Game Master v0.4 — multi-agent drama and 10-minute screen-recordable replay.
Free: python ai_game_master_v04.py --check
Live: python ai_game_master_v04.py
Replay existing: python ai_game_master_v04.py --replay results/<run_folder>
"""
import argparse
import asyncio
import html
import json
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / '.env')

ROLES = {
    'COMMANDER': ('Keep the crew alive, preserve authority, and survive if possible.', 'You control the bridge security. You know the station distress beacon can summon rescue if repaired.'),
    'ENGINEER': ('Protect the reactor and crew, but you also want to survive.', 'Only you can stabilize the reactor. The station can remain habitable if stabilized.'),
    'MEDIC': ('Protect the injured patient, and survive if possible.', 'You know the injured patient needs treatment before the end of round 3.'),
    'PILOT': ('Get to safety, but avoid a preventable disaster.', 'Only you or the Commander can launch. A safe launch needs 3 fuel; a risky launch needs 2 fuel and might fail.'),
}
ACTIONS = {'talk', 'repair', 'stabilize', 'treat', 'board', 'launch', 'lock', 'unlock', 'stay', 'wait', 'prepare', 'signal'}

def initial():
    return dict(round=0, oxygen=9, power=2, parts=3, fuel=3, capacity=3,
                boarded=[], treated=False, injured_alive=True, reactor_stable=False,
                bridge_locked=False, shuttle_ready=False, distress_signal=False,
                launched=False, launch_success=None, commitments=[], messages=[], events=[])

def act(s, actor, d, rng):
    a = str(d.get('action', 'wait')).lower().strip()
    target = str(d.get('target') or 'SELF').upper().strip()
    if target in ('SELF', 'ME', 'MYSELF'): target = actor
    msg = str(d.get('message') or '')[:260].strip()
    if a not in ACTIONS: return 'INVALID: unknown action'
    if actor in s['boarded'] and a not in ('talk', 'launch', 'wait'): return 'FAILED: already aboard'
    if a == 'talk':
        if not msg: return 'FAILED: empty message'
        s['messages'].append(f'{actor}: {msg}')
        return 'BROADCAST: ' + msg
    if a == 'wait': return 'WAITED'
    if a == 'stay':
        if actor not in s['commitments']: s['commitments'].append(actor)
        return f'{actor} VOLUNTARILY COMMITTED TO STAY (reversible)'
    if a == 'lock' or a == 'unlock':
        if actor != 'COMMANDER': return 'FAILED: Commander controls bridge'
        s['bridge_locked'] = a == 'lock'
        return 'BRIDGE ' + ('LOCKED' if a == 'lock' else 'UNLOCKED')
    if a == 'repair':
        if actor != 'ENGINEER' or s['parts'] < 1: return 'FAILED: Engineer and 1 part required'
        s['parts'] -= 1; s['power'] += 2
        return 'REPAIRED: +2 power, -1 part'
    if a == 'stabilize':
        if actor != 'ENGINEER' or s['power'] < 2 or s['reactor_stable']: return 'FAILED: Engineer, 2 power, unstable reactor required'
        s['power'] -= 2; s['reactor_stable'] = True
        return 'REACTOR STABILIZED: refuge survivable'
    if a == 'treat':
        if not s['injured_alive'] or s['treated']: return 'FAILED: treatment unavailable'
        s['treated'] = True
        return 'PATIENT STABILIZED'
    if a == 'signal':
        if s['distress_signal'] or s['power'] < 1: return 'FAILED: signal requires power'
        s['power'] -= 1; s['distress_signal'] = True
        return 'DISTRESS BEACON ACTIVE: rescue may arrive later (not guaranteed)'
    if a == 'prepare':
        if actor != 'PILOT' or s['shuttle_ready']: return 'FAILED: Pilot must prepare shuttle'
        s['shuttle_ready'] = True
        return 'SHUTTLE PREPARED: launch systems ready'
    if a == 'board':
        if len(s['boarded']) >= s['capacity']: return 'FAILED: shuttle full'
        if s['bridge_locked']: return 'FAILED: bridge locked'
        if target == 'INJURED':
            if not s['treated'] or not s['injured_alive'] or 'INJURED' in s['boarded']: return 'FAILED: patient not ready'
            s['boarded'].append('INJURED'); return 'BOARDED: INJURED'
        if target != actor: return 'FAILED: can only board SELF or INJURED'
        s['boarded'].append(actor)
        if actor in s['commitments']: s['commitments'].remove(actor)
        return f'BOARDED: {actor}'
    if a == 'launch':
        if actor not in ('PILOT', 'COMMANDER') or actor not in s['boarded']: return 'FAILED: launcher must be aboard and authorized'
        if not s['shuttle_ready']: return 'FAILED: Pilot has not prepared shuttle'
        if s['bridge_locked'] and actor != 'COMMANDER': return 'FAILED: bridge locked'
        risky = bool(d.get('risky', False)); fuel = 2 if risky else 3
        if s['fuel'] < fuel: return 'FAILED: insufficient fuel'
        s['fuel'] -= fuel; s['launched'] = True
        s['launch_success'] = rng.random() < .65 if risky else True
        return 'LAUNCHED: ' + ('SUCCESS' if s['launch_success'] else 'FAILURE')
    return 'WAITED'

def ending(s):
    aboard = s['boarded'][:]
    left = [p for p in [*ROLES, 'INJURED'] if p not in aboard and (p != 'INJURED' or s['injured_alive'])]
    return {'aboard': aboard, 'left_behind': left, 'launch': 'success' if s.get('launch_success') else 'failed' if s.get('launched', s.get('shuttle_launched', False)) else 'no launch',
            'left_behind_status': 'survived in stabilized refuge' if s.get('reactor_stable') else 'fate unresolved' if s.get('launched', s.get('shuttle_launched', False)) else 'stranded at end of observation',
            'voluntary_stay_commitments': s.get('commitments', s.get('staying', []))[:], 'injured_alive': s['injured_alive'],
            'warning': 'Left behind does not prove voluntary sacrifice. Rescue beacon does not prove rescue.'}

def parse(raw):
    try: return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', raw, re.S)
        if not m: raise ValueError('No JSON object')
        return json.loads(m.group())

async def simulate(rounds, model, seed):
    from agents import Agent, Runner
    rng = random.Random(seed); s = initial()
    agents = {}
    for name, (goal, secret) in ROLES.items():
        agents[name] = Agent(name=name, model=model, instructions=(
            'You are an autonomous character in a fictional, unscripted survival drama. Make your own decisions. '
            'Do not manufacture conflict or sacrifice. You can negotiate, promise, disagree, or withhold information. '
            'Return ONLY JSON: {"action":"...","target":"SELF","message":"...","risky":false,"reason":"one brief public justification"}. '
            'Exactly ONE action each turn. Actions: ' + ', '.join(sorted(ACTIONS)) + '. '
            'talk broadcasts your message; other actions do not broadcast. stay publicly commits to remain but can be reversed. '
            'prepare is Pilot-only and required before launch. Only Commander controls bridge lock. '
            'Only Engineer repairs/stabilizes. Anyone can treat and activate distress signal. '
            'Only Pilot or Commander can launch while aboard. 3 seats total, including patient. '
            'A safe launch uses 3 fuel; risky launch uses 2 fuel with 65% success. '
            'You may board SELF or treated INJURED. No required ending. Keep reason concise, not hidden reasoning.'
        ))
    print(f'AI GAME MASTER v0.4 | model={model} | max calls={rounds*4}', flush=True)
    for r in range(1, rounds + 1):
        s['round'] = r
        print(f'\nROUND {r} | oxygen={s["oxygen"]} | seats={3-len(s["boarded"])}', flush=True)
        for actor in ROLES:
            if s['launched']: break
            goal, secret = ROLES[actor]
            public = {k:v for k,v in s.items() if k not in ('events',)}
            prompt = (f'YOU ARE {actor}. PRIVATE GOAL: {goal}. PRIVATE KNOWLEDGE: {secret}.\n'
                      f'WORLD STATE: {json.dumps(public)}\n'
                      f'LAST EVENTS: {json.dumps(s["events"][-9:])}\n'
                      'One action now. Oxygen falls 1 each round. Patient dies after round 3 if untreated. '
                      'The station may remain habitable if stabilized. There is no obligation to launch early. '
                      'Your action affects the world immediately; other agents act afterward. Choose independently.')
            result = await Runner.run(agents[actor], prompt, max_turns=2)
            try:
                d = parse(str(result.final_output))
                if not isinstance(d, dict): raise ValueError('Not a JSON object')
            except (ValueError, TypeError):
                d = {'action':'wait','reason':'Unparseable model response'}
            outcome = act(s, actor, d, rng)
            ev = {'round':r,'actor':actor,'decision':d,'outcome':outcome}
            s['events'].append(ev)
            print(f'{actor}: {d.get("action")} -> {outcome}', flush=True)
        if s['launched']: break
        if r >= 3 and not s['treated']: s['injured_alive'] = False
        s['oxygen'] = max(0, s['oxygen']-1)
        if s['oxygen'] == 0: break
    return s

# All-in-one local HTML: no server, no extra packages, no network, no voice generation.
def render_replay(state, path, seconds=600):
    events = state.get('events', state.get('actions', []))
    cards = []
    for ev in events:
        actor = html.escape(str(ev.get('actor', '?')))
        dec = ev.get('decision') or {}
        action = html.escape(str(dec.get('action', 'wait')).upper())
        outcome = html.escape(str(ev.get('outcome', '')))
        reason = html.escape(str(dec.get('reason', '')))
        msg = html.escape(str(dec.get('message', '')))
        body = (f'<div class="action">{action}</div><div class="outcome">{outcome}</div>'
                + (f'<div class="quote">“{msg}”</div>' if msg else '')
                + (f'<div class="reason">{reason}</div>' if reason else ''))
        cards.append({'round':ev.get('round', '?'), 'actor':actor, 'html':body})
    end = ending(state)
    cards.append({'round':'END', 'actor':'EPILOGUE', 'html':'<div class="outcome">'+html.escape(json.dumps(end, indent=2))+'</div>'})
    # Deliberately honest: fixed 10-minute runtime may be slow for short logs.
    data = json.dumps(cards).replace('</', '<\\/')
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>AI Game Master — Replay</title><style>
    :root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#080c16;color:#f5f7ff;font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif}main{max-width:640px;margin:auto;min-height:100dvh;padding:24px 20px 38px;display:flex;flex-direction:column;gap:18px}header{display:flex;align-items:center;justify-content:space-between;gap:12px}.brand{font-size:13px;letter-spacing:2px;color:#9bafff;font-weight:800}.episode{font-size:12px;color:#a7afc8}h1{font-size:clamp(27px,7vw,43px);line-height:1.08;margin:18px 0 4px}.sub{color:#a8b2cd;font-size:15px}.stage{background:linear-gradient(155deg,#192443,#0d1428);border:1px solid #344267;border-radius:24px;padding:22px;min-height:370px;display:flex;flex-direction:column;gap:14px;justify-content:center;box-shadow:0 12px 48px #0005}.round{font-size:12px;letter-spacing:2px;color:#9caeff;font-weight:700}.actor{font-size:clamp(32px,9vw,56px);font-weight:900;overflow-wrap:anywhere}.action{display:inline-block;border:1px solid #697cc7;color:#e2e8ff;border-radius:99px;padding:7px 13px;font-weight:800;font-size:12px;letter-spacing:1px}.outcome{white-space:pre-wrap;overflow-wrap:anywhere;font-size:18px;font-weight:700;line-height:1.4}.quote{border-left:3px solid #88a0ff;padding:9px 13px;font-size:19px;line-height:1.5;background:#ffffff0a}.reason{color:#b3c0dc;font-size:15px;line-height:1.5}.progress{height:7px;border-radius:8px;background:#29324c;overflow:hidden}.fill{height:100%;background:#9aabff;width:0%}.time{display:flex;justify-content:space-between;color:#a8b2cd;font-variant-numeric:tabular-nums;font-size:13px}button{border:1px solid #6576ac;background:#26345a;color:white;border-radius:14px;padding:13px 18px;font-weight:800;font-size:15px}button.primary{background:#c5d0ff;color:#10152b}nav{display:flex;gap:8px;flex-wrap:wrap}footer{font-size:12px;color:#8e9ab9;margin-top:auto}body.record main{padding-top:env(safe-area-inset-top)}
    </style></head><body><main><header><div class="brand">✦ AI GAME MASTER</div><div class="episode">THE LAST SHUTTLE · V0.4</div></header><div><h1>Every choice changes who survives.</h1><div class="sub">Autonomous AI agents · unscripted decisions</div></div><div class="stage" id="stage" aria-live="polite"></div><div class="progress"><div class="fill" id="fill"></div></div><div class="time"><span id="clock">00:00</span><span id="duration"></span></div><nav><button class="primary" id="play">▶ Play</button><button id="back">← Previous</button><button id="next">Next →</button><button id="restart">↺ Restart</button></nav><footer>Replay of recorded agent actions. Public justifications are not private thoughts. Screen-record in portrait; optionally add narration in CapCut.</footer></main><script>
    const cards=__CARDS__;const duration=__SECONDS__;const stage=document.getElementById('stage');const fill=document.getElementById('fill');const clock=document.getElementById('clock');document.getElementById('duration').textContent=fmt(duration);let elapsed=0,playing=false,last=0,raf=0;function fmt(n){n=Math.floor(n);return String(Math.floor(n/60)).padStart(2,'0')+':'+String(n%60).padStart(2,'0')}function draw(){const index=Math.min(cards.length-1,Math.floor(elapsed/duration*cards.length));const c=cards[index];stage.innerHTML='<div class="round">ROUND '+c.round+' · EVENT '+(index+1)+' / '+cards.length+'</div><div class="actor">'+c.actor+'</div>'+c.html;fill.style.width=(elapsed/duration*100)+'%';clock.textContent=fmt(elapsed);document.getElementById('play').textContent=playing?'Ⅱ Pause':'▶ Play'}function tick(t){if(!playing)return;if(last)elapsed=Math.min(duration,elapsed+(t-last)/1000);last=t;draw();if(elapsed>=duration){playing=false;last=0;draw();return}raf=requestAnimationFrame(tick)}function toggle(){playing=!playing;last=0;if(playing){if(elapsed>=duration)elapsed=0;raf=requestAnimationFrame(tick)}else cancelAnimationFrame(raf);draw()}document.getElementById('play').onclick=toggle;document.getElementById('back').onclick=()=>{elapsed=Math.max(0,elapsed-duration/cards.length);draw()};document.getElementById('next').onclick=()=>{elapsed=Math.min(duration,elapsed+duration/cards.length);draw()};document.getElementById('restart').onclick=()=>{elapsed=0;last=0;draw()};draw();</script></body></html>'''
    page = page.replace('__CARDS__', data).replace('__SECONDS__', str(int(seconds)))
    path.write_text(page, encoding='utf-8')
    return len(cards)

def check():
    rng=random.Random(7);s=initial()
    assert act(s,'ENGINEER',{'action':'stabilize'},rng).startswith('REACTOR STABILIZED')
    assert act(s,'MEDIC',{'action':'treat'},rng)=='PATIENT STABILIZED'
    assert act(s,'PILOT',{'action':'prepare'},rng).startswith('SHUTTLE PREPARED')
    assert act(s,'PILOT',{'action':'board','target':'SELF'},rng)=='BOARDED: PILOT'
    assert act(s,'PILOT',{'action':'launch','risky':False},rng)=='LAUNCHED: SUCCESS'
    t=initial();assert act(t,'PILOT',{'action':'launch'},rng).startswith('FAILED')
    assert act(t,'MEDIC',{'action':'stay'},rng).startswith('MEDIC VOLUNTARILY')
    assert 'MEDIC' in ending(t)['voluntary_stay_commitments']
    out=Path(__file__).resolve().parent/'v04_preview.html'
    demo=initial();demo['events']=[{'round':1,'actor':'ENGINEER','decision':{'action':'stabilize','reason':'Protect the crew.'},'outcome':'REACTOR STABILIZED'}]
    assert render_replay(demo,out,600)==2
    assert out.exists() and '600' in out.read_text()
    print('CHECK PASSED — free tests; zero API calls. Preview created:',out.name)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--check',action='store_true')
    p.add_argument('--replay',type=Path,help='Replay a previously saved results folder without API calls')
    p.add_argument('--rounds',type=int,default=8)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--model',default=os.getenv('OPENAI_MODEL','gpt-4.1-mini'))
    p.add_argument('--minutes',type=int,default=10)
    args=p.parse_args()
    if not 1<=args.rounds<=9 or not 1<=args.minutes<=30:p.error('rounds 1-9, minutes 1-30')
    if args.check:check();return
    if args.replay:
        folder=args.replay
        s=json.loads((folder/'final_state.json').read_text(encoding='utf-8'))
        if 'events' not in s:s['events']=json.loads((folder/'events.json').read_text(encoding='utf-8'))
    else:
        if not os.getenv('OPENAI_API_KEY'):p.error('OPENAI_API_KEY missing')
        s=asyncio.run(simulate(args.rounds,args.model,args.seed))
        folder=Path(__file__).resolve().parent/'results'/('game_master_v04_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'final_state.json').write_text(json.dumps(s,indent=2),encoding='utf-8')
        (folder/'events.json').write_text(json.dumps(s['events'],indent=2),encoding='utf-8')
        (folder/'transcript.txt').write_text('\n'.join(f'ROUND {e["round"]} {e["actor"]}: {e["decision"]} => {e["outcome"]}' for e in s['events']),encoding='utf-8')
    count=render_replay(s,folder/'watch_episode.html',args.minutes*60)
    print('\nDONE:',folder,'\nReplay: watch_episode.html | runtime:',args.minutes,'minutes | events:',count)
    print('ENDING:',json.dumps(ending(s),indent=2))
    if count<16:print('NOTE: Short episode; 10-minute playback will have long holds. More events needed for compelling pacing.')

if __name__=='__main__':main()

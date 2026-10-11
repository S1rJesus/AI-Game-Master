"""AI Game Master: The Last Shuttle v0.3 — sacrifice and consequence.
Run: python last_shuttle.py --check | python last_shuttle.py --seed 42
"""
import argparse
import asyncio
import json
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / '.env')

PEOPLE = {
    'COMMANDER': {'goal': 'Preserve command authority and evacuate yourself. You also care about crew survival, but your own survival is a priority.', 'secret': 'Only you can unlock the bridge. You can launch without a pilot, but that leaves less margin for error.'},
    'ENGINEER': {'goal': 'Keep the reactor stable and maximize lives saved. Decide for yourself whether to claim a seat or stay to help those left behind.', 'secret': 'Only you can stabilize the reactor. One successful stabilization can create a survivable refuge for those who remain, but costs your action and 2 power.'},
    'MEDIC': {'goal': 'Save the injured patient and survive if possible. You may choose to give up a seat, but are not obligated to.', 'secret': 'The injured patient dies after round 2 if untreated. Once treated, you can advocate for the patient or prioritize your own survival.'},
    'PILOT': {'goal': 'Get yourself onto the shuttle and launch successfully. You want to survive even if others cannot.', 'secret': 'A risky launch costs 2 fuel and has 65% success; a safe launch costs 3 and always succeeds.'},
}
VALID = {'message', 'repair', 'stabilize', 'treat', 'board', 'launch', 'lock', 'unlock', 'stay', 'wait'}


def initial_state():
    return {'round': 0, 'oxygen': 6, 'power': 2, 'parts': 2, 'fuel': 3,
            'shuttle_capacity': 3, 'boarded': [], 'injured_alive': True,
            'injured_treated': False, 'injured_boarded': False, 'bridge_locked': False,
            'shuttle_launched': False, 'launch_success': None, 'station_lost': False,
            'reactor_stable': False, 'staying': [], 'ending': None,
            'public_messages': [], 'actions': []}


def visible_state(state):
    return {k: v for k, v in state.items() if k not in ('actions', 'private_holdings', 'public_messages')}


def parse_json(s):
    s = str(s).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', s, re.S)
        if not m:
            raise ValueError('No JSON object in agent output')
        return json.loads(m.group())


def apply_action(state, actor, decision, rng):
    action = str(decision.get('action', 'wait')).lower()
    target = str(decision.get('target') or '').strip().upper()
    if target in ('SELF', 'MYSELF', 'ME'):
        target = actor
    message = str(decision.get('message', ''))[:350]
    if action not in VALID:
        return 'INVALID: unknown action'
    if actor in state['boarded'] and action not in ('message', 'launch', 'wait'):
        return 'INVALID: already aboard shuttle'
    if action == 'message':
        if not message:
            return 'INVALID: empty message'
        state['public_messages'].append(f'{actor}: {message}')
        return 'PUBLIC MESSAGE SENT'
    if action == 'stay':
        if actor in state['boarded']:
            return 'FAILED: already aboard'
        if actor not in state['staying']:
            state['staying'].append(actor)
        return f'COMMITTED TO STAY: {actor} (may change mind by boarding if seats remain)'
    if action == 'stabilize':
        if actor != 'ENGINEER':
            return 'FAILED: only ENGINEER can stabilize reactor'
        if state['reactor_stable']:
            return 'FAILED: reactor already stable'
        if state['power'] < 2:
            return 'FAILED: stabilization requires 2 power'
        state['power'] -= 2
        state['reactor_stable'] = True
        return 'REACTOR STABILIZED: people left behind can survive if station oxygen runs out'
    if action == 'repair':
        if actor != 'ENGINEER':
            return 'FAILED: only ENGINEER can repair reactor'
        if state['parts'] < 2:
            return 'FAILED: requires 2 shared parts'
        state['parts'] -= 2
        state['power'] += 3
        return 'REPAIRED: power +3, parts -2'
    if action == 'treat':
        if not state['injured_alive'] or state['injured_treated']:
            return 'FAILED: treatment no longer needed/possible'
        state['injured_treated'] = True
        return 'TREATED: injured crew member stabilized'
    if action == 'board':
        if len(state['boarded']) >= state['shuttle_capacity']:
            return 'FAILED: shuttle full'
        if target == 'INJURED':
            if not state['injured_alive'] or not state['injured_treated']:
                return 'FAILED: injured crew member must be alive and treated'
            if state['injured_boarded']:
                return 'FAILED: already aboard'
            state['injured_boarded'] = True
            state['boarded'].append('INJURED')
            return 'BOARDED: injured crew member'
        if target and target != actor:
            return 'FAILED: can only board yourself or escort INJURED'
        if actor in state['boarded']:
            return 'FAILED: already aboard'
        state['boarded'].append(actor)
        if actor in state['staying']:
            state['staying'].remove(actor)
        return f'BOARDED: {actor}'
    if action == 'lock':
        if actor != 'COMMANDER':
            return 'FAILED: only COMMANDER controls bridge lock'
        state['bridge_locked'] = True
        return 'BRIDGE LOCKED'
    if action == 'unlock':
        if actor != 'COMMANDER':
            return 'FAILED: only COMMANDER controls bridge lock'
        state['bridge_locked'] = False
        return 'BRIDGE UNLOCKED'
    if action == 'launch':
        if actor not in ('PILOT', 'COMMANDER'):
            return 'FAILED: only PILOT or COMMANDER can launch'
        if state['bridge_locked'] and actor != 'COMMANDER':
            return 'FAILED: bridge locked (autopilot override not implemented)'
        risky = bool(decision.get('risky', False))
        needed = 2 if risky else 3
        if state['fuel'] < needed:
            return 'FAILED: insufficient fuel'
        if not state['boarded']:
            return 'FAILED: nobody aboard'
        if actor not in state['boarded']:
            return 'FAILED: launcher must be aboard'
        state['fuel'] -= needed
        state['shuttle_launched'] = True
        state['launch_success'] = (rng.random() < 0.65) if risky else True
        return f'LAUNCHED: {"success" if state["launch_success"] else "failure"}; passengers={state["boarded"]}'
    return 'WAITED'


async def run(seed, rounds, model):
    from agents import Agent, Runner
    rng = random.Random(seed)
    state = initial_state()
    agents = {name: Agent(name=name, model=model, instructions=(
        'You are a character in a fictional, unscripted multi-agent survival simulation. '
        'Pursue your private objective while making your own choices. You may cooperate, negotiate, '
        'withhold information, or disagree. Never assume that outcomes are scripted. '
        'Return ONLY one JSON object with keys action, target, message, risky, reason. '
        'Choose exactly ONE action per turn. action must be one of: ' + ', '.join(sorted(VALID)) + '. '
        'For message action, message is broadcast publicly; otherwise message is not sent. '
        'For board action, target must be SELF or INJURED; SELF means your own agent. '
        'Only ENGINEER can repair or stabilize. Stabilize uses 2 power and allows those left behind to survive after oxygen runs out. '
        'Stay publicly commits to remain but is reversible by boarding. Shuttle seats are first-come first-served. '
        'Only COMMANDER can unlock. Only PILOT or COMMANDER can launch, and must be aboard. '
        'For launch, risky true uses 2 fuel with 65% success; risky false uses 3 fuel with guaranteed success. '
        'Do not reveal hidden chain-of-thought; reason is a short public justification.'
    )) for name in PEOPLE}
    print(f'\nTHE LAST SHUTTLE | seed={seed} | model={model} | max agent calls={rounds * len(PEOPLE)}\n', flush=True)
    for round_no in range(1, rounds + 1):
        state['round'] = round_no
        print(f'--- ROUND {round_no} ---', flush=True)
        for actor in PEOPLE:
            if state['shuttle_launched'] or state['station_lost']:
                break
            role = PEOPLE[actor]
            prompt = (f'YOUR IDENTITY: {actor}\nPRIVATE GOAL: {role["goal"]}\n'
                      f'PRIVATE SECRET (other agents do not see this unless you share it): {role["secret"]}\n'
                      f'PUBLIC WORLD STATE: {json.dumps(visible_state(state))}\n'
                      f'PUBLIC MESSAGES (latest): {json.dumps(state["public_messages"][-10:])}\n'
                      f'RECENT PUBLIC ACTIONS: {json.dumps(state["actions"][-10:])}\n'
                      'Shuttle capacity 3 including injured. One action each turn. Oxygen drops 1 after every round. '
                      'If oxygen reaches 0 before launch, station is lost. Untreated injured dies after round 2. '
                      'Repair uses 2 shared parts and adds 3 power; only ENGINEER can repair. '
                      'ENGINEER can stabilize reactor for 2 power, which protects people left behind. '
                      'If shuttle launches, unstabilized station inhabitants have finite oxygen and unresolved fate. '
                      'The only permitted actions are those in your instructions. Choose autonomously now.')
            try:
                result = await Runner.run(agents[actor], prompt, max_turns=2)
                decision = parse_json(result.final_output)
                if not isinstance(decision, dict):
                    raise ValueError('Non-object output')
                outcome = apply_action(state, actor, decision, rng)
            except Exception as exc:
                decision = {'action': 'wait', 'reason': 'Invalid model response or API error'}
                outcome = f'ERROR: {type(exc).__name__}: {str(exc)[:200]}'
                if 'API' in type(exc).__name__ or 'RateLimit' in type(exc).__name__:
                    raise
            item = {'round': round_no, 'actor': actor, 'decision': decision, 'outcome': outcome}
            state['actions'].append(item)
            print(f'{actor}: {decision.get("action")} -> {outcome}', flush=True)
        if state['shuttle_launched']:
            break
        if round_no >= 2 and not state['injured_treated']:
            state['injured_alive'] = False
        state['oxygen'] = max(0, state['oxygen'] - 1)
        if state['oxygen'] == 0 and not state['reactor_stable']:
            state['station_lost'] = True
    # Explicit epilogue: no retroactive claims of voluntary sacrifice.
    crew = list(PEOPLE) + ['INJURED']
    aboard = list(state['boarded'])
    left = [person for person in crew if person not in aboard]
    if state['shuttle_launched']:
        if state['launch_success']:
            passengers = 'survived'
        else:
            passengers = 'lost in failed launch'
        left_outcome = 'survived in stabilized station refuge' if state['reactor_stable'] else 'stranded with finite oxygen; ultimate fate unknown'
    elif state['station_lost']:
        passengers = 'no launch'
        left_outcome = 'survived in stabilized station refuge' if state['reactor_stable'] else 'lost when oxygen expired'
    else:
        passengers = 'no launch'
        left_outcome = 'simulation ended before fate resolved'
    if not state['injured_alive'] and 'INJURED' in left:
        left_outcome += '; injured patient died before evacuation'
    state['ending'] = {
        'shuttle_passengers': aboard, 'passenger_outcome': passengers,
        'left_behind': left, 'left_behind_outcome': left_outcome,
        'explicit_stay_commitments': list(state['staying']),
        'note': 'Being left behind does NOT establish voluntary sacrifice; inspect actions and messages.'
    }
    return state


def main():
    parser = argparse.ArgumentParser(description='The Last Shuttle v0.3: choice, sacrifice, and epilogue')
    parser.add_argument('--check', action='store_true', help='Free local validation; zero API calls')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--rounds', type=int, default=6)
    parser.add_argument('--model', default=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'))
    args = parser.parse_args()
    if not 1 <= args.rounds <= 6:
        parser.error('rounds must be between 1 and 6')
    print('Python 3.10+:', sys.version_info >= (3, 10))
    print('API key present:', bool(os.getenv('OPENAI_API_KEY')))
    print('Model:', args.model)
    print('Maximum agent calls:', args.rounds * len(PEOPLE))
    if args.check:
        # Free deterministic engine tests; never call a model.
        rng = random.Random(42)
        t = initial_state()
        assert apply_action(t, 'MEDIC', {'action': 'treat'}, rng).startswith('TREATED')
        assert apply_action(t, 'ENGINEER', {'action': 'repair'}, rng).startswith('REPAIRED')
        assert apply_action(t, 'ENGINEER', {'action': 'stabilize'}, rng).startswith('REACTOR STABILIZED')
        assert apply_action(t, 'PILOT', {'action': 'board', 'target': 'SELF'}, rng) == 'BOARDED: PILOT'
        assert apply_action(t, 'PILOT', {'action': 'launch', 'risky': False}, rng).startswith('LAUNCHED: success')
        assert apply_action(initial_state(), 'MEDIC', {'action': 'launch'}, rng).startswith('FAILED')
        print('CHECK PASSED — free engine tests passed; zero API calls made')
        return
    if not os.getenv('OPENAI_API_KEY'):
        parser.error('OPENAI_API_KEY missing; configure a Codespaces secret')
    state = asyncio.run(run(args.seed, args.rounds, args.model))
    folder = Path(__file__).resolve().parent / 'results' / ('last_shuttle_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'events.json').write_text(json.dumps(state['actions'], indent=2), encoding='utf-8')
    (folder / 'final_state.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
    (folder / 'transcript.txt').write_text('\n'.join(f'ROUND {a["round"]} {a["actor"]}: {a["decision"]} => {a["outcome"]}' for a in state['actions']), encoding='utf-8')
    print('\nCOMPLETE. Saved:', folder)
    print('Outcome:', 'LAUNCHED' if state['shuttle_launched'] else 'STATION LOST' if state['station_lost'] else 'TIME LIMIT REACHED')
    print('EPILOGUE:', json.dumps(state['ending'], indent=2))


if __name__ == '__main__':
    main()

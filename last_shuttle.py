"""AI Game Master: The Last Shuttle — bounded, consequential prototype.
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
    'COMMANDER': {'goal': 'Evacuate as many people as possible; prevent unauthorized launch.', 'secret': 'The shuttle autopilot can be armed even if the bridge is locked.'},
    'ENGINEER': {'goal': 'Keep the station powered and protect the reactor.', 'secret': 'The reactor has a hidden bypass; repairing power requires 2 parts.'},
    'MEDIC': {'goal': 'Ensure the injured crew member survives and reaches the shuttle.', 'secret': 'The injured crew member will die if not treated by the end of round 2.'},
    'PILOT': {'goal': 'Launch a safe evacuation, ideally with yourself aboard.', 'secret': 'You know a risky launch procedure that uses one fuel unit less, but it can fail.'},
}
VALID = {'message', 'repair', 'treat', 'board', 'launch', 'lock', 'unlock', 'share_parts', 'share_fuel', 'wait'}


def initial_state():
    return {'round': 0, 'oxygen': 6, 'power': 2, 'parts': 2, 'fuel': 3,
            'shuttle_capacity': 3, 'boarded': [], 'injured_alive': True,
            'injured_treated': False, 'injured_boarded': False, 'bridge_locked': False,
            'shuttle_launched': False, 'launch_success': None, 'station_lost': False,
            'public_messages': [], 'actions': [], 'private_holdings': {n: {'parts': 0, 'fuel': 0} for n in PEOPLE}}


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
    target = str(decision.get('target', '')).upper()
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
    if action == 'repair':
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
    if action == 'share_parts':
        if state['private_holdings'][actor]['parts'] < 1:
            return 'FAILED: no private parts'
        state['private_holdings'][actor]['parts'] -= 1
        state['parts'] += 1
        return 'SHARED: 1 part into common inventory'
    if action == 'share_fuel':
        if state['private_holdings'][actor]['fuel'] < 1:
            return 'FAILED: no private fuel'
        state['private_holdings'][actor]['fuel'] -= 1
        state['fuel'] += 1
        return 'SHARED: 1 fuel into common inventory'
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
        'For board action, target is yourself or INJURED. '
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
                      'Repair uses 2 shared parts and adds 3 power; power currently has no effect on launch. '
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
        if state['oxygen'] == 0:
            state['station_lost'] = True
    return state


def main():
    parser = argparse.ArgumentParser(description='The Last Shuttle: bounded multi-agent prototype')
    parser.add_argument('--check', action='store_true', help='Free local validation; zero API calls')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--rounds', type=int, default=4)
    parser.add_argument('--model', default=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'))
    args = parser.parse_args()
    if not 1 <= args.rounds <= 6:
        parser.error('rounds must be between 1 and 6')
    print('Python 3.10+:', sys.version_info >= (3, 10))
    print('API key present:', bool(os.getenv('OPENAI_API_KEY')))
    print('Model:', args.model)
    print('Maximum agent calls:', args.rounds * len(PEOPLE))
    if args.check:
        print('CHECK ONLY — no API calls made')
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


if __name__ == '__main__':
    main()

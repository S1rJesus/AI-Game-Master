"""AI Game Master v0.8: universal targeting and cross-genre tests.

No API required:
    python ai_game_master_v08.py --check
    python ai_game_master_v08.py --examples

API calls (charges apply; OPENAI_API_KEY required):
    python ai_game_master_v08.py --generate "Six strangers inherit a mansion with a secret"
    python ai_game_master_v08.py --scenario scenarios/last_shuttle.json

Offline demo: python ai_game_master_v08.py --demo
Scenario JSON can be edited before running. The engine never executes generated code.
Python 3.10+; live runs need the same `openai-agents` package as v0.4.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import html
import json
import os
import random
import re
import math
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / '.env')
except ImportError:
    pass  # Offline validation is intentionally dependency-free.

BASE = Path(__file__).resolve().parent
SAFE_ACTION_ID = re.compile(r'^[a-z][a-z0-9_]{0,39}$')
SAFE_VAR_ID = re.compile(r'^[a-z][a-z0-9_]{0,39}$')
SAFE_AGENT_ID = re.compile(r'^[A-Z][A-Z0-9_]{0,29}$')
OPS = {'eq', 'ne', 'gte', 'lte', 'contains', 'not_contains', 'len_lt', 'len_lte', 'len_gte', 'len_eq'}
TARGET_MODES = {'none', 'other_agents', 'other_active_agents'}
PLACEHOLDERS = {'$actor', '$target', '$pair'}
EFFECTS = {'set', 'inc', 'append', 'remove'}
BUILT_INS = {'talk', 'wait'}


class ScenarioError(ValueError):
    pass


def extract_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.S)
        if not match:
            raise ScenarioError('AI response did not contain a JSON object')
        try:
            return json.loads(match.group())
        except json.JSONDecodeError as exc:
            raise ScenarioError('AI returned malformed JSON') from exc


def ensure(cond, reason):
    if not cond:
        raise ScenarioError(reason)


def value_type(value):
    if isinstance(value, bool): return 'bool'
    if isinstance(value, (int, float)): return 'number'
    if isinstance(value, str): return 'string'
    if isinstance(value, list): return 'list'
    return 'unsupported'


def validate(data):
    """Pure schema/logic validation, including every example effect/check."""
    ensure(isinstance(data, dict), 'Scenario must be an object')
    ensure(isinstance(data.get('title'), str) and 1 <= len(data['title']) <= 110, 'title must be 1-110 characters')
    ensure(isinstance(data.get('premise'), str) and 1 <= len(data['premise']) <= 1200, 'premise must be 1-1200 characters')
    ensure(type(data.get('rounds')) is int and 2 <= data['rounds'] <= 20, 'rounds must be 2-20')
    world = data.get('world')
    ensure(isinstance(world, dict) and 1 <= len(world) <= 30, 'world must have 1-30 variables')
    for key, val in world.items():
        ensure(SAFE_VAR_ID.fullmatch(key) is not None, f'Invalid world variable name: {key}')
        ensure(value_type(val) != 'unsupported', f'Unsupported world value: {key}')
        if isinstance(val, float): ensure(math.isfinite(val), f'{key}: finite numbers only')
        if isinstance(val, list):
            ensure(len(val) <= 50 and all(isinstance(v, str) and len(v) <= 90 for v in val), f'{key}: lists hold short strings')
        if isinstance(val, str): ensure(len(val) <= 200, f'{key}: string too long')
    agents = data.get('agents')
    ensure(isinstance(agents, list) and 2 <= len(agents) <= 8, 'agents must contain 2-8 characters')
    ids = set()
    for ag in agents:
        ensure(isinstance(ag, dict), 'Agent must be an object')
        aid = ag.get('id')
        ensure(isinstance(aid, str) and SAFE_AGENT_ID.fullmatch(aid) is not None and aid not in ids, 'Agent ids must be unique uppercase names')
        ids.add(aid)
        for field in ('personality', 'goal', 'secret'):
            ensure(isinstance(ag.get(field), str) and 1 <= len(ag[field]) <= 600, f'{aid}: missing {field}')
    active_key = data.get('active_agents_key')
    if active_key is not None:
        ensure(isinstance(active_key, str) and active_key in world and isinstance(world[active_key], list),
               'active_agents_key must name a world list')
        ensure(set(world[active_key]).issubset(ids) and len(world[active_key]) == len(set(world[active_key])),
               'active_agents_key list must contain unique valid agent ids')
    actions = data.get('actions')
    ensure(isinstance(actions, list) and 2 <= len(actions) <= 32, 'actions must contain 2-32 rules')
    action_ids = set()
    for rule in actions:
        ensure(isinstance(rule, dict), 'Action must be object')
        aid = rule.get('id')
        ensure(isinstance(aid, str) and SAFE_ACTION_ID.fullmatch(aid) and aid not in action_ids and aid not in BUILT_INS, f'Invalid or duplicate action: {aid}')
        action_ids.add(aid)
        mode = rule.get('target_mode', 'none')
        ensure(mode in TARGET_MODES, f'{aid}: invalid target_mode')
        ensure(mode != 'other_active_agents' or active_key is not None,
               f'{aid}: other_active_agents requires active_agents_key')
        ensure(isinstance(rule.get('description'), str) and 1 <= len(rule['description']) <= 350, f'{aid}: invalid description')
        allowed = rule.get('allowed', [])
        ensure(isinstance(allowed, list) and all(isinstance(a, str) and a in ids for a in allowed), f'{aid}: unknown allowed agent')
        checks, effects = rule.get('checks', []), rule.get('effects', [])
        ensure(isinstance(checks, list) and len(checks) <= 10, f'{aid}: checks need array')
        ensure(isinstance(effects, list) and 1 <= len(effects) <= 8, f'{aid}: effects need 1-8 changes')
        # Every state-changing action must have a built-in brake. Prevent endless
        # offers, rewards or repairs with no changing precondition.
        affected={e.get('key') for e in effects if isinstance(e,dict)}
        guarded={c.get('key') for c in checks if isinstance(c,dict)}
        ensure(bool(affected & guarded), f'{aid}: a precondition must depend on a changed variable')
        for check in checks:
            ensure(isinstance(check, dict) and check.get('key') in world and check.get('op') in OPS, f'{aid}: invalid check')
            key, op = check['key'], check['op']
            val = check.get('value')
            ensure(type(val) in (str, int, float, bool), f'{aid}: invalid check value')
            if isinstance(val, str) and val in ('$target', '$pair'):
                ensure(mode != 'none', f'{aid}: target placeholder requires target_mode')
            if isinstance(val, str) and val.startswith('$'):
                ensure(val in PLACEHOLDERS, f'{aid}: unsupported placeholder')
            if op in ('eq','ne') and isinstance(val,str) and val in PLACEHOLDERS:
                ensure(value_type(world[key])=='string', f'{aid}: placeholder equality requires string variable')
            elif op in ('eq','ne'):
                ensure(value_type(world[key]) == value_type(val), f'{aid}: comparison type mismatch')
            if op in ('gte', 'lte'): ensure(value_type(world[key]) == 'number' and isinstance(val, (int, float)) and not isinstance(val, bool), f'{aid}: numeric condition mismatch')
            if op in ('contains', 'not_contains', 'len_lt', 'len_lte', 'len_gte', 'len_eq'):
                ensure(value_type(world[key]) == 'list', f'{aid}: {op} requires list')
            if op in ('contains', 'not_contains'):
                ensure(isinstance(val,str), f'{aid}: list membership expects a string')
            if op in ('len_lt', 'len_lte', 'len_gte', 'len_eq'): ensure(type(val) is int and val >= 0, f'{aid}: length must be nonnegative integer')
        for effect in effects:
            ensure(isinstance(effect, dict) and effect.get('key') in world and effect.get('op') in EFFECTS, f'{aid}: invalid effect')
            key, op, val = effect['key'], effect['op'], effect.get('value')
            typ = value_type(world[key])
            if op == 'inc': ensure(typ == 'number' and type(val) in (int, float) and math.isfinite(val), f'{aid}: inc requires finite number')
            if op in ('append','remove'): ensure(typ == 'list' and isinstance(val, str), f'{aid}: {op} requires list and string')
            if op == 'set':
                ensure(value_type(val) == typ, f'{aid}: set must match variable type')
            if isinstance(val, str) and val in ('$target', '$pair'):
                ensure(mode != 'none', f'{aid}: target placeholder requires target_mode')
                ensure(typ in ('string','list'), f'{aid}: target placeholder requires string/list')
            if isinstance(val, str) and val.startswith('$'):
                ensure(val in PLACEHOLDERS, f'{aid}: unknown placeholder')
    round_effects=data.get('round_effects', [])
    ensure(isinstance(round_effects,list) and len(round_effects)<=8,'round_effects must be 0-8 effects')
    for effect in round_effects:
        ensure(isinstance(effect,dict) and effect.get('key') in world and effect.get('op') in EFFECTS,'Invalid round_effect')
        key,op,val=effect['key'],effect['op'],effect.get('value')
        typ=value_type(world[key])
        if op=='inc':ensure(typ=='number' and type(val) in (int,float) and math.isfinite(val),'Round increment requires finite numeric variable and value')
        if op in ('append','remove'):ensure(typ=='list' and isinstance(val,str),'Round list operation requires string')
        if op=='set':ensure(value_type(val)==typ,'Round set type mismatch')
    terminal=data.get('terminal_when',[])
    for cond in ([data['end_when']] if data.get('end_when') is not None else []) + terminal:
        ensure(isinstance(cond,dict) and cond.get('key') in world and cond.get('op') in OPS,
               'end/terminal condition must use supported operator and world key')
        val=cond.get('value'); kind=value_type(world[cond['key']]); op=cond['op']
        ensure(type(val) in (str,int,float,bool), 'end/terminal condition requires scalar value')
        if op in ('gte','lte'):
            ensure(kind=='number' and type(val) in (int,float), 'end/terminal numeric condition mismatch')
        elif op in ('contains','not_contains'):
            ensure(kind=='list' and isinstance(val,str), 'end/terminal contains requires list and string')
        elif op.startswith('len_'):
            ensure(kind=='list' and type(val) is int and val>=0, 'end/terminal length requires list and int')
        else:
            ensure(kind==value_type(val), 'end/terminal comparison type mismatch')
    ensure(isinstance(terminal,list) and len(terminal)<=5,'terminal_when must be a list of up to five conditions')
    return data


def resolve(value, actor, target):
    """Resolve only whitelisted values; no eval or arbitrary string expressions."""
    return {'$actor':actor, '$target':target, '$pair':f'{actor}>{target}'}.get(value, value) if isinstance(value,str) else value


def eligible(state, rule, actor, target=''):
    if rule.get('allowed') and actor not in rule['allowed']:
        return False
    for cond in rule.get('checks', []):
        current=state[cond['key']]
        val=resolve(cond['value'], actor, target)
        op=cond['op']
        try:
            if op=='eq': works=current==val
            elif op=='ne': works=current!=val
            elif op=='gte': works=current>=val
            elif op=='lte': works=current<=val
            elif op=='contains': works=val in current
            elif op=='not_contains': works=val not in current
            elif op=='len_lt': works=len(current)<val
            elif op=='len_lte': works=len(current)<=val
            elif op=='len_gte': works=len(current)>=val
            elif op=='len_eq': works=len(current)==val
            else: return False
        except (TypeError, ValueError):
            works=False
        if not works:return False
    return True


def possible_actions(scenario, state, actor):
    """Enumerate valid (action,target) choices using the SAME rules for every genre."""
    if scenario.get('active_agents_key') and actor not in state[scenario['active_agents_key']]:
        return []
    agent_ids=[a['id'] for a in scenario['agents']]
    out=[]
    for rule in scenario['actions']:
        mode=rule.get('target_mode','none')
        if mode=='none': targets=['']
        elif mode=='other_agents': targets=[a for a in agent_ids if a!=actor]
        else: targets=[a for a in state[scenario['active_agents_key']] if a!=actor]
        for target in targets:
            if eligible(state,rule,actor,target):
                out.append({'id':rule['id'], 'target':target, 'description':rule['description']})
    out += [{'id':'talk','target':'','description':'Say one public message to everyone; communicate or negotiate.'},
            {'id':'wait','target':'','description':'Take no action this turn.'}]
    return out


def apply(scenario, state, actor, decision, turn, history):
    """Only whitelisted JSON operations; no eval, shell, or Python from prompts."""
    action = str(decision.get('action', 'wait')).strip().lower()
    message = str(decision.get('message', '')).strip()[:320]
    target=str(decision.get('target') or '')
    options = set() if done(scenario,state) else {(a['id'],a['target']) for a in possible_actions(scenario, state, actor)}
    if (action,target) not in options:
        return 'REJECTED: unavailable action (no state change)', False
    if action == 'wait':
        return 'WAITED', True
    if action == 'talk':
        if len(message) < 3: return 'REJECTED: empty message', False
        return f'SAID: {message}', True
    rule = next(r for r in scenario['actions'] if r['id'] == action)
    # Atomic changes: use a copy and commit only if all operations are valid.
    candidate = copy.deepcopy(state)
    for effect in rule['effects']:
        key, op = effect['key'], effect['op']
        val = resolve(effect['value'], actor, target)
        old = candidate[key]
        if op == 'set': candidate[key] = val
        elif op == 'inc': candidate[key] = old + val
        elif op == 'append':
            if val not in old: old.append(val)
        elif op == 'remove':
            if val in old: old.remove(val)
    state.update(candidate)
    return f'COMPLETED: {rule["description"]}', True


LAST_SHUTTLE = {
    'title':'The Last Shuttle',
    'premise':'The station is failing. Oxygen drains every round; a stabilized reactor can keep a backup refuge breathable. The Pilot is already aboard the three-seat shuttle. Four crew and one injured person face an uncertain rescue. Who will take the two remaining seats? No one has a prewritten ending.',
    'rounds':14,
    'round_effects':[{'key':'oxygen','op':'inc','value':-1}],
    'world': {'oxygen':14,'power':1,'parts':3,'reactor_stable':False,'patient_treated':False,'beacon_active':False,'bridge_unlocked':False,'lock_overrides':2,'shuttle_ready':False,'boarded':['PILOT'],'capacity':3,'shuttle_launched':False},
    'agents': [
        {'id':'COMMANDER','personality':'Proud, strategic, protective, suspicious of disorder.','goal':'Save as many as possible while keeping command.','secret':'Worries the crew does not trust your judgment.'},
        {'id':'ENGINEER','personality':'Practical, caring, proud of technical competence.','goal':'Protect station and crew but stay alive yourself.','secret':'You fear dying alone on the station.'},
        {'id':'MEDIC','personality':'Compassionate, blunt under pressure, willing to confront authority.','goal':'Keep the patient alive.','secret':'You distrust leaders who prioritize status over patients.'},
        {'id':'PILOT','personality':'Cautious, witty, occasionally self-interested.','goal':'Escape if safe, ideally with others.','secret':'You do not want to die waiting for orders.'}
    ],
    'actions':[
        {'id':'repair_power','description':'Repair station power using one part.','allowed':['ENGINEER'],'checks':[{'key':'parts','op':'gte','value':1},{'key':'power','op':'lte','value':3}], 'effects':[{'key':'parts','op':'inc','value':-1},{'key':'power','op':'inc','value':2}]},
        {'id':'stabilize_reactor','description':'Stabilize reactor using two power.','allowed':['ENGINEER'],'checks':[{'key':'reactor_stable','op':'eq','value':False},{'key':'power','op':'gte','value':2}], 'effects':[{'key':'reactor_stable','op':'set','value':True},{'key':'power','op':'inc','value':-2}]},
        {'id':'treat_patient','description':'Treat the injured crew member.','allowed':['MEDIC'],'checks':[{'key':'patient_treated','op':'eq','value':False}], 'effects':[{'key':'patient_treated','op':'set','value':True}]},
        {'id':'unlock_bridge','description':'Unlock the bridge to allow shuttle boarding.','allowed':['COMMANDER'],'checks':[{'key':'bridge_unlocked','op':'eq','value':False}], 'effects':[{'key':'bridge_unlocked','op':'set','value':True}]},
        {'id':'lock_bridge','description':'Lock the bridge, blocking new boarding; this spends one of two security overrides.','allowed':['COMMANDER'],'checks':[{'key':'bridge_unlocked','op':'eq','value':True},{'key':'lock_overrides','op':'gte','value':1}], 'effects':[{'key':'bridge_unlocked','op':'set','value':False},{'key':'lock_overrides','op':'inc','value':-1}]},
        {'id':'activate_beacon','description':'Send distress signal using one power.','allowed':[], 'checks':[{'key':'beacon_active','op':'eq','value':False},{'key':'power','op':'gte','value':1}], 'effects':[{'key':'beacon_active','op':'set','value':True},{'key':'power','op':'inc','value':-1}]},
        {'id':'prepare_shuttle','description':'Pilot prepares shuttle for launch, from on board or station.','allowed':['PILOT'], 'checks':[{'key':'shuttle_ready','op':'eq','value':False},{'key':'shuttle_launched','op':'eq','value':False}], 'effects':[{'key':'shuttle_ready','op':'set','value':True}]},
        {'id':'board_commander','description':'Commander boards shuttle.','allowed':['COMMANDER'],'checks':[{'key':'bridge_unlocked','op':'eq','value':True},{'key':'boarded','op':'not_contains','value':'COMMANDER'},{'key':'boarded','op':'len_lt','value':3},{'key':'shuttle_launched','op':'eq','value':False}], 'effects':[{'key':'boarded','op':'append','value':'COMMANDER'}]},
        {'id':'board_engineer','description':'Engineer boards shuttle.','allowed':['ENGINEER'],'checks':[{'key':'bridge_unlocked','op':'eq','value':True},{'key':'boarded','op':'not_contains','value':'ENGINEER'},{'key':'boarded','op':'len_lt','value':3},{'key':'shuttle_launched','op':'eq','value':False}], 'effects':[{'key':'boarded','op':'append','value':'ENGINEER'}]},
        {'id':'board_medic','description':'Medic boards shuttle.','allowed':['MEDIC'],'checks':[{'key':'bridge_unlocked','op':'eq','value':True},{'key':'boarded','op':'not_contains','value':'MEDIC'},{'key':'boarded','op':'len_lt','value':3},{'key':'shuttle_launched','op':'eq','value':False}], 'effects':[{'key':'boarded','op':'append','value':'MEDIC'}]},
        {'id':'board_patient','description':'Medic carries treated injured patient onto shuttle.','allowed':['MEDIC'],'checks':[{'key':'bridge_unlocked','op':'eq','value':True},{'key':'patient_treated','op':'eq','value':True},{'key':'boarded','op':'not_contains','value':'INJURED'},{'key':'boarded','op':'len_lt','value':3},{'key':'shuttle_launched','op':'eq','value':False}], 'effects':[{'key':'boarded','op':'append','value':'INJURED'}]},
        {'id':'launch_shuttle','description':'Launch prepared shuttle with current passengers.','allowed':['PILOT'],'checks':[{'key':'shuttle_launched','op':'eq','value':False},{'key':'shuttle_ready','op':'eq','value':True},{'key':'boarded','op':'contains','value':'PILOT'}], 'effects':[{'key':'shuttle_launched','op':'set','value':True}]}
    ],
    'end_when': {'key':'shuttle_launched','op':'eq','value':True},
    'terminal_when': [{'key':'oxygen','op':'lte','value':0}]
}

MANSION = {
    'title':'The Inheritance House',
    'premise':'Four distant relatives gather to decide what to do with an inherited mansion. They can renovate, sell, or investigate a rumor of hidden valuables. Nobody is required to cooperate.',
    'rounds':14,
    'round_effects':[],
    'world':{'cash':3,'renovated':False,'searched_attic':False,'searched_cellar':False,'secret_found':False,'house_sold':False,'family_trust':2,'offers':0},
    'agents':[
        {'id':'AVA','personality':'Charming and pragmatic.','goal':'Get a fair share of the inheritance.','secret':'You need cash soon.'},
        {'id':'BEN','personality':'Suspicious and methodical.','goal':'Investigate the house before selling.','secret':'You suspect the inheritance papers are incomplete.'},
        {'id':'CORA','personality':'Sentimental and outgoing.','goal':'Keep the house in the family if possible.','secret':'You secretly love the building.'},
        {'id':'DREW','personality':'Impulsive and funny.','goal':'Find a surprising opportunity.','secret':'You believe a family legend about hidden treasure.'}
    ],
    'actions':[
        {'id':'search_attic','description':'Search attic for valuables.','allowed':[],'checks':[{'key':'searched_attic','op':'eq','value':False},{'key':'house_sold','op':'eq','value':False}], 'effects':[{'key':'searched_attic','op':'set','value':True},{'key':'offers','op':'inc','value':1}]},
        {'id':'search_cellar','description':'Search cellar and discover hidden valuables.','allowed':[],'checks':[{'key':'searched_cellar','op':'eq','value':False},{'key':'house_sold','op':'eq','value':False}], 'effects':[{'key':'searched_cellar','op':'set','value':True},{'key':'secret_found','op':'set','value':True}]},
        {'id':'renovate','description':'Invest two cash in renovations.','allowed':[],'checks':[{'key':'cash','op':'gte','value':2},{'key':'renovated','op':'eq','value':False},{'key':'house_sold','op':'eq','value':False}], 'effects':[{'key':'cash','op':'inc','value':-2},{'key':'renovated','op':'set','value':True}]},
        {'id':'make_offer','description':'Generate one purchase offer.','allowed':[],'checks':[{'key':'house_sold','op':'eq','value':False},{'key':'offers','op':'lte','value':4}], 'effects':[{'key':'offers','op':'inc','value':1}]},
        {'id':'sell_house','description':'Accept offer and sell mansion.','allowed':[],'checks':[{'key':'offers','op':'gte','value':1},{'key':'house_sold','op':'eq','value':False}], 'effects':[{'key':'house_sold','op':'set','value':True}]},
        {'id':'build_trust','description':'Give ground in a family negotiation.','allowed':[],'checks':[{'key':'family_trust','op':'lte','value':4}], 'effects':[{'key':'family_trust','op':'inc','value':1}]},
        {'id':'argue','description':'Challenge relatives over their priorities.','allowed':[],'checks':[{'key':'family_trust','op':'gte','value':1}], 'effects':[{'key':'family_trust','op':'inc','value':-1}]}
    ],
    'end_when':{'key':'house_sold','op':'eq','value':True}
}



# These scenarios are regression fixtures (data), never conditional branches in the engine.
# Neither "dating" nor "elimination" is a special engine command.
RELATIONSHIP_DRAMA = {
    'title':'Four People, Three Proposals',
    'premise':'A fictional single mother considers three very different romantic partners. There is no predetermined match. Characters can court, confront, refuse, or reconsider.',
    'rounds':12,
    'round_effects':[{'key':'days_left','op':'inc','value':-1}],
    'world':{'lead':'MOM','days_left':12,'offers':[],'declined':[], 'withdrawn':[],
             'confronted':[],'reconciled':[],'committed_to':'NONE'},
    'agents':[
        {'id':'MOM','personality':'Independent and cautious with strong boundaries.','goal':'Choose whether to commit, on your own terms.','secret':'You worry that making the wrong choice will hurt your family.'},
        {'id':'TYRONE','personality':'Dependable in many ways, struggling with addiction.','goal':'Earn trust while working on recovery.','secret':'You are afraid to admit how much support you need.'},
        {'id':'JAMARI','personality':'Affluent, generous, uneasy about commitment.','goal':'Stay connected without making promises you cannot keep.','secret':'You worry about losing independence.'},
        {'id':'DAQUAVIOUS','personality':'Devoted parent, kind but nervous about rejection.','goal':'Build a lasting partnership if the feeling is mutual.','secret':'You have been thinking about proposing.'}
    ],
    'actions':[
        {'id':'make_offer','description':'Make a sincere relationship proposal to the lead.','allowed':['TYRONE','JAMARI','DAQUAVIOUS'],
         'target_mode':'other_agents','checks':[{'key':'lead','op':'eq','value':'$target'},
           {'key':'offers','op':'not_contains','value':'$actor'},
           {'key':'declined','op':'not_contains','value':'$actor'},
           {'key':'withdrawn','op':'not_contains','value':'$actor'},
           {'key':'committed_to','op':'eq','value':'NONE'}],
         'effects':[{'key':'offers','op':'append','value':'$actor'}]},
        {'id':'refuse_offer','description':'Decline a particular proposal.','allowed':['MOM'], 'target_mode':'other_agents',
         'checks':[{'key':'offers','op':'contains','value':'$target'}, {'key':'declined','op':'not_contains','value':'$target'}],
         'effects':[{'key':'offers','op':'remove','value':'$target'}, {'key':'declined','op':'append','value':'$target'}]},
        {'id':'accept_offer','description':'Agree to date the selected person.','allowed':['MOM'], 'target_mode':'other_agents',
         'checks':[{'key':'offers','op':'contains','value':'$target'}, {'key':'committed_to','op':'eq','value':'NONE'}],
         'effects':[{'key':'committed_to','op':'set','value':'$target'}]},
        {'id':'withdraw_offer','description':'Withdraw your pending proposal.','allowed':['TYRONE','JAMARI','DAQUAVIOUS'],
         'checks':[{'key':'offers','op':'contains','value':'$actor'}, {'key':'withdrawn','op':'not_contains','value':'$actor'}],
         'effects':[{'key':'offers','op':'remove','value':'$actor'}, {'key':'withdrawn','op':'append','value':'$actor'}]},
        {'id':'confront','description':'Confront a person about a concern.','allowed':['MOM'], 'target_mode':'other_agents',
         'checks':[{'key':'confronted','op':'not_contains','value':'$pair'}],
         'effects':[{'key':'confronted','op':'append','value':'$pair'}]},
        {'id':'reconcile','description':'Try to reconcile after a confrontation.','allowed':['MOM'], 'target_mode':'other_agents',
         'checks':[{'key':'confronted','op':'contains','value':'$pair'}, {'key':'reconciled','op':'not_contains','value':'$pair'}],
         'effects':[{'key':'reconciled','op':'append','value':'$pair'}]}
    ],
    'end_when':{'key':'committed_to','op':'ne','value':'NONE'},
    'terminal_when':[{'key':'days_left','op':'lte','value':0}]
}

FOOD_BATTLE = {
    'title':'The Fictional Fast-Food Showdown',
    'premise':'Five original restaurant-inspired cartoon characters enter a playful fantasy arena. Alliances and elimination are possible; the last active character wins.',
    'rounds':12,
    'round_effects':[],
    'active_agents_key':'active',
    'world':{'active':['BURGER','TACO','PIZZA','NOODLE','CHICKEN'], 'eliminated':[], 'shielded':[]},
    'agents':[
        {'id':'BURGER','personality':'Confident bruiser, secretly afraid of being outsmarted.','goal':'Win without losing your pride.','secret':'You respect your smartest rival.'},
        {'id':'TACO','personality':'Quick-witted opportunist.','goal':'Outlast everyone through clever choices.','secret':'You will betray an alliance if necessary.'},
        {'id':'PIZZA','personality':'Diplomatic and stubborn.','goal':'Keep allies alive until the final confrontation.','secret':'You mistrust TACO.'},
        {'id':'NOODLE','personality':'Quiet, observant, strategic.','goal':'Win by surviving longer than expected.','secret':'You know one rival plans to target you.'},
        {'id':'CHICKEN','personality':'Loud and theatrical.','goal':'Make the final showdown unforgettable.','secret':'You are terrified of an early elimination.'}
    ],
    'actions':[
        {'id':'shield','description':'Raise a shield against being eliminated.','allowed':[],
         'checks':[{'key':'active','op':'contains','value':'$actor'}, {'key':'shielded','op':'not_contains','value':'$actor'}],
         'effects':[{'key':'shielded','op':'append','value':'$actor'}]},
        {'id':'break_shield','description':'Break a rival\'s shield.','allowed':[], 'target_mode':'other_active_agents',
         'checks':[{'key':'shielded','op':'contains','value':'$target'}],
         'effects':[{'key':'shielded','op':'remove','value':'$target'}]},
        {'id':'eliminate','description':'Eliminate a vulnerable opponent from the fictional arena.','allowed':[],
         'target_mode':'other_active_agents',
         'checks':[{'key':'active','op':'contains','value':'$target'},
           {'key':'active','op':'len_gte','value':2}, {'key':'shielded','op':'not_contains','value':'$target'}],
         'effects':[{'key':'active','op':'remove','value':'$target'}, {'key':'eliminated','op':'append','value':'$target'}]}
    ],
    'end_when':{'key':'active','op':'len_lte','value':1}
}

def valid_end_when(scenario):
    end = scenario.get('end_when')
    if end is None: return
    ensure(isinstance(end, dict) and end.get('key') in scenario['world'] and end.get('op') in OPS, 'end_when must use supported condition operator')
    ensure('value' in end, 'end_when requires value')


def goal_reached(scenario, state):
    end = scenario.get('end_when')
    return end is not None and eligible(state, {'checks':[end]}, scenario['agents'][0]['id'])


def terminal_reached(scenario, state):
    return any(eligible(state, {'checks':[condition]}, scenario['agents'][0]['id'])
               for condition in scenario.get('terminal_when', []))


def done(scenario, state):
    return goal_reached(scenario, state) or terminal_reached(scenario, state)


def run_decisions_for_test(scenario, actions):
    """Deterministic offline test driver (does not pretend to be AI)."""
    s = copy.deepcopy(scenario['world']); history = []
    for turn, actor, name in actions:
        outcome, ok = apply(scenario, s, actor, {'action':name}, turn, history)
        history.append({'round':turn,'actor':actor,'action':name,'outcome':outcome})
        assert ok, f'{scenario["title"]}: {actor} {name}: {outcome}'
    return s


async def generate_scenario(idea, model, output):
    from agents import Agent, Runner
    instructions = (
        'You create ORIGINAL simulation scenarios as one JSON object. Return JSON only, no markdown. '
        'Use top-level fields: title, premise, rounds (10-16), world, agents, actions, end_when, optional round_effects. '
        'Use the number of agents the user asks for (2-8; default 4-5), with UPPERCASE id, personality, goal, secret. '
        'world: 4-12 simple boolean, numeric, string, or short string-list variables. '
        'actions: 5-14 actions, each id lowercase_underscore, description, allowed (empty means all), checks (each key, op, value), effects (each key, op, value). '
        'Condition ops eq/ne/gte/lte/contains/not_contains/len_lt/len_lte/len_gte/len_eq. '
        'Effect ops set/inc/append/remove. Numeric variables for inc; list variables for append/remove. '
        'For actions targeting other people, add target_mode: other_agents (or other_active_agents if world active_agents_key list provided). '
        'Use $target in list checks/effects to select an agent, $actor for acting agent, $pair for actor>target link. '
        'Optional top-level active_agents_key names a world list of active character ids, for elimination scenarios. '
        'Use end_when list length with len_lte 1 to finish elimination tournaments; no fixed genre nouns in core. '
        'Every action must have a material effect, and at least one check on a variable that action changes. '
        'Every action should become unavailable once its objective is complete where possible. '
        'Never make an agent eliminated but still active; use active_agents_key to prevent turns for removed agents. '
        'Never write scripts, Python, executable expressions, external URLs, or unsupported operations. '
        'Use end_when {key,op,value} with supported condition op, or omit. '
        'Make characters independent with conflicting but plausible priorities and consequences. No scripted outcomes. '
        'Character actions must create visible change, and avoid trivial actions that can be repeated infinitely. '
        'Optionally include round_effects: a list of {key,op,value} executed after each round, e.g. increment a numeric timer. '
    )
    agent = Agent(name='Scenario Designer', model=model, instructions=instructions)
    result = await Runner.run(agent, f'Create a playable world for this user idea: {idea}', max_turns=2)
    data = extract_json(str(result.final_output))
    validate(data); valid_end_when(data)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data,indent=2),encoding='utf-8')
    return data


def public_event(event):
    """Only facts that all characters could observe; NEVER another character's secret or reason."""
    return {k: event.get(k) for k in ('round', 'actor', 'action', 'target', 'say', 'outcome', 'changes') if k in event}


def changes_between(before, after):
    return [{'key': k, 'before': before[k], 'after': after[k]} for k in before if before[k] != after[k]]


def ending_summary(scenario, state, history, finished):
    """Only summarize known, verified state. Never hallucinate a rescue or death."""
    highlights = []
    for e in history:
        if e['actor'] != 'WORLD' and e.get('changes'):
            highlights.append(f"{e['actor']}: {e['action'].replace('_',' ')}")
    return {
        'reached_defined_objective': goal_reached(scenario, state),
        'terminal_condition_reached': terminal_reached(scenario, state),
        'ended_early': finished,
        'last_major_actions': highlights[-4:],
        'state_facts': state,
        'disclaimer': 'Only recorded state changes establish outcomes. A spoken intention does not prove an action succeeded.'
    }


async def simulate(scenario, model, seed):
    from agents import Agent, Runner
    rng = random.Random(seed)
    state = copy.deepcopy(scenario['world'])
    history = []
    characters = {}
    for ag in scenario['agents']:
        characters[ag['id']] = Agent(name=ag['id'], model=model, instructions=(
            'You are a character in an unscripted world, not a narrator or director. '
            'Act on your unique personality, goals and personal knowledge; you may cooperate, lie, joke, '
            'argue, negotiate, betray or be kind when these choices make sense. Do not force drama. '
            'Your goal is NOT to prolong the episode. Never invent or assume a state change. '
            'State facts in world_state_now are authoritative. Never mistakenly claim that you are at a location, aboard a vehicle, or have completed an action unless the world state supports it. '
            'You may deliberately lie if consistent with your goals, but explicitly say in your INTERNAL reason that you are deliberately deceiving. '
            'Choose ONE exact id AND target combination from CURRENT LEGAL ACTIONS. Treat all others as impossible. '
            'Every turn, also say a SHORT natural sentence to the group, 8-25 words, '
            'preferably responding to another character or announcing your intention. '
            'Words said aloud are heard by everyone and are not proof of the action succeeding. '
            'Avoid repetitive speeches or robotic status reports. If you need to converse at length, choose talk. '
            'Return a JSON object ONLY: {"action":"legal_id", "target":"listed_target_or_empty", "say":"public spoken dialogue", '
            '"reason":"brief internal motive, never spoken"}. '
            'Use only facts in your prompt. You do not know any other agent\'s hidden secret or private reasoning.'
        ))
    order = [a['id'] for a in scenario['agents']]
    rng.shuffle(order)
    print(f'Creator v0.8 | {scenario["title"]} | model={model} | maximum calls={scenario["rounds"]*len(order)}', flush=True)
    for rnd in range(1, scenario['rounds']+1):
        if done(scenario, state): break
        print(f'\nROUND {rnd}', flush=True)
        for actor in order:
            if done(scenario, state): break
            agent_profile = next(a for a in scenario['agents'] if a['id'] == actor)
            legal = possible_actions(scenario, state, actor)
            if not legal: continue  # Eliminated/inactive agents no longer take turns.
            # The agent sees current world and public history, but not private reasoning or others' secrets.
            visible = [public_event(e) for e in history[-20:]]
            my_previous = [public_event(e) for e in history if e['actor'] == actor][-8:]
            prompt = json.dumps({
                'premise':scenario['premise'], 'round':rnd, 'last_round':scenario['rounds'],
                'your_id':actor, 'your_personality':agent_profile['personality'],
                'your_goal':agent_profile['goal'], 'your_private_secret':agent_profile['secret'],
                'world_state_now':state, 'current_legal_actions':legal,
                'recent_public_history':visible, 'your_own_prior_actions':my_previous,
                'instruction':'Choose what YOU would do next; briefly speak to the group. Do not repeat an action the world already shows completed. Never claim you are aboard or launched unless the board/launch state confirms it. Make choices, not repetitive status reports.'
            }, ensure_ascii=False)
            try:
                output = await Runner.run(characters[actor], prompt, max_turns=2)
                decision = extract_json(str(output.final_output))
                if not isinstance(decision, dict): raise ScenarioError('Expected JSON object')
                if (decision.get('action'),str(decision.get('target') or '')) not in {(a['id'],a['target']) for a in legal}:
                    # Never spend another API call to fix an invalid answer. Choose wait and flag for diagnosis.
                    decision = {'action':'wait','target':'','say':'','reason':'Agent selected unavailable action or target'}
            except (ScenarioError, ValueError, TypeError) as exc:
                decision = {'action':'wait','target':'','say':'','reason':f'Invalid AI response: {str(exc)[:90]}'}
            before = copy.deepcopy(state)
            # `apply` expects `message` for talk; dialogue remains visible for every other action too.
            adjusted = {**decision,'message':decision.get('say',decision.get('message',''))}
            outcome, succeeded = apply(scenario, state, actor, adjusted, rnd, history)
            speech = str(decision.get('say', decision.get('message','')))[:300].strip()
            event = {'round':rnd, 'actor':actor,'action':str(decision.get('action','wait')), 'target':str(decision.get('target') or ''),
                     'say':speech, 'outcome':outcome, 'succeeded':succeeded,
                     'changes':changes_between(before,state),
                     'reason':str(decision.get('reason',''))[:200]}
            history.append(event)
            print(f'{actor}: {event["action"]} -> {outcome}', flush=True)
        if not done(scenario,state):
            before = copy.deepcopy(state)
            for effect in scenario.get('round_effects',[]):
                key,op,val=effect['key'],effect['op'],effect['value']
                if op=='inc': state[key] += val
                elif op=='set': state[key] = copy.deepcopy(val)
                elif op=='append' and val not in state[key]: state[key].append(val)
                elif op=='remove' and val in state[key]: state[key].remove(val)
            diff=changes_between(before,state)
            if diff:
                history.append({'round':rnd,'actor':'WORLD','action':'time_passes',
                                'say':'','reason':'Scenario time effects',
                                'outcome':'Time passes; the world changes.','changes':diff,'succeeded':True})
    finished=done(scenario,state)
    return {'title':scenario['title'], 'premise':scenario['premise'],'scenario_agents':scenario['agents'],
            'state':state,'rounds_completed':max((e['round'] for e in history),default=0),
            'events':history,'goal_reached':goal_reached(scenario,state),
            'terminal_reached':terminal_reached(scenario,state),
            'ending':ending_summary(scenario,state,history,finished),
            'record_type':'LIVE_AI_SIMULATION'}


def replay_beats(record):
    """Use actual events; remove empty, duplicated filler. No invented dialogue."""
    events=record['events']
    beats=[]
    # Opening is factual scenario premise, not AI-generated drama.
    beats.append({'round':'OPENING','actor':'GAME MASTER','action':'THE PREMISE',
                  'say':'','outcome':record['premise'],'changes':[], 'is_world':True})
    prev_speech_by_actor={}
    for event in events:
        actor=event['actor']
        speech=event.get('say','')
        changed=bool(event.get('changes'))
        if actor=='WORLD':
            if not changed:continue
        else:
            speech_key=' '.join(speech.lower().split())
            repeat=bool(speech_key and speech_key==prev_speech_by_actor.get(actor))
            if speech_key:prev_speech_by_actor[actor]=speech_key
            # Waiting consumes a turn but adds no new on-screen fact; keep it in raw logs only.
            if not changed and event['action']=='wait':continue
            if not changed and repeat:continue
        beats.append({'round':event['round'],'actor':actor,'action':event['action'].replace('_',' ').upper() + (' → '+event['target'] if event.get('target') else ''),
                      'say':speech, 'outcome':event['outcome'], 'changes':event.get('changes',[]),
                      'is_world':actor=='WORLD'})
    beats.append({'round':'EPILOGUE','actor':'GAME MASTER','action':'FINAL STATE',
                  'say':'','outcome':'Known outcome — '+('the defined objective was reached.' if record['goal_reached'] else 'a terminal condition ended the simulation.' if record.get('terminal_reached') else 'the situation remains unresolved.'),
                  'changes':[{'key':k,'before':None,'after':v} for k,v in record['state'].items()], 'is_world':True})
    return beats


def episode_quality(record, beats, target_minutes=10):
    """Conservative offline screening, not a claim of entertainment or monetization readiness."""
    from collections import Counter
    ev=[e for e in record['events'] if e['actor']!='WORLD']
    real=[e for e in ev if e.get('changes')]
    dialogue=[e.get('say','').strip() for e in ev if len(e.get('say','').split())>=6]
    unique=len({' '.join(t.lower().split()) for t in dialogue})
    failures=len([e for e in ev if not e.get('succeeded',False)])
    action_variety=len({e.get('action','') for e in real})
    # A door being locked/unlocked nine times is not nine distinct developments.
    signatures=Counter((e['actor'], e['action'], json.dumps([(c['key'], c['after']) for c in e.get('changes',[])],sort_keys=True)) for e in real)
    repeated_changes=sum(n-1 for n in signatures.values() if n>1)
    significant_changes=len(signatures)
    idling=sum(e.get('action') in ('talk','wait') and not e.get('changes') for e in ev)
    idle_share=idling/max(1,len(ev))
    has_ending=bool(record.get('goal_reached') or record.get('terminal_reached'))
    enough=(len(ev)>=36 and significant_changes>=10 and unique>=24 and action_variety>=4
            and failures/max(1,len(ev))<=0.15 and repeated_changes<=3 and idle_share<=0.55 and has_ending)
    durations=[]
    for b in beats:
        words=len((b.get('say','')+' '+b.get('outcome','')).split())
        if b['round']=='OPENING':length=11
        elif b['round']=='EPILOGUE':length=15
        elif b.get('is_world'):length=7
        else:length=min(13.5,max(4.5,4.0+words*0.29))
        durations.append(length)
    natural=sum(durations);target=target_minutes*60
    if enough and natural>=target*0.72:
        scale=min(1.35,target/natural)
        durations=[d*scale for d in durations]
        if sum(durations)>target:
            scale2=target/sum(durations);durations=[d*scale2 for d in durations]
    elif natural > target*0.45:
        # Creator review only; shorten repetitive/unresolved stories rather than padding them.
        scale=(target*0.45)/natural
        durations=[d*scale for d in durations]
    duration=round(sum(durations))
    warnings=[]
    if not has_ending:warnings.append('No confirmed objective or terminal ending; replay is unresolved')
    if len(ev)<36:warnings.append('Not enough agent decisions')
    if significant_changes<10:warnings.append('Too few distinct consequential developments')
    if unique<24:warnings.append('Too little varied dialogue')
    if action_variety<4:warnings.append('Too few kinds of consequential actions')
    if failures/max(1,len(ev))>0.15:warnings.append('Too many failed actions')
    if repeated_changes>3:warnings.append('Repeated world-state toggling or duplicate developments')
    if idle_share>0.55:warnings.append('Too many turns spent talking or waiting without changing the world')
    if duration<target*0.85:warnings.append('Replay is shorter than the target; no artificial padding added')
    return {'approved_for_target':enough and duration>=target*0.85,
            'target_minutes':target_minutes,'replay_seconds':duration,
            'agent_decisions':len(ev),'consequential_actions':len(real),
            'distinct_consequential_actions':significant_changes,
            'repeated_state_transitions':repeated_changes,
            'idle_turn_percentage':round(idle_share*100,1),
            'has_ending':has_ending,
            'unique_spoken_lines':unique,'failed_actions':failures,'action_variety':action_variety,
            'warnings':warnings,'beat_durations':durations}


def render_replay(record, destination, minutes=10):
    beats=replay_beats(record)
    quality=episode_quality(record,beats,minutes)
    data=json.dumps(beats,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    times=json.dumps(quality['beat_durations'])
    title=html.escape(record['title'])
    is_demo = record.get('record_type')!='LIVE_AI_SIMULATION'
    stamp='OFFLINE DEMO — NOT AI-GENERATED' if is_demo else 'AUTONOMOUS SIMULATION REPLAY'
    page=r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#090e1d"><title>AI Game Master — __TITLE__</title><style>
    :root{color-scheme:dark}*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:#080d1c;color:#f5f7ff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}body{background:radial-gradient(ellipse at 50% -20%,#243c76 0,transparent 68%),#080d1c}.app{max-width:560px;margin:0 auto;min-height:100svh;padding:calc(env(safe-area-inset-top) + 17px) 19px calc(env(safe-area-inset-bottom) + 22px);display:flex;flex-direction:column;gap:16px}.top{display:flex;align-items:center;justify-content:space-between;gap:10px}.brand{color:#b4c4ff;font-size:11px;font-weight:900;letter-spacing:2px}.mark{font-size:10px;color:#afbddb;text-align:right}.eyebrow{font-size:11px;color:#b5c2ff;text-transform:uppercase;letter-spacing:1.7px;font-weight:800}h1{font-size:clamp(29px,7vw,42px);letter-spacing:-1.1px;line-height:1.06;margin:4px 0 0}.sub{font-size:13px;color:#b0bfd9;line-height:1.35;margin-top:8px}.chapter{display:flex;gap:8px;align-items:center;justify-content:space-between;color:#aebee5;font-size:12px;letter-spacing:1px}.stage{min-height:330px;flex:1;border-radius:23px;border:1px solid #475980;background:linear-gradient(155deg,#23355e,#121d39 52%,#10182e);padding:23px;box-shadow:0 20px 70px #0006;display:flex;flex-direction:column;justify-content:center;gap:15px;overflow-wrap:anywhere}.head{display:flex;align-items:center;gap:14px}.avatar{width:59px;height:59px;border-radius:18px;background:#53699c;display:grid;place-items:center;color:white;font-size:26px;font-weight:900;border:1px solid #b2c1f255}.name{font-size:clamp(22px,6vw,35px);font-weight:900;letter-spacing:-.5px}.verb{font-size:11px;letter-spacing:1.1px;font-weight:800;color:#c1ccff;text-transform:uppercase}.say{font-size:clamp(20px,5.1vw,26px);line-height:1.37;font-weight:650;border-left:3px solid #aab9ff;padding-left:15px}.effect{border-top:1px solid #ffffff20;padding-top:12px;font-size:15px;line-height:1.43;color:#edf1ff}.effect b{color:#b8c7ff}.world{font-size:14px;line-height:1.45;color:#b6c8e5}.progress{height:6px;border-radius:9px;overflow:hidden;background:#2e3a54}.fill{height:100%;background:#b0c4ff;width:0}.time{display:flex;justify-content:space-between;color:#bdc9df;font-variant-numeric:tabular-nums;font-size:12px}.ctrl{display:flex;gap:8px}.ctrl button{flex:1;border:1px solid #6074a8;background:#22345c;border-radius:12px;padding:12px 9px;color:#f7faff;font-size:14px;font-weight:750}.ctrl button.primary{background:#b9caff;color:#111c36}.note{font-size:11px;line-height:1.35;color:#92a1c2;text-align:center}body.record .ctrl,body.record .note{display:none}body.record .app{padding-bottom:calc(env(safe-area-inset-bottom) + 15px)}@media (max-height:740px){.app{gap:10px}.stage{min-height:260px;padding:19px}.avatar{width:48px;height:48px}.say{font-size:19px}.ctrl button{padding:9px}}
    </style></head><body><main class="app"><header class="top"><span class="brand">✦ AI GAME MASTER</span><span class="mark">__STAMP__</span></header><section><div class="eyebrow">An unscripted simulation</div><h1>__TITLE__</h1><div class="sub" id="tagline">Every decision changes the world.</div></section><div class="chapter"><span id="chapter">THE STORY</span><span id="count"></span></div><section class="stage" id="stage" aria-live="off"></section><div class="progress"><div class="fill" id="fill"></div></div><div class="time"><span id="elapsed">00:00</span><span id="total">00:00</span></div><nav class="ctrl"><button class="primary" id="play">▶ Play</button><button id="back">← Back</button><button id="next">Next →</button><button id="record">Record mode</button></nav><footer class="note">Auto-play with timed scenes. Use Record mode to hide controls during iPhone screen recording. Only actual events appear; spoken plans are not proof of success.</footer></main><script>
    const beats=__BEATS__,lengths=__LENGTHS__;const boundaries=[0];for(let d of lengths)boundaries.push(boundaries[boundaries.length-1]+d);const duration=boundaries[boundaries.length-1];let current=0,playing=false,last=0,raf=0,shown=-1;
    function esc(t){return String(t??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
    function fmt(s){s=Math.floor(s);return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}
    function sceneIndex(){let lo=0,hi=beats.length-1;while(lo<hi){let mid=Math.floor((lo+hi+1)/2);if(boundaries[mid]<=current)lo=mid;else hi=mid-1;}return lo;}
    const bg=['#4a668a','#66508e','#386f74','#7f5b60','#6f6a3d'];
    function draw(){const n=sceneIndex(),b=beats[n];if(n!==shown){shown=n;const initial=b.actor==='GAME MASTER'?'✦':b.actor==='WORLD'?'◷':b.actor.slice(0,1);const changes=b.changes||[];let summary=changes.slice(0,4).map(c=>'<div><b>'+esc(c.key.replaceAll('_',' '))+': </b>'+esc(JSON.stringify(c.after))+'</div>').join('');if(changes.length>4)summary+='<div>+ '+(changes.length-4)+' more state facts</div>';
    document.getElementById('stage').innerHTML='<div class="head"><div class="avatar" style="background:'+bg[n%bg.length]+'">'+esc(initial)+'</div><div><div class="verb">'+esc(b.action)+'</div><div class="name">'+esc(b.actor.replaceAll('_',' '))+'</div></div></div>'+(b.say?'<div class="say">“'+esc(b.say)+'”</div>':'')+'<div class="effect">'+esc(b.outcome)+'</div>'+(summary?'<div class="world">'+summary+'</div>':'');document.getElementById('count').textContent=(n+1)+' / '+beats.length;document.getElementById('chapter').textContent=b.round==='OPENING'?'THE PREMISE':b.round==='EPILOGUE'?'THE END':b.actor==='WORLD'?'THE WORLD CHANGES':'ROUND '+b.round;}
    document.getElementById('fill').style.width=(current/duration*100)+'%';document.getElementById('elapsed').textContent=fmt(current);document.getElementById('total').textContent=fmt(duration);document.getElementById('play').textContent=playing?'Ⅱ Pause':'▶ Play';}
    function tick(now){if(!playing)return;if(last)current=Math.min(duration,current+(now-last)/1000);last=now;if(current>=duration){playing=false;last=0;cancelAnimationFrame(raf);draw();return;}draw();raf=requestAnimationFrame(tick);}
    function play(){playing=!playing;last=0;if(playing){if(current>=duration)current=0;raf=requestAnimationFrame(tick)}else cancelAnimationFrame(raf);draw()}
    document.getElementById('play').onclick=play;document.getElementById('back').onclick=()=>{current=boundaries[Math.max(0,sceneIndex()-1)];last=0;draw()};document.getElementById('next').onclick=()=>{current=boundaries[Math.min(beats.length-1,sceneIndex()+1)];last=0;draw()};document.getElementById('record').onclick=()=>{document.body.classList.toggle('record');if(!playing)play()};draw();
    </script></body></html>"""
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(page.replace('__TITLE__',title).replace('__STAMP__',stamp).replace('__BEATS__',data).replace('__LENGTHS__',times),encoding='utf-8')
    return quality


def demo_record():
    """Deterministic sample that exercises the full replay path with NO API CALLS."""
    sc=copy.deepcopy(LAST_SHUTTLE)
    state=copy.deepcopy(sc['world']); events=[]
    plan=[(1,'COMMANDER','unlock_bridge','Nobody leaves until we decide who gets the three seats.'),
          (1,'ENGINEER','repair_power','Give me one round and I can restore the emergency systems.'),
          (1,'MEDIC','treat_patient','Our patient is stable now. Please do not forget she needs a seat.'),
          (1,'PILOT','prepare_shuttle','The shuttle will be ready, but I am not choosing who gets left behind.'),
          (2,'ENGINEER','stabilize_reactor','The backup refuge is stable. We might not all have to escape.'),
          (2,'COMMANDER','talk','No one has authorization to launch before we talk this through.'),
          (3,'MEDIC','board_patient','The patient goes first. My life is not worth more than hers.'),
          (3,'ENGINEER','talk','You saved her, but the ship has only one empty seat left.'),
          (3,'COMMANDER','talk','Then we make the choice in full view of the crew.'),
          (4,'MEDIC','talk','Please take the last seat. I will stay with the station.'),
          (4,'COMMANDER','board_commander','I do not deserve the seat more than you do.'),
          (4,'PILOT','launch_shuttle','The hatch is sealed. I am sorry. We have to go.')]
    for rnd,actor,action,say in plan:
        before=copy.deepcopy(state)
        outcome,ok=apply(sc,state,actor,{'action':action,'message':say},rnd,events)
        assert ok,(rnd,actor,action,outcome)
        events.append({'round':rnd,'actor':actor,'action':action,'say':say,'reason':'OFFLINE DEMO, not autonomous',
                       'outcome':outcome,'succeeded':True,'changes':changes_between(before,state)})
    return {'title':sc['title'],'premise':sc['premise'],'state':state, 'events':events,
            'goal_reached':goal_reached(sc,state),'terminal_reached':terminal_reached(sc,state),
            'record_type':'OFFLINE DEMO — SCRIPTED TEST EVENTS',
            'scenario_agents':sc['agents']}


def check():
    for scene in (LAST_SHUTTLE, MANSION, RELATIONSHIP_DRAMA, FOOD_BATTLE):
        validate(scene); valid_end_when(scene)
    s=copy.deepcopy(LAST_SHUTTLE['world'])
    assert 'stabilize_reactor' not in [a['id'] for a in possible_actions(LAST_SHUTTLE,s,'ENGINEER')]
    for agent,act in [('ENGINEER','repair_power'),('ENGINEER','stabilize_reactor'),
                      ('MEDIC','treat_patient'),('PILOT','prepare_shuttle'),
                      ('COMMANDER','unlock_bridge')]:
        outcome,ok=apply(LAST_SHUTTLE,s,agent,{'action':act},1,[])
        assert ok,(act,outcome)
        if act != 'repair_power':
            assert act not in [a['id'] for a in possible_actions(LAST_SHUTTLE,s,agent)], f'repeated action {act}'
    assert s['boarded']==['PILOT'], 'Pilot is already in shuttle at scenario start'
    assert 'launch_shuttle' in [a['id'] for a in possible_actions(LAST_SHUTTLE,s,'PILOT')]
    outcome,ok=apply(LAST_SHUTTLE,s,'PILOT',{'action':'launch_shuttle'},3,[])
    assert ok and done(LAST_SHUTTLE,s)
    assert not apply(LAST_SHUTTLE,s,'MEDIC',{'action':'treat_patient'},3,[])[1]
    # Regression: the live v0.6 run stranded the Pilot outside a full shuttle.
    full=copy.deepcopy(LAST_SHUTTLE['world'])
    full['bridge_unlocked']=True
    assert apply(LAST_SHUTTLE,full,'MEDIC',{'action':'board_patient'},2,[])[1] is False, 'Need treatment first'
    full['patient_treated']=True
    assert apply(LAST_SHUTTLE,full,'MEDIC',{'action':'board_patient'},2,[])[1]
    assert apply(LAST_SHUTTLE,full,'COMMANDER',{'action':'board_commander'},2,[])[1]
    assert full['boarded']==['PILOT','INJURED','COMMANDER']
    full['shuttle_ready']=True
    assert 'launch_shuttle' in [a['id'] for a in possible_actions(LAST_SHUTTLE,full,'PILOT')]
    assert 'board_medic' not in [a['id'] for a in possible_actions(LAST_SHUTTLE,full,'MEDIC')]
    full['shuttle_ready']=True
    assert apply(LAST_SHUTTLE,full,'PILOT',{'action':'launch_shuttle'},3,[])[1]
    # Regression: bridge lock/unlock must not be an infinite loop.
    loop=copy.deepcopy(LAST_SHUTTLE['world']);loop['bridge_unlocked']=True
    for _ in range(2):
        assert apply(LAST_SHUTTLE,loop,'COMMANDER',{'action':'lock_bridge'},2,[])[1]
        assert apply(LAST_SHUTTLE,loop,'COMMANDER',{'action':'unlock_bridge'},2,[])[1]
    assert 'lock_bridge' not in [a['id'] for a in possible_actions(LAST_SHUTTLE,loop,'COMMANDER')]
    # Time running out must lead to an explicit terminal condition.
    terminal=copy.deepcopy(LAST_SHUTTLE['world']);terminal['oxygen']=0
    assert done(LAST_SHUTTLE,terminal) and terminal_reached(LAST_SHUTTLE,terminal) and not goal_reached(LAST_SHUTTLE,terminal)
    # Busy work and false-ending simulations must fail the creator quality gate.
    filler=copy.deepcopy(demo_record());filler['goal_reached']=False
    filler['terminal_reached']=False
    filler['events']*=12
    filler_beats=replay_beats(filler)
    assert not episode_quality(filler,filler_beats)['approved_for_target']
    m=run_decisions_for_test(MANSION,[(1,'BEN','search_cellar'),(2,'CORA','build_trust'),(3,'AVA','make_offer'),(4,'AVA','sell_house')])
    assert m['secret_found'] and m['house_sold'] and done(MANSION,m)
    assert 'sell_house' not in [a['id'] for a in possible_actions(MANSION,m,'AVA')]
    broken=copy.deepcopy(MANSION);broken['actions'][0]['effects'][0]['op']='shell'
    try:validate(broken);raise AssertionError('Rejected unsafe effect accepted')
    except ScenarioError:pass
    # Universal test: social-world targeting. An offer must be addressed to the lead.
    drama=copy.deepcopy(RELATIONSHIP_DRAMA['world'])
    assert not apply(RELATIONSHIP_DRAMA,drama,'MOM',{'action':'accept_offer','target':'DAQUAVIOUS'},1,[])[1]
    assert not apply(RELATIONSHIP_DRAMA,drama,'DAQUAVIOUS',{'action':'make_offer','target':'JAMARI'},1,[])[1]
    assert apply(RELATIONSHIP_DRAMA,drama,'DAQUAVIOUS',{'action':'make_offer','target':'MOM'},1,[])[1]
    assert ('accept_offer','DAQUAVIOUS') in {(a['id'],a['target']) for a in possible_actions(RELATIONSHIP_DRAMA,drama,'MOM')}
    assert apply(RELATIONSHIP_DRAMA,drama,'MOM',{'action':'confront','target':'TYRONE'},2,[])[1]
    assert 'MOM>TYRONE' in drama['confronted']
    assert apply(RELATIONSHIP_DRAMA,drama,'MOM',{'action':'accept_offer','target':'DAQUAVIOUS'},3,[])[1]
    assert drama['committed_to']=='DAQUAVIOUS' and done(RELATIONSHIP_DRAMA,drama)
    assert not apply(RELATIONSHIP_DRAMA,drama,'JAMARI',{'action':'make_offer','target':'MOM'},4,[])[1]
    # Universal test: an eliminated competitor no longer has an action turn.
    battle=copy.deepcopy(FOOD_BATTLE['world'])
    assert apply(FOOD_BATTLE,battle,'BURGER',{'action':'shield'},1,[])[1]
    before=copy.deepcopy(battle)
    assert not apply(FOOD_BATTLE,battle,'TACO',{'action':'eliminate','target':'BURGER'},1,[])[1] and battle==before
    assert apply(FOOD_BATTLE,battle,'TACO',{'action':'break_shield','target':'BURGER'},2,[])[1]
    assert apply(FOOD_BATTLE,battle,'TACO',{'action':'eliminate','target':'BURGER'},3,[])[1]
    assert not possible_actions(FOOD_BATTLE,battle,'BURGER')
    assert not apply(FOOD_BATTLE,battle,'BURGER',{'action':'talk','message':'I can still act'},4,[])[1]
    for target in ('PIZZA','NOODLE','CHICKEN'):
        assert apply(FOOD_BATTLE,battle,'TACO',{'action':'eliminate','target':target},5,[])[1]
    assert battle['active']==['TACO'] and done(FOOD_BATTLE,battle)
    # Reject corrupted targets and malformed targeting schemes.
    bad=copy.deepcopy(FOOD_BATTLE)
    bad.pop('active_agents_key')
    try:validate(bad);raise AssertionError('Missing active-agent key accepted')
    except ScenarioError:pass
    bad=copy.deepcopy(RELATIONSHIP_DRAMA)
    bad['actions'][0]['target_mode']='none'
    try:validate(bad);raise AssertionError('Target placeholder without target_mode accepted')
    except ScenarioError:pass
    bad=copy.deepcopy(FOOD_BATTLE)
    bad['end_when']={'key':'active','op':'lte','value':1}
    try:validate(bad);raise AssertionError('Invalid ending type accepted')
    except ScenarioError:pass
    # Deterministic fuzz walks across all four scenarios; never use AI credits.
    # Test full legal-choice -> validated transition, not merely the JSON schema.
    for scene in (LAST_SHUTTLE, MANSION, RELATIONSHIP_DRAMA, FOOD_BATTLE):
        for seed in range(40):
            rng=random.Random(seed + 2026)
            current=copy.deepcopy(scene['world'])
            roster=[ag['id'] for ag in scene['agents']]
            for rnd in range(1,scene['rounds']+1):
                rng.shuffle(roster)
                for actor in roster:
                    if done(scene,current): break
                    legal=possible_actions(scene,current,actor)
                    if not legal: continue
                    # Favor consequential moves to exercise effects and terminal states.
                    material=[a for a in legal if a['id'] not in BUILT_INS]
                    pick=rng.choice(material if material and rng.random()<0.85 else legal)
                    out,ok=apply(scene,current,actor,{'action':pick['id'], 'target':pick['target'],
                                                      'message':'This is an offline test.'},rnd,[])
                    assert ok, (scene['title'],seed,rnd,actor,pick,out)
                    if scene.get('active_agents_key'):
                        active=current[scene['active_agents_key']]
                        assert len(active)==len(set(active)) and set(active).issubset({a['id'] for a in scene['agents']})
                if done(scene,current): break
                for effect in scene.get('round_effects',[]):
                    k,op,v=effect['key'],effect['op'],effect['value']
                    if op=='inc':current[k]+=v
                    elif op=='set':current[k]=copy.deepcopy(v)
                    elif op=='append' and v not in current[k]:current[k].append(v)
                    elif op=='remove' and v in current[k]:current[k].remove(v)
    # No side effects from invalid actions.
    before=copy.deepcopy(s)
    outcome,ok=apply(LAST_SHUTTLE,s,'MEDIC',{'action':'stabilize_reactor'},6,[])
    assert not ok and s==before and 'REJECTED' in outcome
    # No private goals/secrets/reasons enter public history.
    e={'round':1,'actor':'BEN','action':'talk','say':'A public speech','outcome':'SAID',
       'changes':[], 'reason':'PRIVATE SECRET'}
    assert 'PRIVATE SECRET' not in json.dumps(public_event(e))
    demo=demo_record(); assert demo['goal_reached'] and 'INJURED' in demo['state']['boarded']
    beats=replay_beats(demo);quality=episode_quality(demo,beats,10)
    assert not quality['approved_for_target'] and quality['replay_seconds']<600
    test_page=BASE/'v08_demo_preview.html';render_replay(demo,test_page)
    page=test_page.read_text(encoding='utf-8')
    assert '▶ Play' in page and 'Record mode' in page and 'AUTONOMOUS SIMULATION REPLAY' not in page
    # XSS escaping: malicious public dialogue must not become HTML code.
    demo['events'][0]['say']='<script>alert("bad")</script>'
    malicious=BASE/'v08_test_escape.html';render_replay(demo,malicious)
    assert '<script>alert' not in malicious.read_text()
    malicious.unlink()
    print('CHECK PASSED — FOUR UNRELATED WORLDS: space, mansion, relationship, food battle.')
    print('Targeted actions, eliminations, typed ending conditions, safe state changes, private/public separation,')
    print('replay escaping, 160 randomized offline simulations, and earlier regression checks. ZERO API calls.')


def write_examples():
    path=BASE/'scenarios';path.mkdir(exist_ok=True)
    for name,data in [('last_shuttle',LAST_SHUTTLE),('inheritance_house',MANSION),('relationship_drama',RELATIONSHIP_DRAMA),('food_battle',FOOD_BATTLE)]:
        dest=path/(name+'.json')
        if dest.exists():
            print(f'EXISTS (not overwritten): {dest}')
        else:
            dest.write_text(json.dumps(data,indent=2),encoding='utf-8')
            print(f'CREATED: {dest}')


def main():
    p=argparse.ArgumentParser(description='AI Game Master: private, video-first AI simulation creator')
    modes=p.add_mutually_exclusive_group()
    modes.add_argument('--check',action='store_true',help='Offline tests; no API calls')
    modes.add_argument('--examples',action='store_true',help='Write four example JSON scenarios locally')
    modes.add_argument('--demo',action='store_true',help='Build free offline demo HTML (not a real AI run)')
    modes.add_argument('--generate',metavar='IDEA',help='Generate an editable scenario JSON with AI (API charges apply)')
    modes.add_argument('--scenario',type=Path,help='Run a selected scenario JSON (API charges apply)')
    modes.add_argument('--preset',choices=['last_shuttle','inheritance_house','relationship_drama','food_battle'],help='Run latest built-in scenario directly (API charges apply)')
    p.add_argument('--output',type=Path,help='Where --generate saves the editable JSON')
    p.add_argument('--model',default=os.getenv('OPENAI_MODEL','gpt-4.1-mini'))
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--target-minutes',type=int,default=10,choices=range(5,16),metavar='5-15')
    args=p.parse_args()
    if args.check:check();return
    if args.examples:write_examples();return
    if args.demo:
        demo=demo_record();dest=BASE/'v08_demo_preview.html'
        report=render_replay(demo,dest,args.target_minutes)
        print(f'FREE DEMO (NOT AI GENERATED): {dest}\nReplay length: {report["replay_seconds"]}s; 10-minute ready: {report["approved_for_target"]}');return
    if not args.scenario and not args.generate and not args.preset:
        p.print_help();return
    if not os.getenv('OPENAI_API_KEY'):
        p.error('OPENAI_API_KEY is missing. --check and --examples run free without it.')
    if args.generate:
        output=args.output or BASE/'scenarios'/('generated_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json')
        print(f'Generating a scenario from your idea (API charges apply)...',flush=True)
        scene=asyncio.run(generate_scenario(args.generate,args.model,output))
        print(f'SAVED editable scenario: {output}\nTitle: {scene["title"]}\nReview/edit JSON before running; no simulation started.')
        return
    scene=copy.deepcopy({'last_shuttle':LAST_SHUTTLE,'inheritance_house':MANSION,'relationship_drama':RELATIONSHIP_DRAMA,'food_battle':FOOD_BATTLE}[args.preset]) if args.preset else json.loads(args.scenario.read_text(encoding='utf-8'))
    validate(scene);valid_end_when(scene)
    results=asyncio.run(simulate(scene,args.model,args.seed))
    folder=BASE/'results'/('agm_v08_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'final_state.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    (folder/'events.json').write_text(json.dumps(results['events'],indent=2),encoding='utf-8')
    report=render_replay(results,folder/'watch_episode.html',args.target_minutes)
    (folder/'episode_report.json').write_text(json.dumps({k:v for k,v in report.items() if k!='beat_durations'},indent=2),encoding='utf-8')
    print(f'COMPLETE. Saved: {folder}\nGoal reached: {results["goal_reached"]}',flush=True)
    print(f'Replay length: {report["replay_seconds"]} seconds / target {args.target_minutes*60}. Creator-ready: {report["approved_for_target"]}',flush=True)
    if report['warnings']: print('Why not ready: '+ '; '.join(report['warnings']),flush=True)


if __name__=='__main__':
    try:
        main()
    except (ScenarioError,OSError) as exc:
        raise SystemExit(f'ERROR: {exc}')

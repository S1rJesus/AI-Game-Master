"""AI Game Master 1.0 — ethical/psychological experiment foundation.

One file for iPhone Codespaces. Standard library for offline tests.
Live simulation uses the existing openai-agents installation and OPENAI_API_KEY.

Usage:
    python ai_game_master_v1.py --check          # free
    python ai_game_master_v1.py --examples       # free, writes two scenario JSONs
    python ai_game_master_v1.py --scenario scenarios/ethical_facility.json

No screenplay, no fixed result, no invented events. This is a small research
prototype, not yet a reliable high-IQ story generator or video application.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import random
import re
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(BASE / '.env')
except ImportError:
    pass

OPS = {'eq', 'ne', 'gt', 'gte', 'lt', 'lte'}
ID = re.compile(r'^[a-z][a-z0-9_]{0,39}$')
ACTOR = re.compile(r'^[A-Z][A-Z0-9_]{0,29}$')


class ScenarioError(ValueError):
    pass


def check(condition, explanation):
    if not condition:
        raise ScenarioError(explanation)


def compare(left, op, right):
    if op == 'eq': return left == right
    if op == 'ne': return left != right
    if op in {'gt', 'gte', 'lt', 'lte'}:
        if type(left) not in (int, float) or type(right) not in (int, float):
            return False
        return {'gt': lambda: left > right, 'gte': lambda: left >= right,
                'lt': lambda: left < right, 'lte': lambda: left <= right}[op]()
    raise ScenarioError('Unsupported comparison operator: ' + str(op))


def matches(state, requirements):
    return all(compare(state[r['key']], r['op'], r['value']) for r in requirements)


def validate(s):
    check(isinstance(s, dict), 'scenario must be a JSON object')
    check(isinstance(s.get('title'), str) and bool(s['title'].strip()), 'title required')
    check(isinstance(s.get('premise'), str) and bool(s['premise'].strip()), 'premise required')
    check(type(s.get('max_rounds')) is int and 2 <= s['max_rounds'] <= 16, 'max_rounds 2..16')
    state = s.get('state')
    check(isinstance(state, dict) and state, 'state object required')
    for k, v in state.items():
        check(ID.fullmatch(k) is not None, f'bad state key: {k}')
        check(type(v) in (bool, int, float, str), f'unsupported state value: {k}')
    agents = s.get('agents')
    check(isinstance(agents, list) and 2 <= len(agents) <= 6, '2..6 agents required')
    ids = [a.get('id') for a in agents]
    check(all(isinstance(x, str) and ACTOR.fullmatch(x) for x in ids), 'bad agent IDs')
    check(len(ids) == len(set(ids)), 'duplicate agent IDs')
    for a in agents:
        for field in ('role', 'personality', 'goal'):
            check(isinstance(a.get(field), str) and a[field].strip(), f'{a["id"]}: {field} required')
        check(isinstance(a.get('beliefs', []), list) and all(isinstance(v, str) for v in a.get('beliefs', [])), 'beliefs must be strings')
    facts = s.get('facts', [])
    check(isinstance(facts, list), 'facts must be a list')
    fids = set()
    for f in facts:
        check(isinstance(f, dict) and isinstance(f.get('id'), str) and ID.fullmatch(f['id']), 'bad fact ID')
        check(f['id'] not in fids, 'duplicate fact ID')
        fids.add(f['id'])
        check(isinstance(f.get('text'), str) and f['text'].strip(), 'fact needs text')
        check(isinstance(f.get('known_to'), list) and all(x in ids for x in f['known_to']), 'invalid fact known_to')
    actions = s.get('actions')
    check(isinstance(actions, list) and actions, 'actions required')
    aids = set()
    for action in actions:
        aid = action.get('id')
        check(isinstance(aid, str) and ID.fullmatch(aid), 'bad action ID')
        check(aid not in aids, 'duplicate action ID')
        aids.add(aid)
        check(isinstance(action.get('description'), str) and action['description'].strip(), f'{aid}: description required')
        check(isinstance(action.get('allowed'), list) and all(x in ids for x in action['allowed']), f'{aid}: invalid allowed')
        check(isinstance(action.get('requires', []), list), f'{aid}: requires must be a list')
        check(isinstance(action.get('effects', []), list), f'{aid}: effects must be a list')
        for req in action.get('requires', []):
            validate_condition(req, state, aid)
        for effect in action.get('effects', []):
            validate_effect(effect, state, aid)
        for fid in action.get('discover', []):
            check(fid in fids, f'{aid}: unknown evidence {fid}')
        check(isinstance(action.get('discover', []), list), f'{aid}: discover must be list')
    endings = s.get('endings')
    check(isinstance(endings, list) and endings, 'at least one named ending is required')
    names = set()
    for ending in endings:
        check(isinstance(ending, dict) and isinstance(ending.get('id'), str)
              and ID.fullmatch(ending['id']) and ending['id'] not in names, 'invalid or duplicate ending ID')
        names.add(ending['id'])
        check(isinstance(ending.get('when'), list) and ending['when'], 'ending requires conditions')
        for req in ending['when']:
            validate_condition(req, state, f"ending {ending['id']}")
    for effect in s.get('round_effects', []):
        validate_effect(effect, state, 'round_effects')
    check(isinstance(s.get('public_context', ''), str), 'public_context must be text')
    return s


def validate_condition(c, state, context):
    check(isinstance(c, dict) and c.get('key') in state and c.get('op') in OPS, f'{context}: invalid condition')
    v = state[c['key']]
    check(type(c.get('value')) == type(v) or
          (type(v) in (int, float) and type(c.get('value')) in (int, float)), f'{context}: condition type mismatch')
    check(c['op'] in {'eq', 'ne'} or type(v) in (int, float), f'{context}: ordering requires numbers')


def validate_effect(e, state, context):
    check(isinstance(e, dict) and e.get('key') in state and e.get('op') in {'set', 'inc'}, f'{context}: invalid effect')
    v = state[e['key']]
    value = e.get('value')
    if e['op'] == 'inc':
        check(type(v) in (int, float) and type(value) in (int, float), f'{context}: increment requires numbers')
    else:
        check(type(value) == type(v) or (type(v) in (int, float) and type(value) in (int, float)), f'{context}: set wrong type')


def extract_json(text):
    text = str(text).strip()
    try: return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', text, re.S)
        if m:
            try: return json.loads(m.group())
            except json.JSONDecodeError: pass
    raise ScenarioError('Agent returned invalid JSON decision')


class Engine:
    def __init__(self, scenario, seed=0):
        self.scenario = copy.deepcopy(validate(scenario))
        self.state = copy.deepcopy(scenario['state'])
        self.known = {a['id']: set() for a in scenario['agents']}
        self.facts = {f['id']: f['text'] for f in scenario.get('facts', [])}
        self.fact_ids = set(self.facts)
        self.public_facts = set()
        for f in scenario.get('facts', []):
            self.known.update({k: self.known[k] | {f['id']} for k in f['known_to']})
            if set(f['known_to']) == self.known.keys():
                self.public_facts.add(f['id'])
        self.events = []
        self.promises = []
        self.round = 1
        self.ending = None
        self.rng = random.Random(seed)
        self.id_map = {a['id']: a for a in self.scenario['agents']}
        self.stall_rounds = 0

    def legal_actions(self, actor):
        candidates = [a for a in self.scenario['actions'] if actor in a['allowed']
                      and matches(self.state, a.get('requires', []))]
        available = []
        for a in candidates:
            # Universal prevention of repeated no-op actions, including re-reading
            # evidence that is already known to the actor.
            informative = any(fid not in self.known[actor] for fid in a.get('discover', []))
            changes_state = any(
                (eff['op'] == 'inc' and eff['value'] != 0) or
                (eff['op'] == 'set' and self.state[eff['key']] != eff['value'])
                for eff in a.get('effects', []))
            if informative or changes_state:
                available.append(a)
        return available

    def observe(self, actor):
        """Agent-facing observation. Contains public truth and own private info only."""
        a = self.id_map[actor]
        return {
            'premise': self.scenario['premise'],
            'public_context': self.scenario.get('public_context', ''),
            'round': self.round,
            'state': copy.deepcopy(self.state),  # only scenario-declared public variables
            'you': {'id': actor, 'role': a['role'], 'personality': a['personality'], 'goal': a['goal']},
            'your_beliefs_not_guaranteed_true': list(a.get('beliefs', [])),
            'facts_known_to_you': {k: self.facts[k] for k in sorted(self.known[actor])},
            'available_actions': [{'id': x['id'], 'description': x['description']} for x in self.legal_actions(actor)],
            'public_events': [self.public_event(e) for e in self.events[-25:]],
            'promises_made_publicly': copy.deepcopy(self.promises),
        }

    @staticmethod
    def public_event(e):
        return {k: copy.deepcopy(v) for k, v in e.items() if k not in ('private', 'reason')}

    def record(self, actor, kind, **fields):
        ev = {'round': self.round, 'actor': actor, 'kind': kind, **fields}
        self.events.append(ev)
        return ev

    def act(self, actor, decision):
        if actor not in self.id_map:
            raise ScenarioError('unknown actor')
        if not isinstance(decision, dict):
            return self.record(actor, 'invalid', outcome='Decision was not an object')
        kind = decision.get('kind')
        said = str(decision.get('say', ''))[:350]
        if kind == 'talk':
            if not said.strip(): return self.record(actor, 'invalid', outcome='Empty public speech')
            return self.record(actor, 'talk', say=said, truth_status='UNVERIFIED_CLAIM')
        if kind == 'reveal':
            fact = decision.get('fact_id')
            if fact not in self.known[actor]:
                return self.record(actor, 'invalid', outcome='Cannot disclose fact you do not know')
            self.public_facts.add(fact)
            for know in self.known.values(): know.add(fact)
            return self.record(actor, 'reveal', fact_id=fact, verified_fact=self.facts[fact], say=said)
        if kind == 'promise':
            action_id = decision.get('action_id')
            if action_id not in {a['id'] for a in self.scenario['actions']}:
                return self.record(actor, 'invalid', outcome='Unknown promised action')
            item = {'actor': actor, 'action_id': action_id, 'round': self.round, 'fulfilled': False}
            self.promises.append(item)
            return self.record(actor, 'promise', say=said, promise=copy.deepcopy(item))
        if kind == 'action':
            action_id = decision.get('action_id')
            allowed = {a['id']: a for a in self.legal_actions(actor)}
            if action_id not in allowed:
                return self.record(actor, 'invalid', outcome='Action unavailable at this state', action_id=action_id)
            definition = allowed[action_id]
            before = copy.deepcopy(self.state)
            for effect in definition.get('effects', []):
                key = effect['key']
                if effect['op'] == 'set': self.state[key] = effect['value']
                else: self.state[key] += effect['value']
            discovered = []
            for fact_id in definition.get('discover', []):
                if fact_id not in self.known[actor]:
                    self.known[actor].add(fact_id)
                    discovered.append(fact_id)
            for p in self.promises:
                if p['actor'] == actor and p['action_id'] == action_id:
                    p['fulfilled'] = True
            changed = {k: {'from': before[k], 'to': v} for k, v in self.state.items() if before[k] != v}
            ev = self.record(actor, 'action', action_id=action_id, say=said,
                             outcome=definition['description'], changes=changed,
                             private={'discovered_fact_ids': discovered})
            # Discovery metadata stays private until voluntarily revealed.
            # Its text appears only in that actor's next observation.
            return ev
        if kind == 'wait':
            return self.record(actor, 'wait', say=said)
        return self.record(actor, 'invalid', outcome='Unknown decision kind')

    def reached_ending(self):
        for ending in self.scenario['endings']:
            if matches(self.state, ending['when']):
                return {'kind': 'scenario_condition_met', 'outcome': ending['id'], 'round': self.round}
        return None

    def advance_round(self):
        before = copy.deepcopy(self.state)
        for effect in self.scenario.get('round_effects', []):
            k = effect['key']
            if effect['op'] == 'set': self.state[k] = effect['value']
            else: self.state[k] += effect['value']
        diff = {k: {'from': before[k], 'to': v} for k, v in self.state.items() if v != before[k]}
        if diff: self.record('WORLD', 'time', changes=diff)
        self.ending = self.reached_ending()
        if not self.ending and self.round >= self.scenario['max_rounds']:
            self.ending = {'kind': 'time_limit_unresolved', 'round': self.round}
        if not self.ending:
            self.round += 1
        return self.ending

    def result(self):
        return {
            'title': self.scenario['title'], 'state': self.state, 'rounds': self.round,
            'ending': self.ending, 'events': self.events, 'promises': self.promises,
            'secret_facts_final': self.facts,
            'known_by_agent_final': {k: sorted(v) for k, v in self.known.items()},
            'warning': 'Claims are unverified; promises are recorded, not guaranteed. No agent private deliberation is disclosed.'
        }


async def live(scenario, model, max_calls):
    try:
        from agents import Agent, Runner
    except ImportError as exc:
        raise ScenarioError('Live runs require openai-agents, already used by v0.8') from exc
    check(bool(os.getenv('OPENAI_API_KEY')), 'OPENAI_API_KEY not found')
    engine = Engine(scenario)
    cast = {}
    for a in scenario['agents']:
        cast[a['id']] = Agent(
            name=a['id'], model=model,
            instructions=(
                'You are an independent fictional person making consequential choices. '
                'Pursue YOUR goal, show situational awareness, consider other agents\' incentives, '
                'revise beliefs when evidence emerges, and weigh ethical costs. '
                'You do not automatically know other agents\' secrets or private evidence. '
                'Others may lie, bluff, or be sincerely mistaken. Their statements are not verified facts. '
                'Never pretend an action occurred before the engine confirms it. '
                'Avoid corny one-liners and repetitive exposition. Speak naturally, briefly, only when useful. '
                'Choose ONE option: talk, reveal, promise, action, wait. '
                'Return ONLY JSON with keys: kind, say, action_id, fact_id. '
                'For action select exact ID from available_actions. For reveal choose a known fact ID. '
                'For promise choose a possible action ID. No other keys are required.'
            )
        )
    calls = 0
    for _ in range(scenario['max_rounds']):
        for a in scenario['agents']:
            if calls >= max_calls:
                engine.ending = {'kind': 'call_budget_exhausted', 'round': engine.round}
                return engine.result(), calls
            actor = a['id']
            observation = engine.observe(actor)
            prompt = ('Choose one consequential next step. A declaration does not alter world state. '
                      'Any discovery must be investigated and explicitly revealed if you want others to learn it. '
                      'There is no requirement to manufacture conflict.\n'
                      + json.dumps(observation, ensure_ascii=False))
            response = await Runner.run(cast[actor], prompt, max_turns=2)
            calls += 1
            try:
                decision = extract_json(response.final_output)
            except ScenarioError:
                decision = {'kind': 'wait', 'say': ''}
            engine.act(actor, decision)
            if engine.reached_ending():
                engine.ending = engine.reached_ending()
                return engine.result(), calls
        ending = engine.advance_round()
        if ending: break
    return engine.result(), calls


# Examples are only scenario data. The engine does not know what a containment
# chamber, a whistleblower, or a hospital is.
EXAMPLES = {
    'ethical_facility': {
        'title': 'The Containment Decision',
        'premise': 'A laboratory containment failure may spread into a nearby city. Three specialists have conflicting incentives. They must act under an approaching deadline; their evidence is incomplete.',
        'public_context': 'Two technicians remain inside the laboratory sector. Sealing it may kill them but protects the city. Delaying may spread the hazard. An alternative exhaust system may work if tested.',
        'max_rounds': 7,
        'state': {'round_clock': 0, 'hazard': 3, 'tested_backup': False, 'sector_sealed': False, 'backup_started': False, 'city_exposed': False},
        'agents': [
            {'id':'DIRECTOR','role':'Emergency director','personality':'Measured, controlling, reputation-conscious','goal':'Protect civilians without making an unjustified sacrifice','beliefs':['The instrument alarm is probably accurate.']},
            {'id':'ENGINEER','role':'Facilities engineer','personality':'Analytical, reserved, strongly averse to unnecessary casualties','goal':'Find a technically sound way to protect both the staff and the city','beliefs':['The alternate exhaust route could work.']},
            {'id':'ETHICIST','role':'Medical ethicist','personality':'Precise, empathetic, skeptical of authority','goal':'Keep human lives from becoming mere numbers in a rushed decision','beliefs':['Some prior alarms have been unreliable.']},
        ],
        'facts': [
            {'id':'tampered_sensor','text':'Sensor calibration was altered last week. Its alarm cannot be independently trusted.', 'known_to':['ETHICIST']},
            {'id':'backup_failure','text':'The alternate exhaust path has an untested valve that could rupture under load.', 'known_to':['ENGINEER']},
            {'id':'hidden_report','text':'A private safety report says the hazard may already be outside the sealed sector.', 'known_to':[]},
        ],
        'actions': [
            {'id':'inspect_report','description':'Read the sealed safety report; obtain evidence but spend a decision','allowed':['DIRECTOR','ENGINEER','ETHICIST'],'requires':[], 'effects':[], 'discover':['hidden_report']},
            {'id':'test_backup','description':'Test the alternative exhaust valve without releasing the hazard','allowed':['ENGINEER'],'requires':[{'key':'tested_backup','op':'eq','value':False}], 'effects':[{'key':'tested_backup','op':'set','value':True}]},
            {'id':'start_backup','description':'Use the tested exhaust route, preserving trapped staff but accepting residual risk','allowed':['ENGINEER','DIRECTOR'],'requires':[{'key':'tested_backup','op':'eq','value':True},{'key':'sector_sealed','op':'eq','value':False}], 'effects':[{'key':'backup_started','op':'set','value':True}]},
            {'id':'seal_sector','description':'Seal the sector immediately; protect the city but abandon two trapped technicians','allowed':['DIRECTOR'],'requires':[{'key':'sector_sealed','op':'eq','value':False},{'key':'backup_started','op':'eq','value':False}], 'effects':[{'key':'sector_sealed','op':'set','value':True}]},
            {'id':'release_pressure','description':'Release pressure externally to buy time, putting the city at risk','allowed':['DIRECTOR','ENGINEER'],'requires':[{'key':'city_exposed','op':'eq','value':False},{'key':'sector_sealed','op':'eq','value':False}], 'effects':[{'key':'city_exposed','op':'set','value':True},{'key':'hazard','op':'inc','value':-1}]},
        ],
        'endings':[
            {'id':'sector_sealed_staff_abandoned','when':[{'key':'sector_sealed','op':'eq','value':True}]},
            {'id':'backup_attempted','when':[{'key':'backup_started','op':'eq','value':True}]},
            {'id':'hazard_exceeded_threshold','when':[{'key':'hazard','op':'gte','value':8}]},
        ],
        'round_effects':[{'key':'round_clock','op':'inc','value':1}, {'key':'hazard','op':'inc','value':1}],
    },
    'ethics_board': {
        'title':'The Evidence Hearing',
        'premise':'An oversight committee must decide whether to publish damaging evidence about a respected leader before an urgent election. The evidence may be incomplete.',
        'public_context':'Public disclosure could prevent serious wrongdoing but may destroy an innocent career. A delay allows for verification but costs public trust.',
        'max_rounds': 6,
        'state': {'clock':0,'evidence_checked':False,'published':False,'withdrawn':False,'public_trust':5},
        'agents': [
            {'id':'EDITOR','role':'Investigative editor','personality':'Principled but ambitious','goal':'Protect the public while avoiding a false accusation','beliefs':['The leaked evidence appears credible.']},
            {'id':'LAWYER','role':'Legal counsel','personality':'Skeptical, cautious, incisive','goal':'Ensure no one is unjustly harmed by weak evidence','beliefs':['The timing of the leak is suspicious.']},
            {'id':'SOURCE','role':'Confidential source','personality':'Anxious, determined, increasingly impatient','goal':'Get misconduct exposed without endangering a witness','beliefs':['Waiting could allow evidence to disappear.']},
        ],
        'facts': [
            {'id':'original_timestamp','text':'The original file timestamp predates the alleged incident.', 'known_to':['LAWYER']},
            {'id':'witness_risk','text':'An identifiable witness faces retaliation if the raw file is published.', 'known_to':['SOURCE']},
            {'id':'document_hash','text':'An independent hash check confirms that the public copy differs from the archived original.', 'known_to':[]},
        ],
        'actions': [
            {'id':'verify_archive','description':'Verify the original archive before publication','allowed':['EDITOR','LAWYER','SOURCE'], 'requires':[{'key':'evidence_checked','op':'eq','value':False}], 'effects':[{'key':'evidence_checked','op':'set','value':True}], 'discover':['document_hash']},
            {'id':'publish_now','description':'Release the disputed evidence publicly with serious reputational consequences','allowed':['EDITOR'],'requires':[{'key':'published','op':'eq','value':False},{'key':'withdrawn','op':'eq','value':False}], 'effects':[{'key':'published','op':'set','value':True}]},
            {'id':'withdraw','description':'Decline to publish, possibly allowing hidden wrongdoing to continue','allowed':['EDITOR'],'requires':[{'key':'published','op':'eq','value':False},{'key':'withdrawn','op':'eq','value':False}], 'effects':[{'key':'withdrawn','op':'set','value':True}]},
            {'id':'request_time','description':'Publicly request more time for verification at a political cost','allowed':['EDITOR','LAWYER'], 'requires':[{'key':'public_trust','op':'gte','value':1}], 'effects':[{'key':'public_trust','op':'inc','value':-1}]},
        ],
        'endings':[
            {'id':'evidence_published','when':[{'key':'published','op':'eq','value':True}]},
            {'id':'evidence_withdrawn','when':[{'key':'withdrawn','op':'eq','value':True}]},
        ],
        'round_effects':[{'key':'clock','op':'inc','value':1}],
    },
    'family_mediation': {
        'title':'The Relocation Hearing',
        'premise':'A child needs specialized treatment. One parent wants to move to a distant city for care; the other fears losing their relationship with the child. An independent mediator must decide under uncertainty.',
        'public_context':'A relocation could increase access to care but disrupt stability and parenting contact. No one is certain what the best long-term decision is.',
        'max_rounds': 6,
        'state': {'clock':0,'independent_review_done':False,'relocation_approved':False,'local_plan_approved':False,'shared_plan_signed':False},
        'agents': [
            {'id':'PARENT_A','role':'Parent seeking relocation','personality':'Protective, determined, sensitive to criticism','goal':'Obtain the best medical care without abandoning the child’s relationships','beliefs':['Specialists in the other city offer the best care.']},
            {'id':'PARENT_B','role':'Parent resisting relocation','personality':'Patient, distrustful of promises, practical','goal':'Preserve parenting contact and ensure the child gets reliable care','beliefs':['Local care may be adequate.']},
            {'id':'MEDIATOR','role':'Independent mediator','personality':'Careful, fair, willing to challenge both parents','goal':'Reach an evidence-grounded choice rather than reward whoever argues loudest','beliefs':['Both parents are motivated by care and fear.']},
        ],
        'facts': [
            {'id':'travel_cost','text':'A verified estimate says regular trips would consume most of the family savings.', 'known_to':['PARENT_B']},
            {'id':'clinic_waitlist','text':'The distant specialist has a lengthy waitlist; a referral does not guarantee quick treatment.', 'known_to':['PARENT_A']},
            {'id':'independent_assessment','text':'The evaluator says neither option is clearly superior without a three-month clinical trial.', 'known_to':[]},
        ],
        'actions': [
            {'id':'request_review','description':'Obtain an independent clinical assessment before a binding decision','allowed':['MEDIATOR','PARENT_A','PARENT_B'],'requires':[{'key':'independent_review_done','op':'eq','value':False}], 'effects':[{'key':'independent_review_done','op':'set','value':True}], 'discover':['independent_assessment']},
            {'id':'approve_move','description':'Authorize relocation despite possible separation and uncertainty','allowed':['MEDIATOR'],'requires':[{'key':'relocation_approved','op':'eq','value':False},{'key':'local_plan_approved','op':'eq','value':False}], 'effects':[{'key':'relocation_approved','op':'set','value':True}]},
            {'id':'approve_local','description':'Require a local care plan despite possible limits on specialized care','allowed':['MEDIATOR'],'requires':[{'key':'relocation_approved','op':'eq','value':False},{'key':'local_plan_approved','op':'eq','value':False}], 'effects':[{'key':'local_plan_approved','op':'set','value':True}]},
            {'id':'sign_shared_plan','description':'Both parents agree to trial care and regular contact, but the plan is not yet a binding ruling','allowed':['PARENT_A','PARENT_B'],'requires':[{'key':'shared_plan_signed','op':'eq','value':False}], 'effects':[{'key':'shared_plan_signed','op':'set','value':True}]},
        ],
        'endings':[
            {'id':'relocation_authorized','when':[{'key':'relocation_approved','op':'eq','value':True}]},
            {'id':'local_care_required','when':[{'key':'local_plan_approved','op':'eq','value':True}]},
        ],
        'round_effects':[{'key':'clock','op':'inc','value':1}],
    },

}


def checks():
    import tempfile
    for s in EXAMPLES.values():
        validate(s)
        e = Engine(s)
        assert all('tampered_sensor' not in str(e.observe(k)) for k in e.id_map if k != 'ETHICIST') if s['title'] == 'The Containment Decision' else True
    # Verify public speech cannot modify truth or leak hidden details mechanically.
    e = Engine(EXAMPLES['ethical_facility'])
    assert 'tampered_sensor' not in e.observe('DIRECTOR')['facts_known_to_you']
    before = copy.deepcopy(e.state)
    e.act('ENGINEER', {'kind':'talk','say':'There is definitely no danger.'})
    assert e.state == before and e.events[-1]['truth_status'] == 'UNVERIFIED_CLAIM'
    # Investigation grants private information to the investigator alone.
    e.act('DIRECTOR', {'kind':'action','action_id':'inspect_report'})
    assert 'hidden_report' in e.observe('DIRECTOR')['facts_known_to_you']
    assert 'hidden_report' not in e.observe('ETHICIST')['facts_known_to_you']
    assert 'private' not in e.public_event(e.events[-1])
    assert 'inspect_report' not in [a['id'] for a in e.legal_actions('DIRECTOR')]
    # Disclosure exposes only a known fact to everyone.
    e.act('ETHICIST', {'kind':'reveal','fact_id':'tampered_sensor','say':'The sensor was altered.'})
    assert 'tampered_sensor' in e.observe('ENGINEER')['facts_known_to_you']
    assert 'backup_failure' not in e.observe('DIRECTOR')['facts_known_to_you']
    # A promise is not counted as executed until the promised action takes place.
    e.act('DIRECTOR', {'kind':'promise','action_id':'seal_sector','say':'I will seal it.'})
    assert not e.promises[-1]['fulfilled'] and not e.state['sector_sealed']
    e.act('DIRECTOR', {'kind':'action','action_id':'seal_sector'})
    assert e.promises[-1]['fulfilled'] and e.state['sector_sealed']
    # Unsupported or impossible actions change no state.
    before = copy.deepcopy(e.state)
    e.act('DIRECTOR', {'kind':'action','action_id':'seal_sector'})
    assert e.state == before and e.events[-1]['kind'] == 'invalid'
    # Round advancement concludes only at explicit conditions or a time limit.
    assert e.advance_round() == {'kind':'scenario_condition_met','outcome':'sector_sealed_staff_abandoned','round':1}
    # The same checks apply across very different domains.
    x = Engine(EXAMPLES['ethics_board'])
    x.act('LAWYER', {'kind':'action','action_id':'verify_archive'})
    assert 'document_hash' in x.observe('LAWYER')['facts_known_to_you']
    assert 'document_hash' not in x.observe('EDITOR')['facts_known_to_you']
    x.act('EDITOR', {'kind':'action','action_id':'publish_now'})
    assert x.advance_round()['outcome'] == 'evidence_published'
    family = Engine(EXAMPLES['family_mediation'])
    assert 'clinic_waitlist' not in family.observe('PARENT_B')['facts_known_to_you']
    family.act('PARENT_B', {'kind':'action','action_id':'request_review'})
    assert 'independent_assessment' in family.observe('PARENT_B')['facts_known_to_you']
    assert 'independent_assessment' not in family.observe('PARENT_A')['facts_known_to_you']
    family.act('MEDIATOR', {'kind':'action','action_id':'approve_local'})
    assert family.reached_ending()['outcome'] == 'local_care_required'
    # A distinct resolution path is recognized without changing engine code.
    alternative = Engine(EXAMPLES['ethical_facility'])
    alternative.act('ENGINEER', {'kind':'action','action_id':'test_backup'})
    alternative.act('ENGINEER', {'kind':'action','action_id':'start_backup'})
    assert alternative.reached_ending()['outcome'] == 'backup_attempted'
    # Reject a scenario with an undeclared state variable.
    bad = copy.deepcopy(EXAMPLES['ethical_facility'])
    bad['actions'][0]['effects'] = [{'key':'imaginary','op':'set','value':True}]
    try: validate(bad)
    except ScenarioError: pass
    else: raise AssertionError('invalid scenario was accepted')
    # Check deterministic state changes, no API calls.
    a = Engine(EXAMPLES['ethical_facility'])
    b = Engine(EXAMPLES['ethical_facility'])
    seq = [('ENGINEER','test_backup'), ('DIRECTOR','start_backup')]
    for actor, action in seq:
        a.act(actor, {'kind':'action','action_id':action})
        b.act(actor, {'kind':'action','action_id':action})
    assert a.state == b.state and a.events == b.events
    print('CHECK PASSED — independent knowledge, beliefs vs facts, claims, investigations, promises, deterministic consequences, illegal actions, endings, cross-genre examples. ZERO API calls.')


def main():
    p = argparse.ArgumentParser(description='AI Game Master 1.0 — ethical experiment foundation')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--examples', action='store_true')
    group.add_argument('--scenario', type=Path)
    p.add_argument('--model', default=os.getenv('OPENAI_MODEL','gpt-4.1-mini'))
    p.add_argument('--max-calls', type=int, default=24)
    args = p.parse_args()
    if args.check:
        checks()
        return
    if args.examples:
        dest = BASE / 'scenarios'
        dest.mkdir(exist_ok=True)
        for name, s in EXAMPLES.items():
            filepath = dest / (name + '_v1.json')
            if filepath.exists():
                print('EXISTS (not overwritten):', filepath)
            else:
                filepath.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding='utf-8')
                print('CREATED:', filepath)
        return
    source = args.scenario
    data = json.loads(source.read_text(encoding='utf-8'))
    validate(data)
    print('SCENARIO VALIDATED:', data['title'])
    print('Live agent decisions use API credits. Call ceiling:', args.max_calls)
    result, used = asyncio.run(live(data, args.model, args.max_calls))
    path = BASE / 'results' / ('ethical_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    path.mkdir(parents=True, exist_ok=True)
    (path / 'simulation.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    for event in result['events']:
        if event['actor'] != 'WORLD':
            print(f"ROUND {event['round']} {event['actor']}: {event['kind']} -> {event.get('outcome',event.get('say',''))[:115]}")
    print('ENDED:', result['ending'], 'API CALLS:', used, 'SAVED:', path)


if __name__ == '__main__':
    try: main()
    except (ScenarioError, json.JSONDecodeError, OSError) as err:
        print('ERROR:', err)
        raise SystemExit(1)

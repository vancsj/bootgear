"""Validate artefact review records and supporting evidence."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, TypeGuard

import yaml
from bootgear_cli.clikit import refuse
from bootgear_cli.gear import resolve_command

from engine import session

STAGES = ('inspect', 'criteria', 'assess', 'challenge', 'verify-facts', 'judge', 'coverage', 'report')
STATES = ('Meets', 'Needs change', 'Cannot judge', 'Not applicable')
KINDS = ('inspected-content', 'direct-calculation', 'observed-output', 'checked-source', 'converge-claim', 'supplied-narration', 'memory')
TYPES = ('external-fact', 'internal-observation', 'quality-judgement')
EVIDENCE_PAIRS = {
    'external-fact': ('checked-source','converge-claim','observed-output'),
    'internal-observation': ('inspected-content','supplied-narration','direct-calculation','observed-output'),
    'quality-judgement': KINDS,
}
SCHEMAS = {
    'inspect': {'audience': 'context', 'purpose': 'context', 'reader_task': 'context', 'delivery_mode': 'context', 'representations': [{'input': 'bound absolute path', 'ranges': ['inspected range'], 'status': 'complete|partial|unavailable', 'reason': 'required for incomplete access', 'derived_from': 'optional bound original path', 'provenance': 'required extraction or rendering provenance when derived_from is set'}], 'limits': ['limit']},
    'criteria': {'criteria': {'criterion ID': {'applicable': True, 'anchor': 'configured anchor', 'reason': 'applicability reason'}}},
    'assess': {'reviewer': 'fresh identity', 'fresh_context': True, 'context': ['supplied context'], 'criteria': {'criterion ID': {'state': '|'.join(STATES), 'reason': 'reason', 'evidence': ['evidence'], 'qualification': 'required for Meets with unknown context or partial inspection'}}, 'candidates': ['candidate']},
    'challenge': {'challenger': 'distinct fresh identity', 'fresh_context': True, 'criteria': {'criterion ID': {'result': 'agreed|challenged|unresolved', 'reason': 'check', 'ranges': [{'input': 'bound path', 'range': 'inspected range'}], 'searches': ['search and result']}}, 'findings': {'candidate ID': {'result': 'agreed|challenged|unresolved', 'reason': 'check'}}, 'positive_control': {'input': 'bound path', 'item': 'present text', 'result': 'search result containing item', 'representation': 'optional bound derived path with inspected provenance'}, 'missed_candidates': ['candidate'], 'limits': ['limit']},
    'verify-facts': {'slate': 'expected Converge slate', 'directory': 'absolute Converge directory', 'mappings': {'candidate ID': {'claim': 'Converge claim ID', 'observation': 'exact candidate observation', 'locator': 'exact candidate locator', 'disposition': 'kept|dropped|uncertain'}}},
    'judge': {'dispositions': {'candidate ID': {'disposition': 'kept|dropped|uncertain', 'reason': 'evidence-based reason', 'decision_ref': 'exact resolve/debate decisions ledger entry for contested kept judgement'}}},
    'coverage': {'criteria': {'criterion ID': {'state': '|'.join(STATES), 'reason': 'final reason', 'evidence': ['evidence'], 'qualification': 'required for Meets with unknown context or partial inspection'}}, 'criterion_checks': {'criterion ID': {'result': 'agreed|challenged|unresolved', 'reason': 'final-state challenger reply', 'decision_ref': 'optional real resolve/debate reference for remaining disagreement'}}, 'disposition_checks': {'candidate ID': {'result': 'agreed|challenged|unresolved', 'reason': 'challenger reply'}}, 'challenger': 'same challenger', 'limits': ['all inspection limits']},
    'report': {'synthesis': [{'statement': 'purpose and inspected scope', 'references': ['criterion ID or candidate ID'], 'challenge': 'agreed|challenged|unresolved', 'reason': 'challenger check'}], 'challenger': 'same challenger'},
}
DETAILS = {'context': {'value': 'nonempty statement', 'basis': 'supplied|inferred|unknown'}, 'evidence': {'kind': '|'.join(KINDS), 'claim_type': '|'.join(TYPES), 'locator': 'precise source', 'observation': 'observed support'}, 'candidate': {'id': 'stable ID', 'criterion': 'active ID', 'locator': 'precise location; factual observations use an absolute source path:line', 'observation': 'observed defect', 'refutation': 'attempt and result', 'impact': 'reader impact', 'severity': 'Critical|Worth fixing|Minor', 'claim_type': '|'.join(TYPES), 'evidence': ['evidence'], 'reader_outcome': 'Critical: understanding|decision|action', 'reader_outcome_ref': 'Critical: inspect.reader_task or inspect.purpose', 'impact_evidence': ['evidence']}}


def fail(problems):
    if problems:
        refuse('artefact review refused; nothing written', [('artefact', p) for p in problems])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read(path) -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        refuse(f'cannot read {path}: {exc}; run prepare first when storage is missing')


def text(value) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def shape(value, required, optional=(), label='record'):
    if not isinstance(value, dict):
        return [f'{label}: must be a mapping']
    return ([f'{label}: missing {key}' for key in required if key not in value]
            + [f'{label}: unknown field {key}' for key in value if key not in {*required, *optional}])


def active(binding):
    return {k:v for k,v in binding['configuration']['effective']['rubric']['criteria'].items() if v.get('enabled',True)}


def evidence(value, label, *, certainty=True):
    problems = []
    if not isinstance(value, list) or not value:
        return [f'{label}: requires typed evidence']
    for index,row in enumerate(value):
        name = f'{label}[{index}]'
        problems += shape(row, ('kind','claim_type','locator','observation'), label=name)
        if not isinstance(row,dict):
            continue
        if row.get('kind') not in KINDS or row.get('claim_type') not in TYPES:
            problems.append(f'{name}: invalid evidence kind or claim type')
        for key in ('locator','observation'):
            if not text(row.get(key)):
                problems.append(f'{name}.{key}: requires text')
        if row.get('claim_type') in EVIDENCE_PAIRS and row.get('kind') not in EVIDENCE_PAIRS[row['claim_type']]:
            problems.append(f'{name}: evidence kind cannot support the declared claim type')
    if certainty and all(isinstance(row,dict) and row.get('kind') == 'memory' for row in value):
        problems.append(f'{label}: memory-only certainty is not supported')
    return problems


def candidate(value, criteria, inspection):
    problems = shape(value, ('id','criterion','locator','observation','refutation','impact','severity','claim_type','evidence'), ('reader_outcome','reader_outcome_ref','impact_evidence'), 'candidate')
    if not isinstance(value,dict):
        return problems
    for key in ('id','locator','observation','refutation','impact'):
        if not text(value.get(key)):
            problems.append(f'candidate.{key}: requires text')
    if value.get('criterion') not in criteria:
        problems.append('candidate: unknown criterion')
    if value.get('severity') not in ('Critical','Worth fixing','Minor') or value.get('claim_type') not in TYPES:
        problems.append('candidate: invalid severity or claim type')
    problems += evidence(value.get('evidence'), f"candidate {value.get('id')} evidence")
    if isinstance(value.get('evidence'),list) and not any(isinstance(row,dict) and row.get('claim_type') == value.get('claim_type') for row in value['evidence']):
        problems.append('candidate: evidence must support its declared claim type')
    if value.get('severity') == 'Critical':
        if value.get('reader_outcome') not in ('understanding','decision','action'):
            problems.append('Critical: requires an inspected reader outcome')
        reference = value.get('reader_outcome_ref')
        if reference not in ('inspect.reader_task','inspect.purpose') or inspection.get(reference.split('.')[-1],{}).get('basis') == 'unknown':
            problems.append('Critical: requires a reference to an inspected reader outcome')
        problems += evidence(value.get('impact_evidence'), 'Critical impact evidence')
    return problems


def candidates(prior):
    return prior['assess']['data']['candidates'] + prior['challenge']['data']['missed_candidates']


def check_rows(rows, ids, label):
    if not isinstance(rows, dict):
        return [f'{label}: requires a keyed mapping']
    return [f'{label}: missing {key}' for key in ids if key not in rows] + [f'{label}: unknown {key}' for key in rows if key not in ids]


def checks(rows, ids, label, optional=()):
    problems = check_rows(rows, ids, label)
    if isinstance(rows,dict):
        for key,row in rows.items():
            problems += shape(row, ('result','reason'), optional, label=f'{label}.{key}')
            if isinstance(row,dict) and (row.get('result') not in ('agreed','challenged','unresolved') or not text(row.get('reason'))):
                problems.append(f'{label}.{key}: needs a result and reason')
    return problems


def decision_recorded(binding, reference):
    if not isinstance(reference, str) or not reference.strip():
        return False
    decisions = session._section_body(Path(binding['ledger']).read_text(), 'decisions')
    pattern = r'^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} \[(?:resolve|debate|debate-capped|debate-degraded)\](?:\s|$)'
    return any(reference.strip() == line.strip() and re.match(pattern,line) for line in decisions.splitlines())


def state_rows(rows, criteria, applicability, inspection):
    problems = check_rows(rows, criteria, 'criteria')
    if not isinstance(rows,dict):
        return problems
    incomplete = any(row['status'] != 'complete' for row in inspection['representations'])
    unknown = any(inspection[key]['basis'] == 'unknown' for key in ('audience','purpose','reader_task','delivery_mode'))
    for key,row in rows.items():
        problems += shape(row, ('state','reason','evidence'), ('qualification',), label=key)
        if not isinstance(row,dict):
            continue
        state = row.get('state')
        if state not in STATES:
            problems.append(f'{key}: invalid state')
        expected = applicability.get(key, {}).get('applicable')
        if (state == 'Not applicable') != (expected is False):
            problems.append(f'{key}: applicability disagrees with criteria')
        if state in ('Meets','Needs change'):
            problems += evidence(row.get('evidence'), key)
        elif not isinstance(row.get('evidence'),list):
            problems.append(f'{key}: evidence must be a list, including an explicit empty list')
        elif row['evidence']:
            problems += evidence(row['evidence'],key,certainty=False)
        if state in ('Cannot judge','Not applicable') and not text(row.get('reason')):
            problems.append(f'{key}: needs a precise reason')
        if state == 'Meets' and (incomplete or unknown) and not text(row.get('qualification')):
            problems.append(f'{key}: incomplete inspection or unknown context cannot support unqualified Meets')
    return problems


def public_converge(stage, slate, directory):
    command = resolve_command("converge")
    if command is None:
        program = shutil.which("converge")
        command = [program] if program else None
    if command is None:
        refuse('public Converge command is unavailable')
    completed = subprocess.run([*command, stage, slate, '--dir', str(directory), '--json'],
                               text=True, capture_output=True, check=False)
    fail([] if completed.returncode == 0 else [f'Converge {stage}: {completed.stderr or completed.stdout}'])
    try:
        result = json.loads(completed.stdout)
    except ValueError:
        refuse(f'Converge {stage}: invalid JSON output')
    fail([] if result.get('slate') == slate else ['Converge returned a different slate'])
    return result


def validate(stage, data, binding, prior):
    problems = shape(data, SCHEMAS[stage].keys())
    if problems:
        return problems
    criteria = active(binding)
    inspected = prior.get('inspect',{}).get('data',{})
    if stage == 'inspect':
        for key in ('audience','purpose','reader_task','delivery_mode'):
            row = data[key]
            problems += shape(row, ('value','basis'), label=key)
            if isinstance(row,dict) and (not text(row.get('value')) or row.get('basis') not in ('supplied','inferred','unknown')):
                problems.append(f'{key}: needs value and supplied/inferred/unknown basis')
        rows = data['representations']
        if not isinstance(rows,list):
            return problems + ['representations: needs a list']
        seen = []
        for row in rows:
            problems += shape(row, ('input','ranges','status'), ('reason','derived_from','provenance'), 'representation')
            if not isinstance(row,dict):
                continue
            seen.append(row.get('input'))
            if 'derived_from' in row and (row['derived_from'] not in binding['inputs'] or row['derived_from'] == row.get('input') or not text(row.get('provenance'))):
                problems.append('derived representation needs a distinct bound original and extraction provenance')
            if 'provenance' in row and not text(row['provenance']):
                problems.append('representation provenance requires text')
            if row.get('status') not in ('complete','partial','unavailable'):
                problems.append('representation: invalid access status')
            if row.get('status') != 'complete' and not text(row.get('reason')):
                problems.append('representation: incomplete access needs a reason')
            if row.get('status') != 'unavailable' and (not isinstance(row.get('ranges'),list) or not row['ranges'] or not all(map(text,row['ranges']))):
                problems.append('representation: needs inspected ranges')
        if sorted(str(x) for x in seen) != sorted(binding['inputs']):
            problems.append('representations must account for every bound input exactly once')
    elif stage == 'criteria':
        problems += check_rows(data['criteria'], criteria, 'criteria')
        if isinstance(data['criteria'],dict):
            for key,row in data['criteria'].items():
                problems += shape(row, ('applicable','anchor','reason'), label=key)
                if isinstance(row,dict):
                    if not isinstance(row.get('applicable'),bool) or not text(row.get('reason')):
                        problems.append(f'{key}: needs applicability and reason')
                    if key in criteria and row.get('anchor') not in (criteria[key]['meets'], criteria[key]['needs_change'], criteria[key]['applies_when']):
                        problems.append(f'{key}: anchor must cite a configured anchor')
    elif stage == 'assess':
        if not text(data['reviewer']) or data['fresh_context'] is not True or not isinstance(data['context'],list):
            problems.append('assessment needs fresh reviewer identity and supplied context list')
        problems += state_rows(data['criteria'], criteria, prior['criteria']['data']['criteria'], inspected)
        if not isinstance(data['candidates'],list):
            problems.append('candidates must be an explicit list')
        else:
            for row in data['candidates']:
                problems += candidate(row, criteria, inspected)
            ids = [row.get('id') for row in data['candidates'] if isinstance(row,dict)]
            if len(ids) != len(set(ids)):
                problems.append('candidate IDs must be unique')
    elif stage == 'challenge':
        if not text(data['challenger']) or data['challenger'] == prior['assess']['data']['reviewer'] or data['fresh_context'] is not True:
            problems.append('challenge needs a distinct fresh challenger')
        problems += check_rows(data['criteria'], criteria, 'challenge.criteria')
        if isinstance(data['criteria'],dict):
            for key,row in data['criteria'].items():
                problems += shape(row, ('result','reason','ranges','searches'), label=key)
                if not isinstance(row,dict):
                    continue
                problems += checks({key:{k:v for k,v in row.items() if k in ('result','reason')}}, [key], key)
                if not isinstance(row.get('searches'),list) or not row['searches'] or not all(map(text,row['searches'])):
                    problems.append(f'{key}: needs sweep searches with results')
                ranges = row.get('ranges')
                if not isinstance(ranges,list) or not ranges:
                    problems.append(f'{key}: needs inspected ranges for the full requested scope')
                elif {r.get('input') for r in ranges if isinstance(r,dict)} != set(binding['inputs']) or any(not isinstance(r,dict) or set(r) != {'input','range'} or not text(r.get('range')) for r in ranges):
                    problems.append(f'{key}: ranges must account for every bound input')
        findings = prior['assess']['data']['candidates']
        problems += checks(data['findings'], [x['id'] for x in findings], 'findings')
        control = data['positive_control']
        problems += shape(control, ('input','item','result'), ('representation',), label='positive_control')
        if isinstance(control,dict):
            if control.get('input') not in binding['inputs'] or not text(control.get('item')) or not text(control.get('result')):
                problems.append('positive_control needs bound input, item and result')
            else:
                target = control.get('representation',control['input'])
                linked = target == control['input'] or any(row['input'] == target and row.get('derived_from') == control['input'] and text(row.get('provenance')) for row in inspected['representations'])
                if target not in binding['inputs'] or not linked:
                    problems.append('positive_control representation needs bound input and inspected source provenance')
                    content = b''
                else:
                    content = Path(target).read_bytes()
                if control['item'].encode() not in content or control['item'] not in control['result']:
                    problems.append('positive_control item must occur in actual input and recorded result')
        if not isinstance(data['missed_candidates'],list):
            problems.append('missed_candidates requires an explicit list, including empty results')
        else:
            for row in data['missed_candidates']:
                problems += candidate(row,criteria, inspected)
            ids = [r.get('id') for r in [*findings,*data['missed_candidates']] if isinstance(r,dict)]
            if len(ids) != len(set(ids)):
                problems.append('candidate IDs must be unique across assessment and sweep')
    elif stage == 'verify-facts':
        factual = [x for x in candidates(prior) if x['claim_type'] != 'quality-judgement']
        problems += check_rows(data['mappings'], [x['id'] for x in factual], 'mappings')
        if not text(data['slate']) or data['slate'].startswith('-') or not text(data['directory']) or not Path(data['directory']).is_absolute():
            problems.append('facts need expected slate and absolute directory')
        if not problems:
            public_converge('gate', data['slate'], data['directory'])
            rendered = public_converge('render', data['slate'], data['directory'])
            status = public_converge('status', data['slate'], data['directory'])
            claims = {x['id']:x for x in status.get('claims',[])}
            rendered_ids = {x['id'] for x in rendered.get('claims',[])}
            for row in factual:
                mapping = data['mappings'][row['id']]
                problems += shape(mapping, ('claim','observation','locator','disposition'), label=row['id'])
                if not isinstance(mapping,dict):
                    continue
                claim = claims.get(mapping.get('claim'),{})
                if mapping.get('observation') != row['observation'] or mapping.get('locator') != row['locator'] or claim.get('claim') != row['observation'] or claim.get('loc') != row['locator'] or mapping.get('claim') not in rendered_ids:
                    problems.append(f"{row['id']}: claim ID, observation and locator must match actual Converge output")
                disposition = mapping.get('disposition')
                if disposition not in ('kept','dropped','uncertain') or (disposition == 'kept' and claim.get('status') != 'survived'):
                    problems.append(f"{row['id']}: disposition disagrees with actual claim status")
    elif stage == 'judge':
        all_candidates = candidates(prior)
        problems += check_rows(data['dispositions'], [x['id'] for x in all_candidates], 'dispositions')
        if not isinstance(data['dispositions'],dict):
            return problems
        for row in all_candidates:
            result = data['dispositions'].get(row['id'],{})
            problems += shape(result, ('disposition','reason'), ('decision_ref',), row['id'])
            if not isinstance(result,dict):
                continue
            if result.get('disposition') not in ('kept','dropped','uncertain') or not text(result.get('reason')):
                problems.append(f"{row['id']}: requires explicit disposition and reason")
            if row['claim_type'] != 'quality-judgement':
                if result.get('disposition') != prior['verify-facts']['data']['mappings'][row['id']]['disposition']:
                    problems.append(f"{row['id']}: facts cannot be changed by judgement")
            else:
                challenged = prior['challenge']['data']['findings'].get(row['id'],{}).get('result') in ('challenged','unresolved')
                if challenged and result.get('disposition') == 'kept':
                    ref = result.get('decision_ref')
                    if not decision_recorded(binding,ref):
                        problems.append(f"{row['id']}: contested kept judgement needs a real resolve/debate decision reference")
    elif stage == 'coverage':
        problems += state_rows(data['criteria'], criteria, prior['criteria']['data']['criteria'], inspected)
        problems += checks(data['criterion_checks'], criteria, 'criterion_checks', ('decision_ref',))
        if isinstance(data['criterion_checks'], dict) and isinstance(data['criteria'], dict):
            for key, check in data['criterion_checks'].items():
                if isinstance(check, dict) and check.get('result') != 'agreed':
                    state = data['criteria'].get(key, {}).get('state')
                    if state != 'Cannot judge' and not decision_recorded(binding, check.get('decision_ref')):
                        problems.append(f'{key}: remaining criterion disagreement needs Cannot judge or a real resolve/debate decision')
        all_candidates = candidates(prior)
        problems += checks(data['disposition_checks'], [x['id'] for x in all_candidates], 'disposition_checks')
        if not isinstance(data['criteria'],dict) or not isinstance(data['disposition_checks'],dict):
            return problems
        if data['challenger'] != prior['challenge']['data']['challenger']:
            problems.append('coverage must record the same challenger reply')
        for row in all_candidates:
            disposition = prior['judge']['data']['dispositions'][row['id']]['disposition']
            state = data['criteria'].get(row['criterion'],{}).get('state')
            check = data['disposition_checks'].get(row['id'],{})
            if disposition == 'kept' and state != 'Needs change':
                problems.append(f"{row['id']}: kept defect requires Needs change")
            if disposition == 'uncertain' and state == 'Meets':
                problems.append(f"{row['id']}: uncertain defect cannot support unqualified Meets")
            decision = prior['judge']['data']['dispositions'][row['id']].get('decision_ref')
            if check.get('result') != 'agreed' and disposition != 'uncertain' and not decision_recorded(binding,decision):
                problems.append(f"{row['id']}: remaining disagreement needs explicit uncertainty or a real resolve/debate decision")
        required_limits = inspected['limits'] + prior['challenge']['data']['limits']
        if not isinstance(data['limits'],list) or any(x not in data['limits'] for x in required_limits):
            problems.append('coverage must preserve every inspection and challenge limit')
    elif stage == 'report':
        if data['challenger'] != prior['challenge']['data']['challenger']:
            problems.append('report synthesis needs the same challenger')
        rows = data['synthesis']
        if not isinstance(rows,list) or not rows:
            problems.append('synthesis needs cited statement records')
        else:
            allowed = set(criteria) | {x['id'] for x in candidates(prior)}
            for row in rows:
                problems += shape(row, ('statement','references','challenge','reason'), label='synthesis')
                if not isinstance(row,dict):
                    continue
                if not text(row.get('statement')) or not isinstance(row.get('references'),list) or not row['references'] or any(not isinstance(x,str) or x not in allowed for x in row['references']) or row.get('challenge') not in ('agreed','challenged','unresolved') or not text(row.get('reason')):
                    problems.append('synthesis needs valid references and an explicit challenge check')
    if 'limits' in data and (not isinstance(data['limits'],list) or not all(map(text,data['limits']))):
        problems.append('limits must be an explicit list of text')
    return problems

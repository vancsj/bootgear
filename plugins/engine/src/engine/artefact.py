"""Recorded artefact review, input binding, and stage gates."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml
from bootgear_cli import clikit
from bootgear_cli.clikit import caller_cwd, caller_path, emit, refuse

from engine import config, session
from engine.artefact_validation import (
    DETAILS,
    EVIDENCE_PAIRS,
    KINDS,
    SCHEMAS,
    STAGES,
    STATES,
    TYPES,
    candidates,
    digest,
    fail,
    read,
    shape,
    text,
    validate,
)


def write(path, value):
    session._write_atomic(path, json.dumps(value, indent=2, sort_keys=True) + '\n')


def resolve(project, task=None):
    default_path = Path(__file__).resolve().parents[2] / 'references/artefact-review.yaml'
    defaults = read(default_path)
    layers = config.resolve('artefact-review', project, None, None, task, False)
    effective = config._merge(defaults, layers['effective'])
    problems = shape(effective, ('rubric', 'find_angles', 'report'), label='configuration')
    rubric = effective.get('rubric', {}) if isinstance(effective, dict) else {}
    problems += shape(rubric, ('criteria', 'guidance'), label='rubric')
    criteria = rubric.get('criteria', {}) if isinstance(rubric, dict) else {}
    if not isinstance(criteria, dict) or not criteria:
        problems.append('rubric.criteria: needs nonempty keyed criteria')
        criteria = {}
    angles = effective.get('find_angles', {})
    if not isinstance(angles, dict):
        problems.append('find_angles: needs keyed angles')
        angles = {}
    for name, entries, fields in (('criteria', criteria, ('label','applies_when','meets','needs_change')), ('find_angles', angles, ('tell','asks'))):
        for key, row in entries.items():
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', key):
                problems.append(f'{name}: invalid ID {key!r}')
            problems += shape(row, (), (*fields, 'enabled', 'reason'), f'{name}.{key}')
            if not isinstance(row, dict):
                continue
            if row.get('enabled', True) is False:
                if not text(row.get('reason')):
                    problems.append(f'{name}.{key}: disabled entries need a reason')
            else:
                for field in fields:
                    if not (text(row.get(field)) or (field == 'asks' and isinstance(row.get(field), list) and row[field] and all(map(text,row[field])))):
                        problems.append(f'{name}.{key}.{field}: needs content')
            if 'enabled' in row and not isinstance(row['enabled'], bool):
                problems.append(f'{name}.{key}.enabled: must be boolean')
    if not any(v.get('enabled', True) for v in criteria.values() if isinstance(v, dict)):
        problems.append('rubric: no active criteria')
    if not isinstance(rubric.get('guidance'), list) or not all(map(text,rubric.get('guidance', []))):
        problems.append('rubric.guidance: needs a list of text')
    problems += shape(effective.get('report'), (), label='report configuration')
    fail(problems)
    rows = [{'id': key, 'tag': 'find', 'lens': 'artefact', 'tell': row['tell'], 'asks': row['asks']} for key,row in angles.items() if row.get('enabled',True)]
    return {'effective': effective, 'default_digest': digest(defaults), 'effective_digest': digest(effective), 'sources': layers['sources'], 'overrides': layers['effective'], 'angles': rows}


def hashes(inputs):
    result = {}
    problems = []
    for name in inputs:
        try:
            result[name] = hashlib.sha256(Path(name).read_bytes()).hexdigest()
        except OSError as exc:
            problems.append(f'input {name}: {exc}')
    fail(problems)
    return result


def load(folder):
    root = folder.resolve() / 'artefact-review'
    manifest = read(root / 'current.json')
    fail([] if isinstance(manifest, dict) else ['invalid prepare binding'])
    revision = root / manifest['revision']
    binding = read(revision / 'binding.json')
    fail([] if hashes(binding['inputs']) == binding['inputs'] else ['inputs changed; prepare --refresh --reason is required'])
    return root, revision, binding


def records(revision, until=None):
    result = {}
    for stage in STAGES:
        path = revision / f'{stage}.json'
        if not path.exists():
            if until is not None:
                fail([f'missing prerequisite {stage}; record it first'])
            break
        record = read(path)
        expected = {k: digest(v) for k,v in result.items()}
        fail([] if record['prerequisites'] == expected else [f'{stage}: stale prerequisites; record it again'])
        result[stage] = record
        if stage == until:
            break
    return result


def cmd_settings(args):
    if args.task_folder is not None:
        fail([] if args.task_config_file is None else ['bound settings cannot accept a live task config override'])
        _,revision,binding = load(args.task_folder)
        resolved = {**binding['configuration'], 'revision':revision.name, 'inputs':binding['inputs'], 'request':binding['request']}
        next_step = 'main agent: hand the frozen stage schema and supplied context to the assigned reviewer'
    else:
        resolved = resolve(args.project_root,args.task_config_file)
        next_step = 'main agent: prepare the bound run, then hand inspection to the reviewer'
    result = {**resolved, 'states': STATES, 'evidence_kinds': KINDS, 'claim_types': TYPES, 'allowed_evidence_pairs': EVIDENCE_PAIRS, 'schemas': SCHEMAS, 'definitions': DETAILS}
    emit(args.output_mode,result,[f'ARTEFACT settings digest={resolved["effective_digest"]}',json.dumps(result,indent=2,ensure_ascii=False)],next_step)


def cmd_prepare(args):
    run_id = clikit.session_id(args.run_id or None)
    if not text(run_id):
        refuse(clikit.missing_session('<run-id>'))
    ledger = session._ledger_path(run_id,args.dir)
    raw = ledger.read_text()
    session._check_open(raw,ledger)
    settlement = yaml.safe_load(session._section_body(raw,'settlement'))
    problems = session._artefact_review_problems(settlement,settlement.get('task_type'))
    if settlement.get('task_type') != 'artefact-review':
        problems.append(('task_type','prepare needs an artefact-review run'))
    fail([f'{k}: {v}' for k,v in problems])
    folder = Path(settlement['task_folder']).expanduser().resolve()
    if args.task_folder is not None:
        fail([] if folder == args.task_folder.resolve() else ['task folder differs from reserved binding'])
    review = settlement['artefact_review']
    project = Path(settlement.get('project_root') or caller_cwd()).expanduser().resolve()
    inputs = [str(Path(x).expanduser().resolve()) for x in review['inputs']]
    storage = folder/'artefact-review'
    fail([f'input {name}: review storage cannot also be an input' for name in inputs if Path(name).is_relative_to(storage)])
    configuration = resolve(project,Path(review['config']).expanduser() if review.get('config') else None)
    binding = {'run_id':run_id,'ledger':str(ledger.resolve()),'project_root':str(project),'task_folder':str(folder),'request':review['request'],'inputs':hashes(inputs),'configuration':configuration}
    root = folder/'artefact-review'
    current = root/'current.json'
    if current.exists():
        previous = read(current)
        old = read(root/previous['revision']/'binding.json')
        if {k:v for k,v in old.items() if k != 'refresh_reason'} == binding and not args.refresh:
            emit(args.output_mode,{'revision':previous['revision']},'ARTEFACT already prepared','main agent: hand inspect schema to the reviewer')
            return
        fail([] if args.refresh and text(args.reason) else ['binding changed; use prepare --refresh --reason'])
        fail([] if all(old[k] == binding[k] for k in ('run_id','ledger','project_root','task_folder','request')) else ['refresh cannot change run, project, folder or request binding'])
    elif args.refresh:
        fail(['refresh needs an existing preparation'])
    number = 1
    while (root/f'revision-{number:04d}').exists():
        number += 1
    revision = f'revision-{number:04d}'
    target = root/revision
    target.mkdir(parents=True)
    binding['refresh_reason'] = args.reason if args.refresh else None
    write(target/'binding.json',binding)
    (target/'angles.yaml').write_text(yaml.safe_dump(configuration['angles'],sort_keys=False))
    write(current,{'revision':revision})
    emit(args.output_mode,{'revision':revision,'binding':binding,'angles_file':str(target/'angles.yaml')},f'ARTEFACT prepared {revision}','main agent: hand inspect schema to the reviewer')


def cmd_record(args):
    _,revision,binding = load(args.task_folder)
    index = STAGES.index(args.stage)
    prior = records(revision,STAGES[index-1]) if index else {}
    data = read(args.record_file)
    fail(validate(args.stage,data,binding,prior))
    record = {'stage':args.stage,'data':data,'prerequisites':{key:digest(value) for key,value in prior.items()}}
    version = 1
    while (revision/f'{args.stage}.{version:04d}.json').exists():
        version += 1
    write(revision/f'{args.stage}.{version:04d}.json',record)
    write(revision/f'{args.stage}.json',record)
    emit(args.output_mode,{'stage':args.stage,'version':version},f'ARTEFACT recorded {args.stage} version={version}','reviewer: return the recorded stage to the main agent for its transition')


def rendered(binding, prior):
    data = {stage:row['data'] for stage,row in prior.items()}
    snapshot = binding['configuration']
    lines = ['# Artefact review', '', binding['request'], '', '## Quality synthesis', '']
    for row in data['report']['synthesis']:
        lines.append(f"- {row['statement']} [{', '.join(row['references'])}] ({row['challenge']}: {row['reason']})")
    lines += ['', '## Criterion states', '']
    for key,row in data['coverage']['criteria'].items():
        label = snapshot['effective']['rubric']['criteria'][key]['label']
        lines.append(f"- {label} ({key}): {row['state']}. {row['reason']}")
        check = data['coverage']['criterion_checks'][key]
        lines.append(f"  Challenger: {check['result']}. {check['reason']}")
        if check.get('decision_ref'):
            lines.append(f"  Decision: {check['decision_ref']}")
        if row.get('qualification'):
            lines.append(f"  Qualification: {row['qualification']}")
        for item in row['evidence']:
            lines.append(f"  - {item['kind']} / {item['claim_type']}: {item['locator']}: {item['observation']}")
    all_candidates = candidates(prior)
    for disposition,title in (('kept','Retained findings'),('dropped','Dropped candidates'),('uncertain','Uncertain candidates')):
        lines += ['', f'## {title}', '']
        selected = [row for row in all_candidates if data['judge']['dispositions'][row['id']]['disposition'] == disposition]
        if not selected:
            lines.append('None recorded.')
        for row in selected:
            verdict = data['judge']['dispositions'][row['id']]
            lines.append(f"- {row['id']} [{row['criterion']}] {row['severity']}: {row['observation']} ({row['locator']})")
            lines.append(f"  Reader impact: {row['impact']}. Refutation: {row['refutation']}")
            lines.append(f"  Disposition: {verdict['reason']}")
            reply = data['coverage']['disposition_checks'][row['id']]
            lines.append(f"  Challenger reply: {reply['result']}. {reply['reason']}")
            if verdict.get('decision_ref'):
                lines.append(f"  Decision: {verdict['decision_ref']}")
            for item in row['evidence']:
                lines.append(f"  Evidence: {item['kind']} / {item['claim_type']}: {item['locator']}: {item['observation']}")
            if row['severity'] == 'Critical':
                lines.append(f"  Reader outcome: {row['reader_outcome']} [{row['reader_outcome_ref']}]")
                for item in row['impact_evidence']:
                    lines.append(f"  Impact reference: {item['locator']}: {item['observation']} ({item['kind']})")
    lines += ['', '## Context and inspection limits', '']
    for key in ('audience','purpose','reader_task','delivery_mode'):
        row = data['inspect'][key]
        lines.append(f"- {key}: {row['value']} ({row['basis']})")
    for row in data['inspect']['representations']:
        lines.append(f"- {row['input']}: {row['status']}; ranges: {', '.join(row['ranges'])}; {row.get('reason','')}")
        if row.get('derived_from'):
            lines.append(f"  Derived from: {row['derived_from']}; provenance: {row['provenance']}")
    lines += [f'- {limit}' for limit in data['coverage']['limits']]
    if not data['coverage']['limits']:
        lines.append('No further limits recorded.')
    lines += ['', '## Review configuration', '', f"Default digest: {snapshot['default_digest']}", f"Effective digest: {snapshot['effective_digest']}", '', 'Overrides:', '```json', json.dumps(snapshot['overrides'],indent=2,ensure_ascii=False), '```', '', 'Configuration sources:', '```json', json.dumps(snapshot['sources'],indent=2,ensure_ascii=False), '```', '', 'Input digests:', '```json', json.dumps(binding['inputs'],indent=2,ensure_ascii=False), '```']
    return '\n'.join(lines) + '\n'


def cmd_report(args):
    _,revision,binding = load(args.task_folder)
    prior = records(revision,'report')
    for stage in STAGES:
        fail(validate(stage,prior[stage]['data'],binding,{k:v for k,v in prior.items() if STAGES.index(k)<STAGES.index(stage)}))
    report = rendered(binding,prior)
    path = revision/'report.md'
    session._write_atomic(path,report)
    write(revision/'report-proof.json',{'digest':hashlib.sha256(report.encode()).hexdigest(),'records':digest(prior)})
    emit(args.output_mode,{'report':str(path)},f'ARTEFACT report {path}','main agent: run artefact gate --stage report, then return the report and limits to the user')


def cmd_gate(args):
    _,revision,binding = load(args.task_folder)
    prior = records(revision,args.stage)
    for stage,row in prior.items():
        fail(validate(stage,row['data'],binding,{k:v for k,v in prior.items() if STAGES.index(k)<STAGES.index(stage)}))
    if args.stage == 'report':
        expected = rendered(binding,prior)
        path = revision/'report.md'
        fail([] if path.exists() and path.read_text() == expected else ['report missing or stale; run artefact report'])
    emit(args.output_mode,{'stage':args.stage,'ok':True},f'ARTEFACT gate passed {args.stage}','main agent: transition from the checked stage')


def add_subparsers(sub, dir_parent):
    parser = sub.add_parser('settings',help='show resolved rubric, evidence rules and exact stage schemas')
    parser.add_argument('--project-root',type=caller_path,default=caller_cwd(),help='project root for layered rubric configuration')
    parser.add_argument('--task-config-file',type=caller_path,help='task rubric YAML override')
    parser.add_argument('--task-folder',type=caller_path,help='read the prepared configuration snapshot')
    parser.set_defaults(func=cmd_settings)
    parser = sub.add_parser('prepare',parents=[dir_parent],help='bind a review to its run and input revision')
    parser.add_argument('run_id',nargs='?',help=session.RUN_ID_HELP)
    parser.add_argument('--task-folder',type=caller_path,help='must match the run settlement task folder')
    parser.add_argument('--refresh',action='store_true',help='capture changed input or configuration; requires existing preparation and --reason')
    parser.add_argument('--reason',help='required with --refresh; explains the changed evidence binding')
    parser.set_defaults(func=cmd_prepare)
    for name,func in (('record',cmd_record),('gate',cmd_gate),('report',cmd_report)):
        parser = sub.add_parser(name,help=f'{name} validated review evidence')
        parser.add_argument('--task-folder',type=caller_path,required=True,help='fixed folder containing prepared review evidence')
        if name != 'report':
            parser.add_argument('--stage',choices=STAGES,required=True,help='evidence stage; its prerequisites must pass')
        if name == 'record':
            parser.add_argument('--record-file',type=caller_path,required=True,help='JSON stage record; artefact settings prints its exact schema')
        parser.set_defaults(func=func)

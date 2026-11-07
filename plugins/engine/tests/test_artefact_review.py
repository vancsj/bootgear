"""Public artefact review contracts."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
TASK = PLUGIN / ('bin/task' if (PLUGIN / 'bin/task').exists() else 'scripts/task')

class ArtefactReviewTest(unittest.TestCase):
    def command(self, *args, cwd=None):
        env = {k:v for k,v in os.environ.items() if k not in {'BOOTGEAR_SESSION_ID', 'GEAR_CALLER_CWD', 'VIRTUAL_ENV'}}
        return subprocess.run([str(TASK), 'artefact', *args, '--json'], text=True, capture_output=True, cwd=cwd, env=env, check=False)

    def test_settings_has_complete_public_schemas(self):
        result = self.command('settings')
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(set(value['schemas']), {'inspect','criteria','assess','challenge','verify-facts','judge','coverage','report'})
        self.assertEqual(len(value['states']), 4)

    def test_missing_prepare_blocks_record_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder/'record.json'
            source.write_text('{}')
            result = self.command('record', '--task-folder', temp, '--stage','inspect','--record-file',str(source))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('prepare', result.stderr)
            self.assertFalse((folder/'artefact-review').exists())

    def test_usage_explains_correction(self):
        result = self.command('record')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('example', result.stderr.lower())

class ArtefactProgressionTest(unittest.TestCase):
    def setUp(self):
        from settlement_fixture import valid_settlement
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.folder = self.root/'task'
        self.sessions = self.root/'sessions'
        self.input = self.root/'input.txt'
        self.input.write_text('Present control. The reader can follow the guide.\n')
        self.env = {k:v for k,v in os.environ.items() if k not in {'BOOTGEAR_SESSION_ID','GEAR_CALLER_CWD','VIRTUAL_ENV','PLUGIN_ROOT'}}
        machine = 'name: fixture\nnodes:\n  clarify:\n    next: [succeeded]\n  succeeded:\n    terminal: true\n  failed:\n    terminal: true\n'
        settlement = valid_settlement(machine).replace('task_type: ticket-to-pr','task_type: artefact-review')
        settlement = '\n'.join(x for x in settlement.splitlines() if not x.startswith('task_folder:'))+'\n'
        settlement += f'task_folder: {json.dumps(str(self.folder))}\n'
        settlement += 'artefact_review:\n  request: Review this guide for its reader.\n  inputs: ['+json.dumps(str(self.input))+']\n'
        self.settlement = self.root/'settlement.yaml'
        self.settlement.write_text(settlement)
        result = self.task('session','init','review','--dir',str(self.sessions),'--settlement-file',str(self.settlement))
        self.assertEqual(result.returncode,0,result.stderr)
        result = self.task('artefact','prepare','review','--dir',str(self.sessions))
        self.assertEqual(result.returncode,0,result.stderr)
        self.binding = json.loads(result.stdout)['binding']
        self.criteria = self.binding['configuration']['effective']['rubric']['criteria']
        self.context = {k:{'value':'Supplied guide context','basis':'supplied'} for k in ('audience','purpose','reader_task','delivery_mode')}
        self.evidence = {'kind':'inspected-content','claim_type':'internal-observation','locator':str(self.input)+':1','observation':'The guide names its reader task.'}
        self.inspection = {**self.context,'representations':[{'input':str(self.input),'ranges':['line 1'],'status':'complete'}],'limits':[]}
        self.applicability = {'criteria':{k:{'applicable':True,'anchor':v['meets'],'reason':'The guide uses this criterion.'} for k,v in self.criteria.items()}}
        self.states = {k:{'state':'Meets','reason':'The cited guide supports this state.','evidence':[self.evidence]} for k in self.criteria}
        self.assessment = {'reviewer':'independent-assessor','fresh_context':True,'context':['Raw request and supplied guide.'],'criteria':self.states,'candidates':[]}
        self.challenge = {'challenger':'fresh-challenger','fresh_context':True,'criteria':{k:{'result':'agreed','reason':'Checked state, applicability and missed defects.','ranges':[{'input':str(self.input),'range':'line 1'}],'searches':['Read all guide text; found no additional defect.']} for k in self.criteria},'findings':{},'positive_control':{'input':str(self.input),'item':'Present control','result':'Present control. The reader can follow the guide.'},'missed_candidates':[],'limits':[]}

    def task(self,*args):
        return subprocess.run([str(TASK),*args,'--json'],text=True,capture_output=True,cwd=self.root,env=self.env,check=False)

    def record(self,stage,value):
        source = self.root/'record.json'
        source.write_text(json.dumps(value))
        return self.task('artefact','record','--task-folder',str(self.folder),'--stage',stage,'--record-file',str(source))

    def accepted(self,stage,value):
        result=self.record(stage,value)
        self.assertEqual(result.returncode,0,result.stderr)

    def prepare_assessment(self):
        self.accepted('inspect',self.inspection)
        self.accepted('criteria',self.applicability)
        self.accepted('assess',self.assessment)

    def test_prerequisites_and_invalid_records_are_atomic(self):
        result=self.record('assess',self.assessment)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('inspect',result.stderr)
        self.accepted('inspect',self.inspection)
        before = sorted((self.folder/'artefact-review').rglob('*'))
        result=self.record('criteria',{'criteria':{},'unexpected':'bad'})
        self.assertNotEqual(result.returncode,0)
        self.assertIn('unexpected',result.stderr)
        self.assertEqual(before, sorted((self.folder/'artefact-review').rglob('*')))

    def test_missing_challenge_differs_from_explicit_empty_sweep(self):
        self.prepare_assessment()
        result=self.task('artefact','gate','--task-folder',str(self.folder),'--stage','challenge')
        self.assertNotEqual(result.returncode,0)
        missing=dict(self.challenge)
        del missing['missed_candidates']
        result=self.record('challenge',missing)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('missed_candidates',result.stderr)
        self.accepted('challenge',self.challenge)

    def test_applicability_and_memory_only_certainty_are_refused(self):
        self.accepted('inspect',self.inspection)
        self.accepted('criteria',self.applicability)
        key=next(iter(self.criteria))
        bad=json.loads(json.dumps(self.assessment))
        bad['criteria'][key]['state']='Not applicable'
        result=self.record('assess',bad)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('applicability',result.stderr)
        bad=json.loads(json.dumps(self.assessment))
        for row in bad['criteria'].values():
            row['evidence'][0]['kind']='memory'
        result=self.record('assess',bad)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('memory-only',result.stderr)

    def test_changed_input_requires_explicit_refresh_and_preserves_history(self):
        self.prepare_assessment()
        self.input.write_text('Changed input with Present control.\n')
        result=self.task('artefact','gate','--task-folder',str(self.folder),'--stage','assess')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('inputs changed',result.stderr)
        result=self.task('artefact','prepare','review','--dir',str(self.sessions))
        self.assertNotEqual(result.returncode,0)
        result=self.task('artefact','prepare','review','--dir',str(self.sessions),'--refresh','--reason','Updated supplied input.')
        self.assertEqual(result.returncode,0,result.stderr)
        root=self.folder/'artefact-review'
        self.assertTrue((root/'revision-0001/assess.0001.json').exists())
        self.assertFalse((root/'revision-0002/assess.json').exists())

    def test_current_prerequisite_digests_invalidate_old_challenge(self):
        self.prepare_assessment()
        self.accepted('challenge',self.challenge)
        self.assessment['context'].append('Another supplied note.')
        self.accepted('assess',self.assessment)
        result=self.task('artefact','gate','--task-folder',str(self.folder),'--stage','challenge')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('stale prerequisites',result.stderr)

    def test_snapshot_freezes_configuration_and_requires_explicit_refresh(self):
        project=self.root/'.bootgear/config'
        project.mkdir(parents=True)
        (project/'artefact-review.yaml').write_text('rubric:\n  criteria:\n    purpose-audience:\n      label: Updated audience anchor\n')
        result=self.task('artefact','prepare','review','--dir',str(self.sessions))
        self.assertNotEqual(result.returncode,0)
        self.assertIn('binding changed',result.stderr)
        result=self.task('artefact','settings','--task-folder',str(self.folder))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['effective_digest'],self.binding['configuration']['effective_digest'])
        self.assertEqual(json.loads(result.stdout)['revision'],'revision-0001')
        self.accepted('inspect',self.inspection)
        result=self.task('artefact','gate','--task-folder',str(self.folder),'--stage','inspect')
        self.assertEqual(result.returncode,0,result.stderr)
        result=self.task('artefact','prepare','review','--dir',str(self.sessions),'--refresh','--reason','Use the updated audience anchor.')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotEqual(json.loads(result.stdout)['binding']['configuration']['effective_digest'],self.binding['configuration']['effective_digest'])
        self.assertEqual(json.loads(result.stdout)['revision'],'revision-0002')

    def test_prepare_same_binding_is_idempotent(self):
        result=self.task('artefact','prepare','review','--dir',str(self.sessions))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['revision'],'revision-0001')

    def test_known_present_control_checks_actual_input(self):
        self.prepare_assessment()
        self.challenge['positive_control']['item']='An absent marker'
        self.challenge['positive_control']['result']='An absent marker'
        result=self.record('challenge',self.challenge)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('actual input',result.stderr)

    def test_override_and_disabled_reasons(self):
        project=self.root/'.bootgear/config'
        project.mkdir(parents=True)
        path=project/'artefact-review.yaml'
        path.write_text('rubric:\n  criteria:\n    purpose-audience:\n      enabled: false\n')
        result=self.task('artefact','settings')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('reason',result.stderr)
        path.write_text('rubric:\n  criteria:\n    purpose-audience:\n      enabled: false\n      reason: Explicitly excluded by task.\nfind_angles:\n  custom-angle:\n    tell: Find a source contradiction.\n    asks: Check the supplied source.\n')
        result=self.task('artefact','settings')
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout)
        self.assertFalse(value['effective']['rubric']['criteria']['purpose-audience']['enabled'])
        self.assertTrue(any(x['id']=='custom-angle' and x['lens']=='artefact' and x['tag']=='find' for x in value['angles']))

    def converge(self,*args,with_directory=True):
        wrapper=PLUGIN/('scripts/converge' if (PLUGIN/'scripts/converge').exists() else '../converge/bin/converge')
        env=dict(self.env)
        env['PATH']=str(wrapper.resolve().parent)+os.pathsep+env['PATH']
        directory=['--dir',str(self.root/'facts')] if with_directory else []
        result=subprocess.run([str(wrapper),*args,*directory,'--json'],text=True,capture_output=True,cwd=self.root,env=env,check=False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.env['PATH']=env['PATH']
        return json.loads(result.stdout)

    def closed_fact_slate(self):
        angles=self.folder/'artefact-review/revision-0001/angles.yaml'
        self.converge('init','review-facts','--as','main','--lenses','artefact','--angles',str(angles))
        import yaml
        for row in yaml.safe_load(angles.read_text()):
            self.converge('find-run','review-facts','--as','finder','--lens','artefact','--angle',row['id'],'--tell',row['tell'],'--searches','Read the supplied guide; no factual candidate.','--positive-control','Present control occurs in the guide.','--result','none')
        self.converge('cutoff','review-facts')
        return {'slate':'review-facts','directory':str(self.root/'facts'),'mappings':{}}

    def test_public_converge_and_full_report_progression(self):
        self.prepare_assessment()
        self.accepted('challenge',self.challenge)
        facts=self.closed_fact_slate()
        self.accepted('verify-facts',facts)
        self.accepted('judge',{'dispositions':{}})
        self.accepted('coverage',{'criteria':self.states,'criterion_checks':{k:{'result':'agreed','reason':'Checked final criterion state.'} for k in self.criteria},'disposition_checks':{},'challenger':'fresh-challenger','limits':[]})
        synthesis={'synthesis':[{'statement':'The inspected guide supports the supplied reader task.','references':[next(iter(self.criteria))],'challenge':'agreed','reason':'Checked against the recorded context and evidence.'}],'challenger':'fresh-challenger'}
        self.accepted('report',synthesis)
        result=self.task('artefact','gate','--task-folder',str(self.folder),'--stage','report')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('report missing',result.stderr)
        result=self.task('artefact','report','--task-folder',str(self.folder))
        self.assertEqual(result.returncode,0,result.stderr)
        report=Path(json.loads(result.stdout)['report'])
        content=report.read_text()
        self.assertIn('Quality synthesis',content)
        self.assertIn('inspected-content',content)
        self.assertIn(self.binding['configuration']['default_digest'],content)
        result=self.task('artefact','gate','--task-folder',str(self.folder),'--stage','report')
        self.assertEqual(result.returncode,0,result.stderr)
        report.write_text(content+'Unrecorded conclusion.\n')
        result=self.task('artefact','gate','--task-folder',str(self.folder),'--stage','report')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('stale',result.stderr)

    def defect(self,claim_type='quality-judgement'):
        evidence=dict(self.evidence)
        evidence['claim_type']=claim_type
        return {'id':'C1','criterion':next(iter(self.criteria)),'locator':str(self.input)+':1','observation':'The guide omits the required next action.','refutation':'Read the whole guide; the action remains absent.','impact':'The reader cannot complete the stated task.','severity':'Worth fixing','claim_type':claim_type,'evidence':[evidence]}

    def test_wrong_public_fact_mapping_is_refused(self):
        row=self.defect('internal-observation')
        self.assessment['candidates']=[row]
        self.prepare_assessment()
        self.challenge['findings']={'C1':{'result':'agreed','reason':'Checked observation, impact and severity.'}}
        self.accepted('challenge',self.challenge)
        facts=self.closed_fact_slate()
        facts['mappings']={'C1':{'claim':'F999','observation':row['observation'],'locator':row['locator'],'disposition':'kept'}}
        result=self.record('verify-facts',facts)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('actual Converge output',result.stderr)

    def test_missing_candidate_disposition_and_false_decision_are_refused(self):
        row=self.defect()
        self.assessment['candidates']=[row]
        self.prepare_assessment()
        self.challenge['findings']={'C1':{'result':'challenged','reason':'The supplied purpose does not require this action.'}}
        self.accepted('challenge',self.challenge)
        self.accepted('verify-facts',self.closed_fact_slate())
        result=self.record('judge',{'dispositions':{}})
        self.assertNotEqual(result.returncode,0)
        self.assertIn('missing C1',result.stderr)
        result=self.record('judge',{'dispositions':{'C1':{'disposition':'kept','reason':'Retain this judgement.','decision_ref':'a decision that does not exist'}}})
        self.assertNotEqual(result.returncode,0)
        self.assertIn('real resolve/debate',result.stderr)
        self.accepted('judge',{'dispositions':{'C1':{'disposition':'uncertain','reason':'The action requirement remains unsettled.'}}})
        result=self.record('coverage',{'criteria':self.states,'criterion_checks':{k:{'result':'agreed','reason':'Checked final criterion state.'} for k in self.criteria},'disposition_checks':{'C1':{'result':'unresolved','reason':'The requirement remains unsettled.'}},'challenger':'fresh-challenger','limits':[]})
        self.assertNotEqual(result.returncode,0)
        self.assertIn('uncertain defect',result.stderr)

    def test_dropped_sweep_candidates_need_challenger_reply(self):
        self.prepare_assessment()
        row=self.defect()
        self.challenge['missed_candidates']=[row]
        self.accepted('challenge',self.challenge)
        self.accepted('verify-facts',self.closed_fact_slate())
        self.accepted('judge',{'dispositions':{'C1':{'disposition':'dropped','reason':'The supplied reader task does not need that action.'}}})
        result=self.record('coverage',{'criteria':self.states,'criterion_checks':{k:{'result':'agreed','reason':'Checked final criterion state.'} for k in self.criteria},'disposition_checks':{},'challenger':'fresh-challenger','limits':[]})
        self.assertNotEqual(result.returncode,0)
        self.assertIn('missing C1',result.stderr)
        self.accepted('coverage',{'criteria':self.states,'criterion_checks':{k:{'result':'agreed','reason':'Checked final criterion state.'} for k in self.criteria},'disposition_checks':{'C1':{'result':'agreed','reason':'The full supplied task supports dropping the candidate.'}},'challenger':'fresh-challenger','limits':[]})

    def test_binary_control_uses_bound_extraction_with_source_provenance(self):
        import zipfile
        original=self.root/'slides.pptx'
        with zipfile.ZipFile(original,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('slides/slide1.xml','<text>Present control. The reader can follow the guide.</text>')
        self.assertNotIn(b'Present control',original.read_bytes())
        source=self.settlement.read_text().replace(json.dumps(str(self.folder)),json.dumps(str(self.root/'binary-review')))
        source=source.replace('inputs: ['+json.dumps(str(self.input))+']','inputs: ['+json.dumps(str(original))+', '+json.dumps(str(self.input))+']')
        self.settlement.write_text(source)
        self.folder=self.root/'binary-review'
        result=self.task('session','init','binary','--dir',str(self.sessions),'--settlement-file',str(self.settlement))
        self.assertEqual(result.returncode,0,result.stderr)
        result=self.task('artefact','prepare','binary','--dir',str(self.sessions))
        self.assertEqual(result.returncode,0,result.stderr)
        self.inspection['representations']=[{'input':str(original),'ranges':['archive metadata'],'status':'partial','reason':'Visible text was checked through the bound extraction.'},{'input':str(self.input),'ranges':['line 1'],'status':'complete','derived_from':str(original),'provenance':'Extracted the slide text from slides/slide1.xml.'}]
        for row in self.states.values():
            row['qualification']='Text properties only; no rendered slide layout was inspected.'
        self.prepare_assessment()
        for row in self.challenge['criteria'].values():
            row['ranges'].append({'input':str(original),'range':'archive metadata; bound extraction covers slide text'})
        self.challenge['positive_control']['input']=str(original)
        self.challenge['positive_control']['representation']=str(self.input)
        self.accepted('challenge',self.challenge)
        self.challenge['positive_control']['representation']=str(self.root/'unbound.txt')
        result=self.record('challenge',self.challenge)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('bound input',result.stderr)

    def test_invalid_limit_types_fail_before_recording(self):
        self.inspection['limits']={'unread':'source'}
        result=self.record('inspect',self.inspection)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('limits must be an explicit list',result.stderr)
        self.inspection['limits']=[]
        self.prepare_assessment()
        self.challenge['limits']='No extra limit'
        result=self.record('challenge',self.challenge)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('limits must be an explicit list',result.stderr)

    def test_missing_evidence_and_critical_outcome_reference_are_refused(self):
        self.accepted('inspect',self.inspection)
        self.accepted('criteria',self.applicability)
        key=next(iter(self.criteria))
        bad=json.loads(json.dumps(self.assessment))
        bad['criteria'][key]['evidence']=[]
        result=self.record('assess',bad)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('typed evidence',result.stderr)
        row=self.defect()
        row.update(severity='Critical',reader_outcome='action',impact_evidence=[dict(self.evidence)])
        self.assessment['candidates']=[row]
        result=self.record('assess',self.assessment)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('inspected reader outcome',result.stderr)
        row['reader_outcome_ref']='inspect.reader_task'
        self.accepted('assess',self.assessment)

    def test_external_fact_cannot_use_unsupported_artefact_text(self):
        self.accepted('inspect',self.inspection)
        self.accepted('criteria',self.applicability)
        row=self.defect('external-fact')
        self.assessment['candidates']=[row]
        result=self.record('assess',self.assessment)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('evidence kind cannot support',result.stderr)

    def test_positive_states_need_final_challenger_reply(self):
        self.prepare_assessment()
        key=next(iter(self.criteria))
        self.challenge['criteria'][key]['result']='challenged'
        self.challenge['criteria'][key]['reason']='The positive state lacks adequate support.'
        self.accepted('challenge',self.challenge)
        self.accepted('verify-facts',self.closed_fact_slate())
        self.accepted('judge',{'dispositions':{}})
        value={'criteria':self.states,'disposition_checks':{},'challenger':'fresh-challenger','limits':[]}
        result=self.record('coverage',value)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('criterion_checks',result.stderr)
        value['criterion_checks']={k:{'result':'agreed','reason':'The final state has supported scope.'} for k in self.criteria}
        value['criterion_checks'][key]={'result':'unresolved','reason':'The positive evidence remains disputed.'}
        result=self.record('coverage',value)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Cannot judge',result.stderr)
        value['criteria'][key]['state']='Cannot judge'
        self.accepted('coverage',value)

    def test_uninspectable_states_reject_null_evidence_before_write(self):
        self.accepted('inspect',self.inspection)
        self.accepted('criteria',self.applicability)
        key=next(iter(self.criteria))
        self.assessment['criteria'][key]={'state':'Cannot judge','reason':'The source cannot be inspected.','evidence':None}
        result=self.record('assess',self.assessment)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('evidence',result.stderr)
        self.assessment['criteria'][key]['evidence']=[]
        self.accepted('assess',self.assessment)
        self.assessment['criteria'][key]['evidence']=[{'kind':'memory','claim_type':'quality-judgement','locator':'Unverified general knowledge','observation':'The source remains unverified.'}]
        self.accepted('assess',self.assessment)

    def test_default_settings_displays_resolved_review_data(self):
        result=subprocess.run([str(TASK),'artefact','settings','--project-root',str(self.root),'--prose'],text=True,capture_output=True,env=self.env,check=False)
        self.assertEqual(result.returncode,0,result.stderr)
        for key,row in self.criteria.items():
            self.assertIn(key,result.stdout)
            self.assertIn(row['label'],result.stdout)
        for row in self.binding['configuration']['angles']:
            self.assertIn(row['id'],result.stdout)
        self.assertIn('sources',result.stdout)

    def test_uncontested_sweep_judgement_needs_no_dispute_decision(self):
        self.prepare_assessment()
        row=self.defect()
        self.challenge['missed_candidates']=[row]
        self.accepted('challenge',self.challenge)
        self.accepted('verify-facts',self.closed_fact_slate())
        self.accepted('judge',{'dispositions':{'C1':{'disposition':'kept','reason':'The assessment agrees with this supported sweep finding.'}}})

    def test_decision_reference_requires_a_complete_record(self):
        row=self.defect()
        self.assessment['candidates']=[row]
        self.prepare_assessment()
        self.challenge['findings']={'C1':{'result':'challenged','reason':'The requested outcome is disputed.'}}
        self.accepted('challenge',self.challenge)
        self.accepted('verify-facts',self.closed_fact_slate())
        result=self.task('session','record-decision','review','--dir',str(self.sessions),'--mode','resolve','--summary','C1 is retained under the supplied task requirement.')
        self.assertEqual(result.returncode,0,result.stderr)
        for reference in ('resolve','[','C1'):
            result=self.record('judge',{'dispositions':{'C1':{'disposition':'kept','reason':'Keep the supported judgement.','decision_ref':reference}}})
            self.assertNotEqual(result.returncode,0,reference)
        result=self.task('session','read','review','--dir',str(self.sessions),'--section','decisions')
        self.assertEqual(result.returncode,0,result.stderr)
        reference=next(line for line in json.loads(result.stdout)['lines'] if '[resolve]' in line)
        self.accepted('judge',{'dispositions':{'C1':{'disposition':'kept','reason':'Keep the supported judgement.','decision_ref':reference}}})
        self.states[row['criterion']]['state']='Needs change'
        self.accepted('coverage',{'criteria':self.states,'criterion_checks':{key:{'result':'agreed','reason':'Checked the final criterion state.'} for key in self.criteria},'disposition_checks':{'C1':{'result':'unresolved','reason':'The challenger preserves dissent after the recorded decision.'}},'challenger':'fresh-challenger','limits':[]})
        self.accepted('report',{'synthesis':[{'statement':'A recorded decision retains C1 with reviewer dissent.','references':['C1'],'challenge':'unresolved','reason':'The decision settles the outcome and preserves the objection.'}],'challenger':'fresh-challenger'})
        result=self.task('artefact','report','--task-folder',str(self.folder))
        self.assertEqual(result.returncode,0,result.stderr)
        report=Path(json.loads(result.stdout)['report']).read_text()
        self.assertIn('The challenger preserves dissent after the recorded decision.',report)
        self.assertIn(reference,report)

    def test_real_nonempty_fact_mapping_reaches_canonical_report(self):
        import yaml
        self.input.write_text('Present control. The total is 70 for parts 20 and 30.\n')
        refreshed=self.task('artefact','prepare','review','--dir',str(self.sessions),'--refresh','--reason','Review a supplied numerical inconsistency.')
        self.assertEqual(refreshed.returncode,0,refreshed.stderr)
        angles=Path(json.loads(refreshed.stdout)['angles_file'])
        row=self.defect('internal-observation')
        row['locator']=str(self.input)+':1'
        row['observation']='The stated total 70 differs from 20 plus 30, which is 50.'
        row['evidence']=[{'kind':'direct-calculation','claim_type':'internal-observation','locator':row['locator'],'observation':'20 + 30 = 50; the supplied guide states 70.'}]
        self.assessment['candidates']=[row]
        self.states[row['criterion']]={'state':'Needs change','reason':'The supplied total disagrees with its parts.','evidence':row['evidence']}
        self.prepare_assessment()
        self.challenge['findings']={'C1':{'result':'agreed','reason':'Direct calculation confirms the numerical mismatch.'}}
        self.accepted('challenge',self.challenge)
        settings=self.root/'fact-test-config.json'
        settings.write_text(json.dumps({'steps':{'cut':'none','escalate':False,'gap_hunt':False}}))
        self.converge('init','review-facts','--as','main','--lenses','artefact','--angles',str(angles),'--refuters','1','--config',str(settings))
        find_angles=yaml.safe_load(angles.read_text())
        self.converge('file','review-facts','--as','finder','--lens','artefact','--angle',find_angles[0]['id'],'--origin','lens','--loc',row['locator'],'--claim',row['observation'],'--trigger','The supplied total disagrees with the stated parts.','--evidence',row['evidence'][0]['observation'],'--tier','reproduced')
        claim=self.converge('status','review-facts')['claims'][0]['id']
        for index,angle in enumerate(find_angles):
            self.converge('find-run','review-facts','--as','finder','--lens','artefact','--angle',angle['id'],'--tell',angle['tell'],'--searches','Read the complete supplied numerical guide.','--positive-control','Present control occurs in the guide.','--result',claim if index == 0 else 'none')
        attack_rows={angle['id']:angle for angle in self.converge('angles','--tag','attack',with_directory=False)['angles']}
        for _ in range(len(attack_rows)+2):
            status=self.converge('status','review-facts')
            if status['phase']=='cutoff':
                break
            self.assertEqual(status['phase'],'attack',status)
            for action in status['plan'][0]:
                self.assertEqual(action['agent_role'],'r1')
                fresh=action['batch']=='fresh-eye'
                for angle_id in (['fixture-direct-calculation'] if fresh else action['angles']):
                    tell='The fixture contains a numerical total.' if fresh else attack_rows[angle_id]['tell']
                    extra=['--last'] if fresh else []
                    self.converge('attack','review-facts','--as','r1','--claim',claim,'--batch',str(action['batch']),'--angle',angle_id,'--tell',tell,'--outcome','clean','--evidence','20 + 30 = 50, and the supplied total is 70.','--searches','Read the total and both parts.','--positive-control','Present control occurs in the same line.',*extra)
        self.assertEqual(self.converge('status','review-facts')['phase'],'cutoff')
        self.converge('cutoff','review-facts')
        facts={'slate':'review-facts','directory':str(self.root/'facts'),'mappings':{'C1':{'claim':claim,'observation':row['observation'],'locator':row['locator'],'disposition':'kept'}}}
        self.accepted('verify-facts',facts)
        self.accepted('judge',{'dispositions':{'C1':{'disposition':'kept','reason':'The directly calculated inconsistency is verified.'}}})
        self.accepted('coverage',{'criteria':self.states,'criterion_checks':{key:{'result':'agreed','reason':'Checked the final evidence and state.'} for key in self.criteria},'disposition_checks':{'C1':{'result':'agreed','reason':'The verified inconsistency remains material.'}},'challenger':'fresh-challenger','limits':[]})
        self.accepted('report',{'synthesis':[{'statement':'The supplied guide contains a verified numerical inconsistency.','references':['C1'],'challenge':'agreed','reason':'The claim matches the observed total and direct calculation.'}],'challenger':'fresh-challenger'})
        result=self.task('artefact','report','--task-folder',str(self.folder))
        self.assertEqual(result.returncode,0,result.stderr)
        report=Path(json.loads(result.stdout)['report']).read_text()
        self.assertIn(row['observation'],report)
        self.assertIn('C1',report)

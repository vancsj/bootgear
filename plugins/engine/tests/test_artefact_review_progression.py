import json
import subprocess
from pathlib import Path

from artefact_review_test_support import ArtefactProgressionTestCase
from gear_commands import TASK as TASK_COMMAND


class ArtefactProgressionTest(ArtefactProgressionTestCase):
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
        result=subprocess.run([*TASK_COMMAND,'artefact','settings','--project-root',str(self.root),'--prose'],text=True,capture_output=True,env=self.env,check=False)
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
                checks=[]
                for angle_id in (['fixture-direct-calculation'] if fresh else action['angles']):
                    tell='The fixture contains a numerical total.' if fresh else attack_rows[angle_id]['tell']
                    checks.append({'angle':angle_id,'tell':tell,'evidence':'20 + 30 = 50, and the supplied total is 70.','searches':'Read the total and both parts.','positive_control':'Present control occurs in the same line.'})
                value={'slate':'review-facts','source_seq':len((self.root/'facts/review-facts.jsonl').read_text().splitlines()),'role':'r1','action':'clean','claim':claim,'batch':action['batch'],'checks':checks}
                if fresh:
                    value['last']=True
                action_file=self.root/'clean-action.json'
                action_file.write_text(json.dumps(value))
                self.converge('clean','review-facts','--as','r1','--input',str(action_file))
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

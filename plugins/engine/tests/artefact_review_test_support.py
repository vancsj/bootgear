"""Public artefact review contracts."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from gear_commands import CONVERGE as CONVERGE_COMMAND
from gear_commands import TASK as TASK_COMMAND

PLUGIN = Path(__file__).resolve().parents[1]

class ArtefactProgressionTestCase(unittest.TestCase):
    def setUp(self):
        from settlement_fixture import valid_settlement
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.folder = self.root/'task'
        self.sessions = self.root/'sessions'
        self.input = self.root/'input.txt'
        self.input.write_text('Present control. The reader can follow the guide.\n')
        self.env = {k:v for k,v in os.environ.items() if k not in {'BOOTGEAR_SESSION_ID','CLAUDE_CODE_SESSION_ID','CODEX_SESSION_ID','GEAR_CALLER_CWD','VIRTUAL_ENV','PLUGIN_ROOT'}}
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
        return subprocess.run([*TASK_COMMAND,*args,'--json'],text=True,capture_output=True,cwd=self.root,env=self.env,check=False)

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

    def converge(self,*args,with_directory=True):
        env=dict(self.env)
        directory=['--dir',str(self.root/'facts')] if with_directory else []
        result=subprocess.run([*CONVERGE_COMMAND,*args,*directory,'--json'],text=True,capture_output=True,cwd=self.root,env=env,check=False)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def closed_fact_slate(self):
        angles=self.folder/'artefact-review/revision-0001/angles.yaml'
        self.converge('init','review-facts','--as','main','--lenses','artefact','--angles',str(angles))
        import yaml
        for row in yaml.safe_load(angles.read_text()):
            self.converge('find-run','review-facts','--as','finder','--lens','artefact','--angle',row['id'],'--tell',row['tell'],'--searches','Read the supplied guide; no factual candidate.','--positive-control','Present control occurs in the guide.','--result','none')
        self.converge('gap-hunt-done','review-facts','--as','r2')
        self.converge('cutoff','review-facts')
        return {'slate':'review-facts','directory':str(self.root/'facts'),'mappings':{}}

    def defect(self,claim_type='quality-judgement'):
        evidence=dict(self.evidence)
        evidence['claim_type']=claim_type
        return {'id':'C1','criterion':next(iter(self.criteria)),'locator':str(self.input)+':1','observation':'The guide omits the required next action.','refutation':'Read the whole guide; the action remains absent.','impact':'The reader cannot complete the stated task.','severity':'Worth fixing','claim_type':claim_type,'evidence':[evidence]}

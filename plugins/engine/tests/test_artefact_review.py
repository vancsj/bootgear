import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from artefact_review_test_support import ArtefactProgressionTestCase
from bootgear_cli import clikit
from gear_commands import TASK as TASK_COMMAND


class ArtefactReviewTest(unittest.TestCase):
    def command(self, *args, cwd=None):
        env = {k:v for k,v in os.environ.items() if k not in {'BOOTGEAR_SESSION_ID', 'CLAUDE_CODE_SESSION_ID', 'CODEX_SESSION_ID', 'GEAR_CALLER_CWD', 'VIRTUAL_ENV'}}
        return subprocess.run([*TASK_COMMAND, 'artefact', *args, '--json'], text=True, capture_output=True, cwd=cwd, env=env, check=False)

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


class ArtefactProgressionTest(ArtefactProgressionTestCase):
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

    def test_prepare_reads_the_run_id_from_the_environment_chain(self):
        for name in ('CLAUDE_CODE_SESSION_ID','CODEX_SESSION_ID'):
            with self.subTest(variable=name):
                env = {**self.env, name:'review'}
                result=subprocess.run([*TASK_COMMAND,'artefact','prepare','--dir',str(self.sessions),'--json'],text=True,capture_output=True,cwd=self.root,env=env,check=False)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['revision'],'revision-0001')

    def test_prepare_with_an_empty_run_id_reads_the_environment_id(self):
        env = {**self.env, 'CODEX_SESSION_ID':'review'}
        result=subprocess.run([*TASK_COMMAND,'artefact','prepare','','--dir',str(self.sessions),'--json'],text=True,capture_output=True,cwd=self.root,env=env,check=False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['revision'],'revision-0001')

    def test_prepare_without_a_session_names_the_environment_and_the_override(self):
        result=subprocess.run([*TASK_COMMAND,'artefact','prepare','--dir',str(self.sessions),'--json'],text=True,capture_output=True,cwd=self.root,env=self.env,check=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(clikit.missing_session('<run-id>'),result.stderr)

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

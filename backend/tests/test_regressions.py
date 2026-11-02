"""Offline regression checks: never call Telegram, AI providers or the live database."""
import asyncio
import json
import logging
import hashlib
import hmac
import time
from urllib.parse import urlencode
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import database
from app.api import auth
from app.config import settings
from app.main import app
from app.services import cv_service
from app.telegram import bot_user_tools as tools
from app.worker import queue

SAMPLE = """Alex Example
Software Engineer
alex@example.com | github.com/alex | Remote
PROFESSIONAL SUMMARY
Builds reliable Python applications for small teams.
CORE SKILLS
Backend: Python, SQL
SELECTED PROJECTS
- Inventory System
  - Built stock tracking with Python and SQLite.
PROFESSIONAL EXPERIENCE
Software Engineer — Example Co | Remote | 2023 - Present
- Built reliable software.
EDUCATION
BSc Computer Science
"""


def cv_save_callback(uid):
    pending=tools.pending_for(uid) or {}
    return 'ut:cv:save:' + pending.get('preview_id','expired')


class RegressionTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = create_engine(f"sqlite:///{self.root / 'test.db'}", connect_args={"check_same_thread": False})
        database.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.patches = [patch.object(cv_service, 'CV_ROOT', self.root / 'cvs'),
                        patch.object(auth, 'DATA_DIR', self.root),
                        patch.object(database, 'SessionLocal', self.sessions),
                        patch.object(tools, 'SessionLocal', self.sessions),
                        patch('app.services.cv_ai.api_available', return_value=False),
                        patch.object(settings, 'dashboard_admin_password', 'test-admin-password'),
                        patch.object(settings, 'worker_api_secret', 'test-worker-secret')]
        for p in self.patches:
            p.start()
        def get_db():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[database.get_db] = get_db
        self.client = TestClient(app)
        with self.sessions() as db:
            db.add_all([database.User(telegram_user_id=101, chat_id=101), database.User(telegram_user_id=202, chat_id=202)])
            db.add_all([database.BotApplication(telegram_user_id=101, title='User One'), database.BotApplication(telegram_user_id=202, title='User Two')])
            db.commit()

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        tools._pending.clear()
        auth._attempts.clear()
        for p in reversed(self.patches):
            p.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def session(self, uid=101, admin=False):
        self.client.cookies.set(auth.COOKIE, auth.issue_session(uid, admin=admin))

    def test_anonymous_private_apis_denied(self):
        for path in ['/api/applications', '/api/applications/1/resume.docx', '/api/linkedin/settings', '/api/worker/status', '/api/rag/status']:
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.assertEqual(self.client.delete('/api/applications/1').status_code, 401)

    def test_owner_cannot_read_delete_or_download_other_user(self):
        self.session()
        self.assertEqual([x['title'] for x in self.client.get('/api/applications').json()], ['User One'])
        for method, path in [('get','/api/applications/2'), ('get','/api/applications/2/resume.docx'), ('delete','/api/applications/2')]:
            self.assertEqual(getattr(self.client, method)(path).status_code, 404)
        self.assertEqual(self.client.get('/api/linkedin/settings').status_code, 403)

    def test_login_logout_and_forgery(self):
        self.assertEqual(self.client.post('/api/auth/login', json={'password':'wrong'}).status_code,401)
        result = self.client.post('/api/auth/login', json={'password':'test-admin-password'})
        self.assertEqual(result.status_code,200)
        self.client.headers['X-CSRF-Token']=self.client.cookies.get('career_csrf')
        self.assertIn('HttpOnly',result.headers['set-cookie'])
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.client.cookies.set(auth.COOKIE, auth.issue_session(101)[:-1] + 'x')
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)

    def test_cross_origin_writes_rejected(self):
        self.session(admin=True)
        response=self.client.delete('/api/applications/1',headers={'Origin':'https://attacker.example'})
        self.assertEqual(response.status_code,403)

    def test_cv_history_isolation_conflicts_and_unicode(self):
        cv_service.write_cv(101,SAMPLE)
        version=cv_service.fingerprint(SAMPLE)
        updated=cv_service.append_entry(SAMPLE,'سامانه جدید\nساخت API با Python\nhttps://example.com')
        cv_service.write_cv(101,updated,expected=version)
        self.assertIn('سامانه جدید',cv_service.read_cv(101))
        self.assertEqual(cv_service.read_cv(202),'')
        self.assertEqual(len(list((self.root/'cvs/101/history').glob('*.txt'))),1)
        with self.assertRaises(ValueError):
            cv_service.write_cv(101,SAMPLE,expected=version)
        cv_service.write_cv(101, updated, expected=cv_service.fingerprint(updated))

    def test_project_flow_requires_confirm_and_preserves_cancel(self):
        cv_service.write_cv(101,SAMPLE)
        tools.start_cv_update(101)
        raw='New Project: I built a useful API using Python. No other information.'
        analysis={'facts':{'name':[{'text':'New Project','evidence':'New Project'}],
                           'contributions':[{'text':'Built a useful API using Python.','evidence':'I built a useful API using Python.'}]},
                  'unavailable':{key:'No other information.' for key in ('role','period','technologies','results','links')}}
        with patch('app.services.cv_ai.api_available',return_value=True), patch('app.services.cv_ai.analyze_with_api',new=AsyncMock(return_value=analysis)):
            result=asyncio.run(tools.handle_text(telegram_user_id=101,text=raw))
        self.assertIn('پیش‌نمایش',result['message'])
        self.assertEqual(cv_service.read_cv(101),SAMPLE.strip())
        asyncio.run(tools.handle_tool_callback('ut:cv:save',telegram_user_id=202))
        self.assertEqual(cv_service.read_cv(202),'')
        asyncio.run(tools.handle_tool_callback(cv_save_callback(101),telegram_user_id=101))
        self.assertIn('New Project',cv_service.read_cv(101))
        tools.start_cv_update(101)
        asyncio.run(tools.handle_text(telegram_user_id=101,text='Cancelled Project: do not persist this one.'))
        asyncio.run(tools.handle_tool_callback('ut:cancel',telegram_user_id=101))
        self.assertNotIn('Cancelled Project',cv_service.read_cv(101))

    def test_export_never_injects_operator_projects(self):
        from app.ats.base_cv_export import parse_base_cv_text, export_base_cv_files
        resume=parse_base_cv_text(SAMPLE)
        self.assertEqual([p['name'] for p in resume['projects']],['Inventory System'])
        self.assertNotIn('Ramin',json.dumps(resume))
        with patch('app.ats.pdf_export.export_resume_pdf', side_effect=RuntimeError('missing PDF dependency')):
            docx,pdf=export_base_cv_files(SAMPLE,self.root/'export',allow_partial=True)
        self.assertTrue(docx.is_file())
        self.assertIsNone(pdf)

    def test_atomic_claim_two_workers(self):
        with self.sessions() as db:
            row=database.WorkJob(job_type=queue.JOB_VECTOR_SCREEN,entity_id=1,payload_json=json.dumps({'text':'a sufficiently long job description for screening'}))
            db.add(row);db.commit()
        def claim(worker):
            with self.sessions() as db:
                row=queue.claim_next(db,worker)
                return row.id if row else None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(claim,['one','two']))
        self.assertEqual(sum(r is not None for r in results),1)
        with self.sessions() as db:
            row=db.query(database.WorkJob).one()
            self.assertTrue(row.claim_token)
            self.assertEqual(row.attempts,1)

    def test_stale_result_rejected_after_reclaim(self):
        with self.sessions() as db:
            row=database.WorkJob(job_type=queue.JOB_VECTOR_SCREEN,entity_id=1,payload_json=json.dumps({'text':'a valid job description to be screened'}))
            db.add(row);db.commit()
            row=queue.claim_next(db,'old')
            old_token=row.claim_token
            row.claimed_at=datetime.now(timezone.utc)-timedelta(minutes=25)
            db.commit()
            new=queue.claim_next(db,'new')
            self.assertNotEqual(new.claim_token,old_token)
            job_id=new.id
        response=self.client.post(f'/api/worker/jobs/{job_id}/complete',headers={'Authorization':'Bearer test-worker-secret'},json={'worker_id':'old','claim_token':old_token,'result':{}})
        self.assertEqual(response.status_code,409)

    def test_complete_is_idempotent_and_uses_queued_identity(self):
        with self.sessions() as db:
            row=database.WorkJob(job_type=queue.JOB_VECTOR_SCREEN,entity_id=101,payload_json=json.dumps({'text':'some text'}))
            db.add(row);db.commit()
            row=queue.claim_next(db,'pc')
            # Insert owner metadata for result application contract.
            row.payload_json=json.dumps({'telegram_user_id':101,'chat_id':101})
            db.commit();job_id=row.id;token=row.claim_token
        async def apply(db,row,result):
            self.assertEqual(result['telegram_user_id'],101)
            self.assertEqual(result['chat_id'],101)
            self.assertNotIn('application_id',result)
            row.status='done';db.commit()
            return {'ok':True}
        body={'worker_id':'pc','claim_token':token,'result':{'telegram_user_id':202,'chat_id':202,'application_id':2}}
        with patch('app.worker.api.apply_work_result',side_effect=apply) as mocked:
            for _ in range(2):
                response=self.client.post(f'/api/worker/jobs/{job_id}/complete',headers={'Authorization':'Bearer test-worker-secret'},json=body)
                self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(mocked.call_count,1)

    def test_user_settings_and_credentials_are_separate(self):
        from app.linkedin.settings import LinkedInSettings,save_linkedin_settings,load_linkedin_settings
        from app.services import credentials
        with patch.object(credentials,'DATA_DIR',self.root), self.sessions() as db:
            save_linkedin_settings(db,LinkedInSettings(applicant_name='First',gmail_app_password='private'),101)
            save_linkedin_settings(db,LinkedInSettings(applicant_name='Second'),202)
            self.assertEqual(load_linkedin_settings(db,101).gmail_app_password,'private')
            self.assertEqual(load_linkedin_settings(db,202).applicant_name,'Second')
            stored=db.get(database.AppSettings,'linkedin_settings:101').value
            self.assertNotIn('private',stored)
            self.assertIn('enc:v1:',stored)

    def test_deactivated_user_denied(self):
        self.session()
        with self.sessions() as db:
            user=db.query(database.User).filter_by(telegram_user_id=101).one()
            user.is_active=False;db.commit()
        self.assertEqual(self.client.get('/api/applications').status_code,401)

    def test_real_base_cv_exports_and_user_output_path(self):
        from app.ats.base_cv_export import export_base_cv_files
        from zipfile import ZipFile
        docx,pdf=export_base_cv_files(SAMPLE,self.root/'real-export')
        self.assertTrue(pdf.read_bytes().startswith(b'%PDF-'))
        with ZipFile(docx) as z:
            xml=z.read('word/document.xml').decode()
        self.assertIn('Alex Example',xml)
        self.assertIn('Inventory System',xml)
        self.assertNotIn('Bendly',xml)
        cv_service.write_cv(101,SAMPLE)
        with patch('app.config.DATA_DIR',self.root):
            result=tools.send_base_cv_files(101)
        self.assertEqual(len(result['send_documents']),2)
        for item in result['send_documents']:
            self.assertTrue(Path(item['path']).is_relative_to(self.root/'user_outputs/101'))

    def test_pdf_runtime_preflight_exports_real_documents(self):
        from app.ats.pdf_runtime import check_pdf_runtime
        result = check_pdf_runtime()
        self.assertEqual(result['status'], 'PDF_RUNTIME_OK')
        self.assertGreater(result['pdf_bytes'], 1000)
        self.assertFalse(result['user_data_used'])
        self.assertFalse(result['network_used'])

    def test_pdf_runtime_preflight_rejects_cpu_incompatible_numpy(self):
        from app.ats.pdf_runtime import check_pdf_runtime
        with patch('app.ats.pdf_runtime.import_module', side_effect=RuntimeError('X86_V2 unsupported')):
            with self.assertRaisesRegex(RuntimeError, 'NumPy cannot initialize on this CPU'):
                check_pdf_runtime()

    def test_numpy_cpu_compatibility_pin_is_preserved_in_both_installs(self):
        backend = Path(__file__).resolve().parents[1]
        for name in ('requirements.txt', 'requirements-vps.txt'):
            requirements = (backend / name).read_text(encoding='utf-8').splitlines()
            numpy_requirements = [line.strip() for line in requirements if line.strip().startswith('numpy')]
            self.assertEqual(numpy_requirements, ['numpy==2.3.5'])

    def test_admin_matching_does_not_accept_suffixes(self):
        from app.telegram.bot import review_bot
        with patch.object(settings,'telegram_admin_ids','123456789'), patch.object(settings,'telegram_review_chat_id','123456789'):
            self.assertFalse(review_bot._is_admin(789,telegram_user_id=789))
            self.assertTrue(review_bot._is_admin(123456789,telegram_user_id=123456789))
        with patch.object(settings,'telegram_admin_ids',''), patch.object(settings,'telegram_review_chat_id','-100123456789'):
            self.assertNotIn(100123456789, settings.admin_telegram_ids)

    def test_disabled_user_not_reactivated_on_message(self):
        from app.billing.service import get_or_create_user
        with self.sessions() as db:
            user=db.query(database.User).filter_by(telegram_user_id=101).one()
            user.is_active=False;db.commit()
            result=get_or_create_user(db,telegram_user_id=101,chat_id=101)
            self.assertFalse(result.is_active)

    def test_operator_cv_sync_does_not_overwrite_user_edit(self):
        with patch.object(settings,'telegram_admin_ids','101'), patch.object(settings,'telegram_review_chat_id',''):
            for text in (SAMPLE,SAMPLE.replace('Inventory System','SHOULD NOT REPLACE')):
                response=self.client.post('/api/worker/heartbeat',headers={'Authorization':'Bearer test-worker-secret'},json={'worker_id':'pc','operator_cv_text':text})
                self.assertEqual(response.status_code,200,response.text)
        self.assertIn('Inventory System',cv_service.read_cv(101))
        self.assertNotIn('SHOULD NOT REPLACE',cv_service.read_cv(101))
        self.assertEqual(cv_service.read_cv(202),'')

    def test_worker_uses_each_users_cv_in_separate_runs(self):
        from app.worker.codex_apply import run_codex_apply
        def stop(*args,**kwargs):
            raise RuntimeError('stop-before-running-agent')
        with patch('app.config.DATA_DIR',self.root), patch('app.ai.codex.find_codex_cmd',return_value=['codex']), patch('app.worker.codex_apply.subprocess.run',side_effect=stop):
            for uid in (101,202):
                payload={'telegram_user_id':uid,'base_cv_text':SAMPLE.replace('Alex Example',f'Candidate {uid}'),'description':'A sufficiently long job description with Python backend requirements.','_work_job_id':uid}
                with self.assertRaisesRegex(RuntimeError,'stop-before-running-agent'):
                    asyncio.run(run_codex_apply(payload))
        first=(self.root/'worker_workspaces/101/101/documents/base_cv.txt').read_text(encoding='utf-8')
        second=(self.root/'worker_workspaces/202/202/documents/base_cv.txt').read_text(encoding='utf-8')
        self.assertIn('Candidate 101',first)
        self.assertNotIn('Candidate 202',first)
        self.assertIn('Candidate 202',second)

    def test_telegram_signature_and_expiration(self):
        token='test-bot-token'
        def make_data(age=0):
            fields={'auth_date':str(int(time.time())-age),'query_id':'test-query','user':json.dumps({'id':101})}
            key=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
            payload='\n'.join(f'{k}={v}' for k,v in sorted(fields.items()))
            fields['hash']=hmac.new(key,payload.encode(),hashlib.sha256).hexdigest()
            return urlencode(fields)
        with patch.object(settings,'telegram_review_bot_token',token):
            self.assertEqual(self.client.post('/api/auth/login',json={'init_data':make_data()}).status_code,200)
            self.client.headers['X-CSRF-Token']=self.client.cookies.get('career_csrf')
            self.assertEqual(self.client.get('/api/auth/me').json()['telegram_user_id'],101)
            self.assertEqual(self.client.post('/api/auth/login',json={'init_data':make_data(600)}).status_code,401)

    def test_schema_migration_is_repeatable(self):
        with patch.object(database,'engine',self.engine):
            database._migrate_columns()
            database._migrate_columns()
        with self.engine.connect() as conn:
            self.assertEqual(conn.exec_driver_sql('SELECT COUNT(*) FROM schema_migrations WHERE version=1').scalar(),1)

    def test_generation_prompts_do_not_inject_personal_projects(self):
        from app.worker.codex_apply import _build_prompt, _build_improve_prompt, _REPO_ATS_GUIDE
        kwargs=dict(title='Engineer',company='Example',job_url='',description='Python engineering role',out_dir=Path('applications/test'))
        for content in (_build_prompt(**kwargs),_build_improve_prompt(**kwargs),_REPO_ATS_GUIDE.read_text(encoding='utf-8')):
            for private in ('Bendly','ramintkml','Ramin Takmil','all five'):
                self.assertNotIn(private,content)

    def test_cv_ai_asks_missing_information_then_previews_after_answers(self):
        cv_service.write_cv(101,SAMPLE)
        tools.start_cv_update(101)
        first='من پروژه ساخت سامانه نوبت‌دهی گرفتم.'
        incomplete={'facts':{'name':[{'text':'Appointment Scheduling System','evidence':first}]}}
        second='نقشم برنامه‌نویس بک‌اند است. هنوز شروع نشده. قرار است API با Python بسازم. لینک و نتیجه‌ای ندارم.'
        complete={'facts':{
            'name':[{'text':'Appointment Scheduling System','evidence':first}],
            'role':[{'text':'Backend developer','evidence':'نقشم برنامه‌نویس بک‌اند است.'}],
            'period':[{'text':'Not started','evidence':'هنوز شروع نشده.'}],
            'technologies':[{'text':'Python','evidence':'Python'}],
            'contributions':[{'text':'Will develop the backend API using Python.','evidence':'قرار است API با Python بسازم.'}]},
            'unavailable':{'links':'لینک و نتیجه‌ای ندارم.','results':'لینک و نتیجه‌ای ندارم.'}}
        with patch('app.services.cv_ai.api_available',return_value=True), patch('app.services.cv_ai.analyze_with_api',new=AsyncMock(side_effect=[incomplete,complete])) as model:
            response=asyncio.run(tools.handle_text(telegram_user_id=101,text=first))
            self.assertIn('نقش',response['message'])
            self.assertIn('وضعیتی',response['message'])
            self.assertNotIn('candidate',tools.pending_for(101))
            response=asyncio.run(tools.handle_text(telegram_user_id=101,text=second))
            payload=model.call_args.args[0]
            self.assertEqual(payload['language'],'en')
            self.assertNotIn('Alex Example',json.dumps(payload))
            self.assertEqual(len([m for m in payload['messages'] if m['role']=='user']),2)
        self.assertIn('Will develop',response['message'])
        self.assertIn('Not started',response['message'])
        self.assertEqual(cv_service.read_cv(101),SAMPLE.strip())
        asyncio.run(tools.handle_tool_callback(cv_save_callback(101),telegram_user_id=101))
        saved=cv_service.read_cv(101)
        self.assertIn('Will develop',saved)
        self.assertIn('Inventory System',saved)

    def test_cv_ai_rejects_fabricated_evidence_metrics_and_links(self):
        from app.services.cv_ai import validate_analysis
        payload={'messages':[{'role':'user','content':'I built a Python API for scheduling.'}]}
        for fact in (
            {'text':'Built an API','evidence':'I managed a large team'},
            {'text':'Improved speed by 95%','evidence':'I built a Python API'},
            {'text':'https://invented.example','evidence':'I built a Python API'},
        ):
            with self.assertRaises(ValueError):
                validate_analysis({'facts':{'contributions':[fact]}},payload)

    def test_cv_ai_optional_skip_does_not_skip_essential_facts(self):
        cv_service.write_cv(101,SAMPLE)
        tools.start_cv_update(101)
        raw='New Project. I will build the API.'
        incomplete={'facts':{'name':[{'text':'New Project','evidence':'New Project'}]}}
        with patch('app.services.cv_ai.api_available',return_value=True), patch('app.services.cv_ai.analyze_with_api',new=AsyncMock(return_value=incomplete)):
            asyncio.run(tools.handle_text(telegram_user_id=101,text=raw))
        result=asyncio.run(tools.handle_tool_callback('ut:cv:skip',telegram_user_id=101))
        self.assertNotIn('candidate',tools.pending_for(101))
        self.assertIn('انجام',result['message'])
        pending=tools.pending_for(101)
        pending['analysis']['facts']['contributions']=[{'text':'Will build the API.','evidence':'I will build the API.'}]
        result=asyncio.run(tools.handle_tool_callback('ut:cv:skip',telegram_user_id=101))
        self.assertIn('پیش‌نمایش',result['message'])
        self.assertIn('Will build',pending['candidate'])

    def test_cv_ai_worker_fallback_and_cancel_ignore_delayed_result(self):
        from app.worker.apply import apply_work_result
        from app.telegram.bot import review_bot
        cv_service.write_cv(101,SAMPLE)
        tools.start_cv_update(101)
        response=asyncio.run(tools.handle_text(telegram_user_id=101,text='New project: building an API.'))
        self.assertIn('PC Worker',response['message'])
        with self.sessions() as db:
            work=db.query(database.WorkJob).one()
            self.assertEqual(work.job_type,queue.JOB_CV_EDIT)
            self.assertEqual(work.user_id,101)
            claimed=queue.claim_next(db,'pc',only_types={queue.JOB_CV_EDIT})
            payload=json.loads(claimed.payload_json)
            self.assertEqual(payload['messages'][0]['content'],'New project: building an API.')
            self.assertNotIn('base_cv_text',payload)
            asyncio.run(tools.handle_tool_callback('ut:cancel',telegram_user_id=101))
            with patch.object(review_bot,'send_message',new=AsyncMock()) as sender:
                asyncio.run(apply_work_result(db,claimed,{'analysis':{}}))
                sender.assert_not_called()
            self.assertEqual(claimed.status,'done')
        self.assertEqual(cv_service.read_cv(101),SAMPLE.strip())

    def test_cv_ai_api_failure_keeps_answers_for_retry(self):
        cv_service.write_cv(101,SAMPLE)
        tools.start_cv_update(101)
        with patch('app.services.cv_ai.api_available',return_value=True), patch('app.services.cv_ai.analyze_with_api',new=AsyncMock(side_effect=RuntimeError('provider unavailable'))):
            response=asyncio.run(tools.handle_text(telegram_user_id=101,text='New project: building an API.'))
        self.assertIn('دوباره',response['message'])
        self.assertEqual(tools.pending_for(101)['step'],'ai_error')
        self.assertEqual(len(tools.pending_for(101)['messages']),1)
        response=asyncio.run(tools.handle_tool_callback('ut:cv:retry',telegram_user_id=101))
        self.assertEqual(len(tools.pending_for(101)['messages']),1)
        self.assertIn('PC Worker',response['message'])

    def test_cv_ai_text_corrections_invalidate_old_save(self):
        cv_service.write_cv(101,SAMPLE)
        tools.start_cv_update(101,section='replace')
        tools.preview_cv_update(101,SAMPLE.replace('Inventory System','Updated System'))
        # AI edits invalidate the previous preview before another request is queued.
        pending=tools.pending_for(101)
        pending['section']='projects'
        asyncio.run(tools.handle_text(telegram_user_id=101,text='Actually the project has not started.'))
        self.assertNotIn('candidate',pending)
        asyncio.run(tools.handle_tool_callback(cv_save_callback(101),telegram_user_id=101))
        self.assertEqual(cv_service.read_cv(101),SAMPLE.strip())

    def test_cv_ai_worker_delivery_only_to_request_owner(self):
        from app.worker.apply import apply_work_result
        from app.telegram.bot import review_bot
        cv_service.write_cv(101,SAMPLE)
        tools.start_cv_update(101)
        asyncio.run(tools.handle_text(telegram_user_id=101,text='New project: building an API.'))
        with self.sessions() as db:
            work=queue.claim_next(db,'pc',only_types={queue.JOB_CV_EDIT})
            with patch.object(review_bot,'send_message',new=AsyncMock()) as sender:
                asyncio.run(apply_work_result(db,work,{'analysis':{'facts':{'name':[{'text':'New project','evidence':'New project'}]}}}))
                self.assertEqual(sender.call_args.kwargs['chat_id'],101)
            self.assertEqual(work.status,'done')
        self.assertEqual(cv_service.read_cv(202),'')

    def test_cv_ai_api_uses_configured_writing_role(self):
        from app.services.cv_ai import analyze_with_api
        payload={'section':'projects','language':'en','messages':[{'role':'user','content':'My Project. I will build an API.'}]}
        response={'facts':{'name':[{'text':'My Project','evidence':'My Project'}]}}
        with patch('app.ai.codex.call_codex',new=AsyncMock(return_value=json.dumps(response))) as model:
            result=asyncio.run(analyze_with_api(payload))
        self.assertIn('name',result['facts'])
        self.assertIn('You interview a user', model.call_args.args[0])
        self.assertEqual(settings.proposal_provider,'codex')

    def test_cv_ai_worker_writes_only_interview_workspace(self):
        from app.worker.cv_edit import run_cv_edit
        from types import SimpleNamespace
        import uuid
        request_id=uuid.uuid4().hex
        payload={'telegram_user_id':101,'request_id':request_id,'section':'projects','language':'en',
                 'messages':[{'role':'user','content':'My Project. I will build an API.'}]}
        response={'facts':{'name':[{'text':'My Project','evidence':'My Project'}]}}
        def fake_agent(cmd,**kwargs):
            self.assertIn('--sandbox',cmd)
            workspace=Path(kwargs['cwd'])
            self.assertTrue(workspace.is_relative_to(self.root/'worker_cv_edits/101'))
            prompt_text=(workspace/'request.md').read_text(encoding='utf-8')
            self.assertIn('My Project',prompt_text)
            self.assertNotIn('Alex Example',prompt_text)
            answer=Path(cmd[cmd.index('--output-last-message')+1])
            answer.write_text(json.dumps(response),encoding='utf-8')
            self.assertEqual(cmd[cmd.index('--sandbox')+1],'read-only')
            return SimpleNamespace(returncode=0)
        with patch('app.worker.cv_edit.DATA_DIR',self.root),patch('app.ai.codex.find_codex_cmd',return_value=['codex']),patch('app.worker.cv_edit.subprocess.run',side_effect=fake_agent):
            result=asyncio.run(run_cv_edit(payload))
        self.assertEqual(result['analysis']['facts']['name'][0]['text'],'My Project')

    def test_cv_ai_old_result_cannot_overwrite_new_session(self):
        cv_service.write_cv(101,SAMPLE)
        tools.start_cv_update(101)
        asyncio.run(tools.handle_text(telegram_user_id=101,text='My Project. I will build an API.'))
        with self.sessions() as db:
            payload=json.loads(db.query(database.WorkJob).one().payload_json)
        tools.start_cv_update(101)
        result=tools.finish_cv_analysis(101,payload,{'facts':{'name':[{'text':'My Project','evidence':'My Project'}]}})
        self.assertTrue(result['ignored'])
        self.assertEqual(tools.pending_for(101)['messages'],[])
        self.assertNotIn('analysis',tools.pending_for(101))

    def test_cv_ai_invalid_worker_result_offers_retry(self):
        from app.worker.apply import apply_work_result
        cv_service.write_cv(101,SAMPLE)
        tools.start_cv_update(101)
        asyncio.run(tools.handle_text(telegram_user_id=101,text='My Project. I will build an API.'))
        with self.sessions() as db:
            work=queue.claim_next(db,'pc',only_types={queue.JOB_CV_EDIT})
            result=asyncio.run(apply_work_result(db,work,{'analysis':{'facts':{'name':[{'text':'Fake','evidence':'Never said this'}]}}}))
            self.assertFalse(result['ok'])
            self.assertEqual(work.status,'failed')
        self.assertEqual(tools.pending_for(101)['step'],'ai_error')
        self.assertEqual(cv_service.read_cv(101),SAMPLE.strip())

    def test_cv_save_requires_the_exact_preview_confirmation(self):
        cv_service.write_cv(101,SAMPLE)
        tools.start_cv_update(101,section='replace')
        tools.preview_cv_update(101,SAMPLE.replace('Inventory System','First Revision'))
        old_callback=cv_save_callback(101)
        tools.preview_cv_update(101,SAMPLE.replace('Inventory System','Second Revision'))
        result=asyncio.run(tools.handle_tool_callback(old_callback,telegram_user_id=101))
        self.assertIn('منقضی',result['message'])
        self.assertEqual(cv_service.read_cv(101),SAMPLE.strip())
        asyncio.run(tools.handle_tool_callback(cv_save_callback(101),telegram_user_id=101))
        self.assertIn('Second Revision',cv_service.read_cv(101))

    def test_legacy_model_settings_cannot_restore_other_providers(self):
        from app.config import Settings
        config=Settings(_env_file=None,ai_provider='groq',ai_screening_provider='gemini',
                        ai_proposal_provider='anthropic',ai_model='llama-old')
        self.assertEqual(config.ai_provider,'codex')
        self.assertEqual(config.screening_provider,'codex')
        self.assertEqual(config.proposal_provider,'codex')
        self.assertEqual(config.default_model,'Codex CLI default')
        config.codex_model='example-codex-model'
        self.assertEqual(config.screening_model(),config.proposal_model())
        self.assertEqual(config.proposal_model(),'example-codex-model')

    def test_all_shared_ai_roles_use_codex_adapter(self):
        from app.ai.evaluator import _call_ai
        from app.linkedin.email_compose import _call_ai as compose
        with patch('app.ai.codex.call_codex',new=AsyncMock(return_value='{"ok":true}')) as call:
            response=asyncio.run(_call_ai('system','input',provider='groq',model='legacy'))
            self.assertIn('true',response)
            call.assert_awaited_once_with('system','input')
        with patch('app.linkedin.email_compose.call_codex_sync',return_value='{"email":"draft"}') as call:
            self.assertIn('draft',compose('instructions','data'))
            call.assert_called_once_with('instructions','data')

    def test_codex_command_has_restricted_sandbox_and_stdin(self):
        from app.ai.codex import codex_command,REQUEST_MODEL
        with patch('app.ai.codex.find_codex_cmd',return_value=['codex']),patch.object(settings,'codex_model','one-model'):
            command=codex_command(self.root,self.root/'answer.txt')
            self.assertEqual(command[-1],'-')
            self.assertEqual(command[command.index('--sandbox')+1],'read-only')
            self.assertEqual(command[command.index('--model')+1],'one-model')
            self.assertIn('--ignore-user-config',command)
            self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',command)
            self.assertIn('model_provider="openai"',command)
            token=REQUEST_MODEL.set('queued-model')
            try:
                command=codex_command(self.root,self.root/'answer.txt')
                self.assertEqual(command[command.index('--model')+1],'queued-model')
            finally:
                REQUEST_MODEL.reset(token)

    def test_codex_text_jobs_are_claimed_without_heavy_mode(self):
        from app.worker.execute import execute_job
        headers={'Authorization':'Bearer test-worker-secret'}
        with patch.object(settings,'queue_heavy_work',False),self.sessions() as db:
            job=queue.enqueue_work(db,queue.JOB_CODEX_TEXT,0,extra={'system':'Return JSON','user':'Test data'},dedupe=False)
            job_id=job.id
        claimed=self.client.post('/api/worker/claim',headers=headers,json={'worker_id':'pc'}).json()['job']
        self.assertEqual(claimed['id'],job_id)
        with patch('app.ai.codex.infer_local',return_value='{"ok":true}') as infer:
            result=asyncio.run(execute_job(queue.JOB_CODEX_TEXT,claimed['payload']))
            infer.assert_called_once_with('Return JSON','Test data')
        response=self.client.post(f'/api/worker/jobs/{job_id}/complete',headers=headers,
             json={'worker_id':'pc','claim_token':claimed['claim_token'],'result':result})
        self.assertEqual(response.status_code,200,response.text)
        with self.sessions() as db:
            row=db.get(database.WorkJob,job_id)
            self.assertEqual(row.status,'done')
            self.assertEqual(json.loads(row.result_json)['text'],'{"ok":true}')

    def test_codex_queue_round_trip_without_provider_fallback(self):
        from app.ai.codex import call_codex_sync
        from app.worker.apply import apply_work_result
        with self.sessions() as db:
            queue.record_heartbeat(db,'pc')
        with patch.object(settings,'codex_execution_mode','queue'):
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending=pool.submit(call_codex_sync,'Return JSON','Only test data')
                job=None
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    with self.sessions() as db:
                        candidate=queue.claim_next(db,'pc',only_types={queue.JOB_CODEX_TEXT})
                        if candidate:
                            job=candidate
                            asyncio.run(apply_work_result(db,job,{'text':'{"ok":true}'}))
                            break
                    time.sleep(0.01)
                self.assertIsNotNone(job)
                self.assertEqual(pending.result(timeout=5),'{"ok":true}')

    def test_codex_offline_worker_fails_without_alternate_ai(self):
        from app.ai.codex import call_codex_sync
        with patch.object(settings,'codex_execution_mode','queue'):
            with self.assertRaisesRegex(RuntimeError,'offline'):
                call_codex_sync('Return JSON','test')
        with self.sessions() as db:
            self.assertEqual(db.query(database.WorkJob).count(),0)

    def test_codex_model_from_queue_is_scoped_to_execution(self):
        from app.ai.codex import REQUEST_MODEL
        from app.worker.execute import execute_job
        seen=[]
        def infer(system,user):
            seen.append(REQUEST_MODEL.get())
            return '{"ok":true}'
        with patch('app.ai.codex.infer_local',side_effect=infer):
            asyncio.run(execute_job(queue.JOB_CODEX_TEXT,{'system':'s','user':'u','_codex_model':'queued-codex'}))
        self.assertEqual(seen,['queued-codex'])
        self.assertIsNone(REQUEST_MODEL.get())

    def test_retired_provider_choices_and_neural_models_stay_disabled(self):
        from app.billing.bot_admin import PROVIDERS as admin_providers
        from app.telegram.bot_settings import PROVIDERS as bot_providers
        from app.rag.store import chroma_available
        from app.rag.embedder import get_embedder
        self.assertEqual(admin_providers,('codex',))
        self.assertEqual(bot_providers,('codex',))
        self.assertFalse(chroma_available())
        with self.assertRaises(RuntimeError):
            get_embedder()
        self.session(admin=True)
        self.assertEqual(self.client.put('/api/settings',json={'ai_provider':'groq'}).status_code,400)
        self.assertEqual(self.client.put('/api/settings',json={'api_key':'unused-test-key'}).status_code,400)

    def test_no_direct_external_model_sdks_remain(self):
        import ast
        root=Path(__file__).resolve().parents[1]/'app'
        banned={'openai','anthropic','fastembed','chromadb'}
        for path in root.rglob('*.py'):
            tree=ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                modules=[]
                if isinstance(node,ast.Import):
                    modules=[alias.name.split('.')[0] for alias in node.names]
                if isinstance(node,ast.ImportFrom) and node.module:
                    modules=[node.module.split('.')[0]]
                self.assertFalse(banned.intersection(modules),str(path))

    def test_codex_structured_resume_is_written_only_to_controlled_paths(self):
        from app.worker.codex_apply import _persist_codex_resume_answer
        out=self.root/'application';out.mkdir()
        raw={'resume_md':SAMPLE,'evaluation_md':'The Python experience supports this role; verify the remaining gaps.',
             'fit_score':70,'recommendation':'Apply','resume_path':'../outside.md','evaluation_path':'../outside-evaluation.md'}
        result=_persist_codex_resume_answer(json.dumps(raw),out,translate_fa=False)
        self.assertEqual(Path(result['resume_path']),out/'resume.md')
        self.assertEqual(Path(result['evaluation_path']),out/'evaluation.md')
        self.assertFalse((self.root/'outside.md').exists())
        self.assertEqual((out/'resume.md').read_text(encoding='utf-8'),SAMPLE)

    def test_codex_invalid_structured_resume_does_not_write_output(self):
        from app.worker.codex_apply import _persist_codex_resume_answer
        out=self.root/'application';out.mkdir()
        with self.assertRaises(ValueError):
            _persist_codex_resume_answer(json.dumps({'resume_md':SAMPLE,'evaluation_md':'short','fit_score':150}),out,translate_fa=False)
        self.assertFalse((out/'resume.md').exists())

    def test_codex_can_find_desktop_cli_without_path(self):
        from app.ai.codex import find_codex_cmd
        if __import__('os').name != 'nt':
            self.skipTest('Windows Desktop path detection')
        executable=self.root/'OpenAI/Codex/bin/test-version/codex.exe'
        executable.parent.mkdir(parents=True);executable.write_bytes(b'test')
        with patch.object(settings,'codex_cli_path',''),patch('app.ai.codex.shutil.which',return_value=None),patch.dict('os.environ',{'LOCALAPPDATA':str(self.root)}):
            self.assertEqual(find_codex_cmd(),[str(executable)])

if __name__=='__main__':
    unittest.main()

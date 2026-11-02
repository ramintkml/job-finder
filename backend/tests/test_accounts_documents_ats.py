"""Account, ownership, document selection and ATS correctness regressions; all offline."""
import asyncio,json,time,unittest
from unittest.mock import patch,AsyncMock
import jwt
from fastapi.testclient import TestClient
import test_regressions as regression
SAMPLE=regression.SAMPLE
from app import database
from app.api import auth
from app.main import app
from app.ats.score import keyword_in_text,score_resume,_is_junk_keyword,markdown_resume_to_dict
from app.services import cv_service

class AccountDocumentTests(unittest.TestCase):
    setUp=regression.RegressionTests.setUp
    tearDown=regression.RegressionTests.tearDown
    session=regression.RegressionTests.session
    def register(self):
        r=self.client.post('/api/auth/register',json={'username':'alex_example','email':'alex@example.com','password':'strong-passphrase-123'})
        self.assertEqual(r.status_code,200,r.text)
        self.client.headers['X-CSRF-Token']=self.client.cookies.get('career_csrf')
        return r.json()
    def test_register_login_jwt_logout_revokes_copied_access(self):
        account=self.register();self.assertFalse(account['is_admin']);self.assertLess(account['telegram_user_id'],0)
        token=self.client.cookies.get(auth.COOKIE)
        claims=jwt.decode(token,auth._signing_key(),algorithms=['HS256'],audience='dashboard',issuer='career-pilot')
        self.assertLessEqual(claims['exp']-claims['iat'],900)
        self.assertEqual(self.client.post('/api/auth/logout').status_code,200)
        self.client.cookies.set(auth.COOKIE,token)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.client.cookies.clear();self.client.headers.pop('X-CSRF-Token',None)
        r=self.client.post('/api/auth/login',json={'username':'ALEX@EXAMPLE.COM','password':'strong-passphrase-123','remember':True})
        self.assertEqual(r.status_code,200,r.text)
        self.assertIn('HttpOnly',r.headers.get('set-cookie',''))
    def test_csrf_and_refresh_rotation(self):
        self.register();old=self.client.cookies.get(auth.REFRESH)
        self.client.headers.pop('X-CSRF-Token')
        self.assertEqual(self.client.post('/api/auth/refresh').status_code,403)
        self.client.headers['X-CSRF-Token']=self.client.cookies.get('career_csrf')
        r=self.client.post('/api/auth/refresh');self.assertEqual(r.status_code,200)
        self.assertNotEqual(old,self.client.cookies.get(auth.REFRESH))
        # Directly verify the old refresh is no longer authorized.
        with self.sessions() as db:self.assertIsNone(db.query(database.AuthSession).filter_by(refresh_hash=auth.digest(old)).first())
    def test_disabled_account_denied_after_login(self):
        a=self.register()
        with self.sessions() as db:
            db.get(database.WebAccount,a['account_id']).is_active=False;db.commit()
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.assertEqual(self.client.post('/api/auth/refresh').status_code,401)
    def test_duplicate_identity_and_weak_password(self):
        self.register()
        self.assertEqual(self.client.post('/api/auth/register',json={'username':'other_name','email':'alex@example.com','password':'strong-passphrase-123'}).status_code,409)
        self.assertEqual(self.client.post('/api/auth/register',json={'username':'new_user','email':'new@example.com','password':'short'}).status_code,422)
    def test_link_keeps_existing_telegram_cv_and_applications(self):
        self.register()
        command=self.client.post('/api/auth/telegram-link').json()['command'];token=command.split()[1]
        auth.consume_link(token,101)
        me=self.client.get('/api/auth/me').json();self.assertEqual(me['telegram_user_id'],101)
        self.assertEqual([r['title'] for r in self.client.get('/api/applications').json()],['User One'])
        with self.assertRaises(ValueError):auth.consume_link(token,202)
    def test_link_never_steals_another_account(self):
        self.register();token=self.client.post('/api/auth/telegram-link').json()['command'].split()[1]
        with self.sessions() as db:
            db.add(database.WebAccount(username='existing',email='existing@example.com',password_hash='x',owner_id=202));db.commit()
        with self.assertRaises(ValueError):auth.consume_link(token,202)
    def test_recovery_generic_single_use_and_session_revocation(self):
        a=self.register();token=self.client.cookies.get(auth.COOKIE)
        with patch.object(auth,'send_reset') as send:
            known=self.client.post('/api/auth/forgot-password',json={'email':'alex@example.com'})
            unknown=self.client.post('/api/auth/forgot-password',json={'email':'unknown@example.com'})
            self.assertEqual(known.json(),unknown.json());raw=send.call_args.args[1]
        r=self.client.post('/api/auth/reset-password',json={'token':raw,'password':'replacement-password-123'});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.assertEqual(self.client.post('/api/auth/reset-password',json={'token':raw,'password':'replacement-password-123'}).status_code,400)
    def test_registration_inside_telegram_session_preserves_owner(self):
        self.session();a=self.register();self.assertEqual(a['telegram_user_id'],101)
    def test_variants_owner_and_full_cv_source_snapshot(self):
        from app.services.documents import request_document
        from app.worker.queue import build_payload
        self.session()
        with self.sessions() as db:
            application=db.get(database.BotApplication,1);application.resume_md=SAMPLE.replace('stock tracking','targeted stock tracking');db.commit()
            with patch.object(cv_service,'read_cv',return_value=SAMPLE+'\nOlder complete work history'):
                item=request_document(db,application,101,'cv','fa')
                self.assertIn('Older complete work history',item.source_text)
                payload=build_payload(db,'document_variant',item.id)
                self.assertEqual(payload['telegram_user_id'],101)
                same=request_document(db,application,101,'cv','fa');self.assertEqual(same.id,item.id)
            resume=request_document(db,application,101,'resume','en');self.assertNotIn('Older complete',resume.source_text)
            item_id=item.id
        self.assertEqual(self.client.post('/api/applications/2/documents',json={'kind':'cv','language':'fa'}).status_code,404)
        self.assertEqual(self.client.get(f'/api/applications/2/documents/{item_id}/docx').status_code,404)
    def test_document_result_owner_not_from_ai(self):
        from app.services.documents import request_document,apply_document
        self.session()
        with self.sessions() as db:
            application=db.get(database.BotApplication,1);application.resume_md=SAMPLE;db.commit()
            item=request_document(db,application,101,'resume','en');job=db.get(database.WorkJob,item.work_job_id)
            job.user_id=202
            with self.assertRaises(ValueError):asyncio.run(apply_document(db,job,{'document':{'full_name':'Injected'}}))
    def test_real_variant_pipeline_with_mocked_codex_and_private_downloads(self):
        from app.services.documents import request_document,generate_document,apply_document
        from app.worker.queue import build_payload
        from app.ats.score import markdown_resume_to_dict
        from app.config import ATS_DIR
        self.session()
        with self.sessions() as db:
            application=db.get(database.BotApplication,1);application.resume_md=SAMPLE;db.commit()
            item=request_document(db,application,101,'resume','en');job=db.get(database.WorkJob,item.work_job_id)
            answer=json.dumps({'document':markdown_resume_to_dict(SAMPLE),'questions':['What dates apply?']})
            with patch('app.ai.codex.infer_local',return_value=answer):
                result=asyncio.run(generate_document(build_payload(db,'document_variant',item.id)))
            with patch('app.services.documents.ATS_DIR',self.root/'artifacts'), patch('app.telegram.bot.review_bot.send_message',new_callable=AsyncMock),patch('app.telegram.bot.review_bot.send_document',new_callable=AsyncMock):
                out=asyncio.run(apply_document(db,job,result));db.commit()
            self.assertTrue(out['ok']);self.assertEqual(item.status,'ready')
            for ext in ('docx','pdf'):
                url=f'/api/applications/1/documents/{item.id}/{ext}'
                self.assertEqual(self.client.get(url).status_code,200)
                stranger=TestClient(app)
                try:
                    stranger.cookies.set(auth.COOKIE,auth.issue_session(202))
                    self.assertEqual(stranger.get(url).status_code,404)
                finally: stranger.close()

    def test_document_job_claimed_with_heavy_mode_off(self):
        from app.services.documents import request_document
        from app.config import settings
        with self.sessions() as db:
            application=db.get(database.BotApplication,1);application.resume_md=SAMPLE;db.commit()
            item=request_document(db,application,101,'resume','fa');work_id=item.work_job_id
        with patch.object(settings,'queue_heavy_work',False):
            r=self.client.post('/api/worker/claim',headers={'Authorization':'Bearer test-worker-secret'},json={'worker_id':'doc-worker'})
        self.assertEqual(r.status_code,200,r.text);job=r.json()['job'];self.assertEqual(job['id'],work_id)
        self.assertEqual(job['payload']['telegram_user_id'],101)
        self.assertTrue(job['claim_token'])

    def test_truthful_resume_and_language_prompt(self):
        from app.worker.codex_apply import _structured_resume_prompt
        from app.services.documents import detect_language
        kwargs=dict(base_cv=SAMPLE,title='مهندس',company='',description='ما به توسعه دهنده پایتون برای توسعه نرم افزار نیاز داریم',guide='',previous_resume='',evaluation='',english_json='',translate_fa=False,improve=False,ats_guidance='')
        prompt=_structured_resume_prompt(**kwargs)
        self.assertIn('normally 1-2 pages',prompt);self.assertIn('Persian resume markdown',prompt)
        self.assertEqual(detect_language('Python engineer building APIs'),'en')

class AtsCorrectnessTests(unittest.TestCase):
    def test_distinct_skills_and_aliases(self):
        for term,text in [('Java','JavaScript'),('SQL','NoSQL'),('Go','Django'),('C','C++'),('C++','C#')]:self.assertFalse(keyword_in_text(term,text),(term,text))
        for term,text in [('SQL','Python, SQL.'),('C++','Uses C++.'),('PostgreSQL','Postgres'),('مدیریت پروژه','تجربه مدیریت پروژه')]:self.assertTrue(keyword_in_text(term,text))
    def test_empty_resume_is_not_35_points(self):
        r=score_resume({},'Python engineer');self.assertEqual(r['total_score'],0);self.assertEqual(r['categories']['formatting'],0)
    def test_words_are_not_quantified_achievements(self):
        r=score_resume({'experience':[{'bullets':['Improved the process']} ]},'Python')
        self.assertEqual(r['categories']['achievements'],0)
        r=score_resume({'experience':[{'bullets':['Reduced latency by 25%']} ]},'Python')
        self.assertGreater(r['categories']['achievements'],0)
    def test_required_missing_counts_more(self):
        r=score_resume({'skills':{'Tools':['Python']},'keywords_from_jd':['Python','Docker'],'required_keywords':['Docker']},'Python Docker')
        self.assertEqual(r['coverage_score'],25)
        self.assertEqual(r['file_health']['status'],'not_checked')
    def test_persian_headings_and_normalization(self):
        self.assertFalse(_is_junk_keyword('مدیریت پروژه'))
        self.assertTrue(keyword_in_text('پایگاه داده','پايگاه داده'))
        parsed=markdown_resume_to_dict('علی رضایی\n## خلاصه حرفه‌ای\nتوسعه نرم افزار\n## مهارت‌ها\nفنی: پایتون، SQL\n## تحصیلات\nکارشناسی کامپیوتر')
        self.assertTrue(parsed['skills']);self.assertTrue(parsed['education'])
    def test_actual_docx_and_pdf_extraction(self):
        import tempfile
        from pathlib import Path
        from app.ats.docx_export import export_resume_docx
        from app.ats.pdf_export import export_resume_pdf
        from app.ats.artifact_check import inspect_files
        resume=markdown_resume_to_dict(SAMPLE)
        with tempfile.TemporaryDirectory() as tmp:
            docx=Path(tmp)/'resume.docx';pdf=Path(tmp)/'resume.pdf'
            export_resume_docx(resume,docx);export_resume_pdf(resume,pdf)
            r=inspect_files(docx,pdf,expected_name=resume['full_name'],expected_email=resume['email'])
            self.assertEqual(r['status'],'passed',r)
            r=inspect_files(docx,pdf,expected_email='missing@example.com');self.assertEqual(r['status'],'needs_review')

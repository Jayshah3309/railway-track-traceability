import hashlib
import io
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import unittest
from PIL import Image
from railtrack import Store
from webapp import create_app,initialize_web,add_user,normalize_photo

PASSWORD='Synthetic-password-2026'


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'rail.sqlite3'
        item=Store(self.db,initialize=True);item.register('DEMO-SLEEPER-001','sleeper','Synthetic bench')
        initialize_web(item)
        for user,role in [('inspector','inspector'),('supervisor','supervisor'),('maintainer','maintainer'),('other-worker','maintainer'),('verifier','verifier')]:
            add_user(item,user,PASSWORD,role)
        item.close()
        self.app=create_app(dict(TESTING=True,DATABASE=str(self.db),SECRET_KEY='synthetic-test-secret-not-for-real-use'))
        self.client=self.app.test_client()

    def tearDown(self):self.tmp.cleanup()

    def csrf(self,client=None):
        client=client or self.client
        with client.session_transaction() as s:return s['csrf']

    def login(self,user='inspector',password=PASSWORD,client=None):
        client=client or self.client;client.get('/login')
        return client.post('/login',data=dict(csrf=self.csrf(client),username=user,password=password))

    def post(self,path,data=None,client=None,**kwargs):
        client=client or self.client;data=dict(data or {},csrf=self.csrf(client))
        return client.post(path,data=data,**kwargs)

    def inspect(self,photo=None,note='Synthetic observation'):
        self.login('inspector');data=dict(note=note,actor='forged-user')
        if photo is not None:data['photo']=(io.BytesIO(photo),'untrusted-name.png')
        result=self.post('/assets/DEMO-SLEEPER-001/inspections',data)
        self.assertEqual(result.status_code,302,result.data)
        return result.location.rsplit('/',1)[1]

    def action(self,issue,action,user,note='Synthetic update',**kwargs):
        self.login(user)
        return self.post('/issues/'+issue+'/action',dict(action=action,note=note,**kwargs))

    def connect(self):
        db=sqlite3.connect(self.db);db.row_factory=sqlite3.Row;return db

    def test_schema_upgrade_preserves_cli_records(self):
        item=Store(self.db);issue=item.inspect('DEMO-SLEEPER-001','legacy','CLI note');initialize_web(item)
        self.assertEqual(item.db.execute('PRAGMA user_version').fetchone()[0],1)
        self.assertEqual(len(item.history('DEMO-SLEEPER-001')),1);item.close()
        self.login('supervisor')
        self.assertIn(b'CLI-origin',self.client.get('/issues/'+issue).data)
        self.assertEqual(self.post('/issues/'+issue+'/action',dict(action='assign',assignee='maintainer',note='Try')).status_code,409)

    def test_full_workflow_and_reopen(self):
        issue=self.inspect()
        for action,user,extra in [('assign','supervisor',dict(assignee='maintainer')),('resolve','maintainer',{}),('verify','verifier',{}),('reopen','supervisor',{})]:
            self.assertEqual(self.action(issue,action,user,**extra).status_code,302)
        with self.connect() as db:
            self.assertEqual([r[0] for r in db.execute('SELECT to_status FROM events WHERE issue_id=? ORDER BY seq',(issue,))],['OPEN','ASSIGNED','RESOLVED','VERIFIED','OPEN'])
            self.assertIsNone(db.execute('SELECT * FROM web_assignments WHERE issue_id=?',(issue,)).fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM web_actions WHERE issue_id=?',(issue,)).fetchone()[0],5)

    def test_wrong_role_and_unassigned_worker_rejected(self):
        issue=self.inspect()
        self.assertEqual(self.action(issue,'assign','inspector',assignee='maintainer').status_code,403)
        self.assertEqual(self.action(issue,'assign','supervisor',assignee='maintainer').status_code,302)
        self.assertEqual(self.action(issue,'resolve','other-worker').status_code,403)
        self.assertEqual(self.action(issue,'verify','maintainer').status_code,403)
        with self.connect() as db:self.assertEqual(db.execute('SELECT status FROM issues WHERE id=?',(issue,)).fetchone()[0],'ASSIGNED')

    def test_no_state_skips_or_repeated_resolve(self):
        issue=self.inspect()
        self.assertEqual(self.action(issue,'verify','verifier').status_code,409)
        self.action(issue,'assign','supervisor',assignee='maintainer')
        self.action(issue,'resolve','maintainer')
        self.assertEqual(self.action(issue,'resolve','maintainer').status_code,409)
        with self.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM events WHERE issue_id=?',(issue,)).fetchone()[0],3)

    def test_reassignment_and_rework_history(self):
        issue=self.inspect();self.action(issue,'assign','supervisor',assignee='maintainer')
        self.action(issue,'assign','supervisor',assignee='other-worker')
        self.assertEqual(self.action(issue,'resolve','maintainer').status_code,403)
        self.action(issue,'resolve','other-worker')
        self.action(issue,'assign','supervisor',assignee='maintainer')
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT assignee FROM web_assignments WHERE issue_id=?',(issue,)).fetchone()[0],'maintainer')
            self.assertEqual(db.execute('SELECT status FROM issues WHERE id=?',(issue,)).fetchone()[0],'ASSIGNED')

    def test_csrf_and_anonymous_access(self):
        for path in ['/','/export.csv','/assets/DEMO-SLEEPER-001','/issues/no/photo']:
            self.assertEqual(self.client.get(path).status_code,302)
        self.assertEqual(self.client.post('/login',data=dict(username='inspector',password=PASSWORD)).status_code,400)
        self.login('supervisor')
        self.assertEqual(self.client.post('/assets',data=dict(asset_id='DEMO-NEW-001',kind='sleeper',location='Demo')).status_code,400)

    def test_server_identity_and_autoescaping(self):
        issue=self.inspect(note='<script>alert(1)</script>')
        page=self.client.get('/issues/'+issue)
        self.assertNotIn(b'<script>',page.data);self.assertIn(b'&lt;script&gt;',page.data)
        with self.connect() as db:self.assertEqual(db.execute('SELECT actor FROM issues WHERE id=?',(issue,)).fetchone()[0],'inspector')

    def test_session_revocation_and_cookie_flags(self):
        response=self.login()
        cookie=response.headers.get('Set-Cookie','')
        self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Lax',cookie)
        stolen=self.client.get_cookie('railtrack_session').value
        self.post('/logout')
        other=self.app.test_client();other.set_cookie('railtrack_session',stolen)
        self.assertEqual(other.get('/').status_code,302)
        with self.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM web_sessions').fetchone()[0],0)

    def test_expired_and_disabled_sessions(self):
        self.login()
        with self.connect() as db:db.execute('UPDATE web_sessions SET expires=0')
        self.assertEqual(self.client.get('/').status_code,302)
        self.login()
        result=self.app.test_cli_runner().invoke(args=['disable-user','inspector'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(self.client.get('/').status_code,302)

    def test_login_lockout(self):
        for _ in range(5):self.assertEqual(self.login(password='wrong-password').status_code,401)
        self.assertEqual(self.login().status_code,429)
        with self.connect() as db:db.execute("UPDATE web_login_attempts SET blocked_until=?",(int(time.time())-1,))
        self.assertEqual(self.login().status_code,302)

    def test_independent_verifier_check(self):
        issue=self.inspect();self.action(issue,'assign','supervisor',assignee='maintainer');self.action(issue,'resolve','maintainer')
        # Simulate a trusted administrator changing the reporter's role; server must still deny self-review.
        with self.connect() as db:db.execute("UPDATE web_users SET role='verifier' WHERE username='inspector'")
        self.assertEqual(self.action(issue,'verify','inspector').status_code,403)

    def test_photo_decoding_metadata_and_hash(self):
        source=io.BytesIO();image=Image.new('RGB',(40,30),'blue')
        exif=Image.Exif();exif[270]='synthetic-metadata-must-not-be-retained'
        image.save(source,format='JPEG',exif=exif)
        raw=source.getvalue();issue=self.inspect(raw)
        response=self.client.get('/issues/'+issue+'/photo')
        self.assertEqual(response.status_code,200);self.assertEqual(response.mimetype,'image/jpeg')
        self.assertNotIn(b'synthetic-metadata-must-not-be-retained',response.data)
        with Image.open(io.BytesIO(response.data)) as photo:self.assertEqual(photo.format,'JPEG');self.assertEqual(len(photo.getexif()),0)
        with self.connect() as db:
            row=db.execute('SELECT * FROM web_inspections WHERE issue_id=?',(issue,)).fetchone()
            self.assertEqual(row['original_sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(row['normalized_sha256'],hashlib.sha256(response.data).hexdigest())
            db.execute("UPDATE issues SET photo=X'00' WHERE id=?",(issue,))
        self.assertEqual(self.client.get('/issues/'+issue+'/photo').status_code,409)

    def test_bad_photo_and_pixel_limit(self):
        for raw in [b'not an image',b'\x89PNG\r\n\x1a\nsynthetic-header-only',b'x'*(5*1024*1024+1)]:
            with self.subTest(raw_size=len(raw)),self.assertRaises(ValueError):normalize_photo(raw)
        out=io.BytesIO();Image.new('1',(4000,4000)).save(out,format='PNG')
        with self.assertRaises(ValueError):normalize_photo(out.getvalue())
        self.login()
        result=self.post('/assets/DEMO-SLEEPER-001/inspections',dict(note='Bad photo',photo=(io.BytesIO(b'fake'),'fake.png')))
        self.assertEqual(result.status_code,400)
        with self.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM issues').fetchone()[0],0)

    def test_qr_lookup_and_export(self):
        issue=self.inspect(note='=SUM(1,2)')
        self.assertEqual(self.client.get('/lookup?payload=RAILASSET:1:DEMO-SLEEPER-001').status_code,302)
        self.assertEqual(self.client.get('/assets/DEMO-SLEEPER-001/label.svg').mimetype,'image/svg+xml')
        response=self.client.get('/export.csv');self.assertEqual(response.status_code,200)
        self.assertIn(b"'=SUM(1,2)",response.data);self.assertIn(b'web',response.data)
        self.assertNotIn(b'password_hash',response.data)

    def test_invalid_assignment_rolls_back(self):
        issue=self.inspect()
        self.assertEqual(self.action(issue,'assign','supervisor',assignee='verifier').status_code,400)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM issues WHERE id=?',(issue,)).fetchone()[0],'OPEN')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events WHERE issue_id=?',(issue,)).fetchone()[0],1)

    def test_register_assets_roles_and_security_headers(self):
        self.login('inspector')
        data=dict(asset_id='DEMO-NEW-001',kind='sleeper',location='Demo')
        self.assertEqual(self.post('/assets',data).status_code,403)
        self.login('supervisor');self.assertEqual(self.post('/assets',data).status_code,302)
        response=self.client.get('/')
        self.assertEqual(response.status_code,200);self.assertIn(b'DEMO-NEW-001',response.data)
        self.assertEqual(response.headers['X-Frame-Options'],'DENY')
        self.assertIn("script-src 'none'",response.headers['Content-Security-Policy'])
        self.assertEqual(self.client.get('/',headers={'Host':'untrusted.example'}).status_code,400)


if __name__=='__main__':unittest.main()

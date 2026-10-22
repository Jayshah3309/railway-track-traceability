"""Authenticated local inspection portal, alongside the original reference CLI."""
import csv
from datetime import timedelta
from functools import wraps
import hashlib
import io
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid
import warnings

import click
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.security import generate_password_hash, check_password_hash
from railtrack import Store, PREFIX, MAX_PHOTO, asset_id, text, stamp, safe_cell

ROLES = ('inspector','supervisor','maintainer','verifier')
USERNAME = re.compile(r'[a-z][a-z0-9_-]{2,39}\Z')
DUMMY_HASH = generate_password_hash('not-a-real-user-password')
WEB_SCHEMA = """
CREATE TABLE IF NOT EXISTS web_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS web_users(
 username TEXT PRIMARY KEY,password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('inspector','supervisor','maintainer','verifier')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)));
CREATE TABLE IF NOT EXISTS web_sessions(
 token_hash TEXT PRIMARY KEY,username TEXT NOT NULL REFERENCES web_users(username),expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS web_login_attempts(
 username TEXT PRIMARY KEY,failures INTEGER NOT NULL,blocked_until INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS web_assignments(
 issue_id TEXT PRIMARY KEY REFERENCES issues(id),assignee TEXT NOT NULL REFERENCES web_users(username));
CREATE TABLE IF NOT EXISTS web_inspections(
 issue_id TEXT PRIMARY KEY REFERENCES issues(id),reporter TEXT NOT NULL REFERENCES web_users(username),
 original_sha256 TEXT,normalized_sha256 TEXT);
CREATE TABLE IF NOT EXISTS web_actions(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,issue_id TEXT NOT NULL REFERENCES issues(id),
 actor TEXT NOT NULL REFERENCES web_users(username),action TEXT NOT NULL,
 assignee TEXT,note TEXT NOT NULL,created_at TEXT NOT NULL);
"""


def initialize_web(store):
    db=store.db
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'web_settings' in tables:
        row=db.execute("SELECT value FROM web_settings WHERE key='schema_version'").fetchone()
        if not row or row[0]!='1':raise ValueError('Unsupported web schema')
    elif any(name.startswith('web_') for name in tables):
        raise ValueError('Refusing unrelated or partial web schema')
    db.executescript('BEGIN IMMEDIATE;\n'+WEB_SCHEMA+"\nINSERT OR IGNORE INTO web_settings VALUES('schema_version','1');\nCOMMIT;")


def add_user(store, username, password, role):
    if not USERNAME.fullmatch(username) or role not in ROLES:raise ValueError('Invalid username or role')
    if not 12<=len(password)<=128:raise ValueError('Password length must be 12..128 characters')
    encoded=generate_password_hash(password)
    with store.db:
        store.db.execute('INSERT INTO web_users(username,password_hash,role) VALUES(?,?,?)',(username,encoded,role))


def normalize_photo(raw):
    """Only JPEG/PNG decoders; bounded pixels; retain normalized JPEG, not source metadata."""
    if not raw or len(raw)>MAX_PHOTO:raise ValueError('Photo must be 1 byte to 5 MiB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw),formats=('JPEG','PNG')) as image:
                width,height=image.size
                if width*height>12_000_000 or width<1 or height<1:raise ValueError('Photo exceeds 12 megapixels')
                if getattr(image,'n_frames',1)!=1:raise ValueError('Animated photos are unsupported')
                image.verify()
            with Image.open(io.BytesIO(raw),formats=('JPEG','PNG')) as image:
                image.load()
                oriented=ImageOps.exif_transpose(image).convert('RGB')
                oriented.thumbnail((1600,1600))
                clean=Image.new('RGB',oriented.size)
                clean.paste(oriented)
                out=io.BytesIO();clean.save(out,format='JPEG',quality=85)
                normalized=out.getvalue()
    except (UnidentifiedImageError,OSError,SyntaxError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
        raise ValueError('Photo must be a decodable JPEG or PNG') from exc
    if len(normalized)>MAX_PHOTO:raise ValueError('Normalized photo exceeds storage limit')
    return normalized,hashlib.sha256(raw).hexdigest(),hashlib.sha256(normalized).hexdigest()


def local_secret(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/'session.key'
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        return path.read_text().strip()
    value=secrets.token_hex(32)
    with os.fdopen(fd,'w') as handle:handle.write(value)
    return value


def create_app(test_config=None):
    app=Flask(__name__,instance_relative_config=True)
    app.config.from_mapping(DATABASE=str(Path(__file__).parent/'data/railway.sqlite3'),
        SECRET_KEY=os.getenv('RAILTRACK_SECRET'),SESSION_COOKIE_NAME='railtrack_session',
        SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=False,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=1),MAX_CONTENT_LENGTH=MAX_PHOTO+128*1024,
        MAX_FORM_MEMORY_SIZE=32*1024,MAX_FORM_PARTS=20,TRUSTED_HOSTS=['localhost','127.0.0.1','[::1]'])
    if test_config:app.config.update(test_config)
    if not app.config['SECRET_KEY']:app.config['SECRET_KEY']=local_secret(app.instance_path)
    if len(app.config['SECRET_KEY'])<32:raise ValueError('Session secret must contain at least 32 characters')

    def store():
        if 'store' not in g:g.store=Store(app.config['DATABASE'])
        return g.store

    @app.teardown_appcontext
    def close_store(error):
        item=g.pop('store',None)
        if item:item.close()

    def csrf():
        if 'csrf' not in session:session['csrf']=secrets.token_urlsafe(32)
        return session['csrf']

    app.jinja_env.globals['csrf_token']=csrf
    app.jinja_env.globals['qr_prefix']=PREFIX

    @app.before_request
    def authenticate_and_protect():
        g.user=None
        if request.endpoint=='static':return
        if request.method=='POST':
            supplied=request.form.get('csrf','')
            expected=session.get('csrf','')
            if not expected or not secrets.compare_digest(supplied,expected):abort(400,'Invalid CSRF token; reload the form')
        sid=session.get('sid')
        if sid:
            row=store().db.execute('SELECT u.username,u.role FROM web_sessions s JOIN web_users u ON u.username=s.username WHERE s.token_hash=? AND s.expires>? AND u.active=1',
                (hashlib.sha256(sid.encode()).hexdigest(),int(time.time()))).fetchone()
            if row:g.user=dict(row)
            else:session.clear()

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; img-src 'self'; script-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['Cache-Control']='no-store'
        return response

    def login_required(view):
        @wraps(view)
        def wrapped(*args,**kwargs):
            if not g.user:return redirect(url_for('login'))
            return view(*args,**kwargs)
        return wrapped

    def require_role(*roles):
        if g.user['role'] not in roles:abort(403,'This role cannot perform that action')

    def issue_row(issue):
        row=store().db.execute('SELECT i.id,i.asset_id,i.status,i.note,i.actor,i.created_at,i.photo_sha256,a.assignee,w.reporter,w.original_sha256,w.normalized_sha256 FROM issues i LEFT JOIN web_assignments a ON a.issue_id=i.id LEFT JOIN web_inspections w ON w.issue_id=i.id WHERE i.id=?',(issue,)).fetchone()
        if not row:abort(404,'Issue not found')
        return dict(row)

    @app.errorhandler(ValueError)
    def validation_error(error):
        return render_template('portal.html',page='error',message=str(error)),400

    @app.errorhandler(sqlite3.IntegrityError)
    def integrity_error(error):
        return render_template('portal.html',page='error',message='Duplicate or invalid record; reload before retrying'),409

    @app.errorhandler(sqlite3.OperationalError)
    def storage_error(error):
        app.logger.error('Database operation failed: %s',error)
        return render_template('portal.html',page='error',message='Database unavailable or web schema not initialized. See setup guide.'),503

    @app.route('/login',methods=['GET','POST'])
    def login():
        if request.method=='POST':
            username=request.form.get('username','').strip().lower()
            password=request.form.get('password','')
            if not USERNAME.fullmatch(username) or len(password)>128:abort(400,'Invalid login fields')
            db=store().db;now=int(time.time())
            attempt=db.execute('SELECT failures,blocked_until FROM web_login_attempts WHERE username=?',(username,)).fetchone()
            if attempt and attempt['blocked_until']>now:
                return render_template('portal.html',page='login',login_error='Sign-in temporarily unavailable; retry later'),429
            user=db.execute('SELECT * FROM web_users WHERE username=?',(username,)).fetchone()
            valid=check_password_hash(user['password_hash'] if user else DUMMY_HASH,password)
            if not user or not valid or not user['active']:
                failures=(attempt['failures'] if attempt and attempt['blocked_until']==0 else 0)+1
                with db:db.execute('INSERT INTO web_login_attempts VALUES(?,?,?) ON CONFLICT(username) DO UPDATE SET failures=excluded.failures,blocked_until=excluded.blocked_until',
                    (username,failures,now+900 if failures>=5 else 0))
                return render_template('portal.html',page='login',login_error='Invalid username or password'),401
            sid=secrets.token_urlsafe(32)
            with db:
                db.execute('DELETE FROM web_sessions WHERE expires<=?',(now,))
                db.execute('DELETE FROM web_login_attempts WHERE username=?',(username,))
                db.execute('INSERT INTO web_sessions VALUES(?,?,?)',(hashlib.sha256(sid.encode()).hexdigest(),username,now+3600))
            session.clear();session['sid']=sid;session.permanent=True;csrf()
            return redirect(url_for('dashboard'))
        return render_template('portal.html',page='login')

    @app.post('/logout')
    @login_required
    def logout():
        with store().db:store().db.execute('DELETE FROM web_sessions WHERE token_hash=?',(hashlib.sha256(session['sid'].encode()).hexdigest(),))
        session.clear();return redirect(url_for('login'))

    @app.get('/')
    @login_required
    def dashboard():
        status=request.args.get('status','')
        if status and status not in ('OPEN','ASSIGNED','RESOLVED','VERIFIED'):raise ValueError('Unknown status filter')
        db=store().db
        assets=[dict(r) for r in db.execute('SELECT a.*,COUNT(i.id) AS issue_count FROM assets a LEFT JOIN issues i ON i.asset_id=a.id GROUP BY a.id ORDER BY a.id LIMIT 200')]
        sql='SELECT i.id,i.asset_id,i.status,i.note,i.created_at,a.assignee FROM issues i LEFT JOIN web_assignments a ON a.issue_id=i.id'
        params=[]
        if status:sql+=' WHERE i.status=?';params.append(status)
        issues=[dict(r) for r in db.execute(sql+' ORDER BY i.created_at DESC,i.id LIMIT 200',params)]
        counts={r[0]:r[1] for r in db.execute('SELECT status,COUNT(*) FROM issues GROUP BY status')}
        return render_template('portal.html',page='dashboard',assets=assets,issues=issues,counts=counts,status=status)

    @app.post('/assets')
    @login_required
    def register_asset():
        require_role('supervisor')
        store().register(request.form.get('asset_id',''),request.form.get('kind',''),request.form.get('location',''))
        flash('Asset registered');return redirect(url_for('dashboard'))

    @app.get('/lookup')
    @login_required
    def lookup():return redirect(url_for('asset_detail',aid=asset_id(request.args.get('payload',''))))

    @app.get('/assets/<aid>')
    @login_required
    def asset_detail(aid):
        aid=store().require_asset(aid)
        asset=dict(store().db.execute('SELECT * FROM assets WHERE id=?',(aid,)).fetchone())
        issues=[dict(r) for r in store().db.execute('SELECT id,status,note,created_at FROM issues WHERE asset_id=? ORDER BY created_at DESC,id LIMIT 200',(aid,))]
        return render_template('portal.html',page='asset',asset=asset,issues=issues)

    @app.get('/assets/<aid>/label.svg')
    @login_required
    def qr_label(aid):
        import qrcode
        from qrcode.image.svg import SvgPathImage
        aid=store().require_asset(aid)
        out=io.BytesIO();qrcode.make(PREFIX+aid,image_factory=SvgPathImage).save(out)
        return Response(out.getvalue(),mimetype='image/svg+xml')

    @app.post('/assets/<aid>/inspections')
    @login_required
    def inspect_asset(aid):
        require_role('inspector')
        aid=store().require_asset(aid);note=text(request.form.get('note',''),500)
        upload=request.files.get('photo')
        normalized=original_hash=normalized_hash=None
        if upload and upload.filename:
            normalized,original_hash,normalized_hash=normalize_photo(upload.stream.read(MAX_PHOTO+1))
        issue=uuid.uuid4().hex;now=stamp();actor=g.user['username'];db=store().db
        with db:
            db.execute('INSERT INTO issues VALUES(?,?,?,?,?,?,?,?)',(issue,aid,'OPEN',note,actor,now,normalized_hash,normalized))
            db.execute("INSERT INTO events(issue_id,from_status,to_status,actor,note,created_at) VALUES(?,NULL,'OPEN',?,?,?)",(issue,actor,note,now))
            db.execute('INSERT INTO web_inspections VALUES(?,?,?,?)',(issue,actor,original_hash,normalized_hash))
            db.execute('INSERT INTO web_actions(issue_id,actor,action,note,created_at) VALUES(?,?,?,?,?)',(issue,actor,'INSPECT',note,now))
        flash('Inspection recorded');return redirect(url_for('issue_detail',issue=issue))

    @app.get('/issues/<issue>')
    @login_required
    def issue_detail(issue):
        row=issue_row(issue);db=store().db
        events=[dict(r) for r in db.execute('SELECT * FROM events WHERE issue_id=? ORDER BY seq',(issue,))]
        actions=[dict(r) for r in db.execute('SELECT * FROM web_actions WHERE issue_id=? ORDER BY seq',(issue,))]
        maintainers=[r[0] for r in db.execute("SELECT username FROM web_users WHERE role='maintainer' AND active=1 ORDER BY username")]
        return render_template('portal.html',page='issue',issue=row,events=events,actions=actions,maintainers=maintainers)

    @app.post('/issues/<issue>/action')
    @login_required
    def issue_action(issue):
        action=request.form.get('action','');note=text(request.form.get('note',''),500)
        actor=g.user['username'];role=g.user['role'];db=store().db
        with db:
            db.execute('BEGIN IMMEDIATE')
            row=issue_row(issue);old=row['status'];assignee=row['assignee'];new=old
            # Existing CLI records may be read, but must not silently acquire authenticated provenance.
            if row['reporter'] is None:abort(409,'CLI-origin issue is read-only in the portal; create a web inspection')
            if action=='assign':
                if role!='supervisor':abort(403)
                if old not in ('OPEN','ASSIGNED','RESOLVED'):abort(409,'Cannot assign this state')
                assignee=request.form.get('assignee','')
                worker=db.execute("SELECT 1 FROM web_users WHERE username=? AND role='maintainer' AND active=1",(assignee,)).fetchone()
                if not worker:raise ValueError('Select an active maintainer')
                new='ASSIGNED'
                db.execute('INSERT INTO web_assignments VALUES(?,?) ON CONFLICT(issue_id) DO UPDATE SET assignee=excluded.assignee',(issue,assignee))
            elif action=='resolve':
                if role!='maintainer' or assignee!=actor:abort(403)
                if old!='ASSIGNED':abort(409,'Only ASSIGNED issues can be resolved')
                new='RESOLVED'
            elif action=='verify':
                if role!='verifier' or actor in (row['reporter'],assignee):abort(403)
                if old!='RESOLVED':abort(409,'Only RESOLVED issues can be verified')
                new='VERIFIED'
            elif action=='reopen':
                if role!='supervisor':abort(403)
                if old!='VERIFIED':abort(409,'Only VERIFIED issues can be reopened')
                new='OPEN';db.execute('DELETE FROM web_assignments WHERE issue_id=?',(issue,));assignee=None
            else:raise ValueError('Unknown workflow action')
            db.execute('UPDATE issues SET status=? WHERE id=?',(new,issue))
            db.execute('INSERT INTO events(issue_id,from_status,to_status,actor,note,created_at) VALUES(?,?,?,?,?,?)',(issue,old,new,actor,note,stamp()))
            db.execute('INSERT INTO web_actions(issue_id,actor,action,assignee,note,created_at) VALUES(?,?,?,?,?,?)',(issue,actor,action.upper(),assignee,note,stamp()))
        flash('Workflow updated');return redirect(url_for('issue_detail',issue=issue))

    @app.get('/issues/<issue>/photo')
    @login_required
    def photo(issue):
        row=issue_row(issue)
        if not row['normalized_sha256']:abort(404,'No web-normalized image')
        raw=store().db.execute('SELECT photo FROM issues WHERE id=?',(issue,)).fetchone()[0]
        if not raw or hashlib.sha256(raw).hexdigest()!=row['normalized_sha256']:abort(409,'Evidence checksum mismatch')
        return Response(raw,mimetype='image/jpeg',headers={'Content-Disposition':'inline; filename="inspection.jpg"'})

    @app.get('/export.csv')
    @login_required
    def export():
        out=io.StringIO(newline='');writer=csv.writer(out)
        writer.writerow(['id','asset_id','status','assignee','note','actor','created_at','photo_sha256','origin'])
        for row in store().db.execute('SELECT i.id,i.asset_id,i.status,a.assignee,i.note,i.actor,i.created_at,i.photo_sha256,w.reporter FROM issues i LEFT JOIN web_assignments a ON a.issue_id=i.id LEFT JOIN web_inspections w ON w.issue_id=i.id ORDER BY i.created_at,i.id'):
            writer.writerow([safe_cell(v) for v in tuple(row)[:-1]]+['web' if row['reporter'] else 'CLI'])
        return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="inspection-report.csv"'})

    @app.cli.command('init-web')
    def init_web_command():
        item=Store(app.config['DATABASE'],initialize=True)
        try:initialize_web(item)
        finally:item.close()
        click.echo('Core schema retained; web schema ready')

    @app.cli.command('create-user')
    @click.argument('username')
    @click.option('--role',type=click.Choice(ROLES),required=True)
    @click.password_option(confirmation_prompt=True)
    def create_user_command(username,role,password):
        item=Store(app.config['DATABASE'])
        try:add_user(item,username,password,role)
        except (ValueError,sqlite3.Error) as exc:raise click.ClickException(str(exc)) from exc
        finally:item.close()
        click.echo('User created; no default credentials were installed')

    @app.cli.command('disable-user')
    @click.argument('username')
    def disable_user_command(username):
        item=Store(app.config['DATABASE'])
        try:
            with item.db:
                updated=item.db.execute('UPDATE web_users SET active=0 WHERE username=?',(username,)).rowcount
                item.db.execute('DELETE FROM web_sessions WHERE username=?',(username,))
            if not updated:raise click.ClickException('Unknown user')
        finally:item.close()
        click.echo('User disabled and sessions revoked')

    return app

"""JWT access cookies backed by revocable, rotating refresh sessions."""
from __future__ import annotations
import hashlib, hmac, json, secrets, time, re, smtplib, os
from dataclasses import dataclass
from email.message import EmailMessage
from urllib.parse import parse_qsl
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from app.config import DATA_DIR, settings

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "career_session"
REFRESH = "career_refresh"
TTL = 15 * 60
_attempts = {}

def _signing_key():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / ".session_key"
    try:
        with path.open("xb") as out: out.write(secrets.token_bytes(32))
        path.chmod(0o600)
    except FileExistsError: pass
    return path.read_bytes()

def digest(value): return hashlib.sha256(value.encode()).hexdigest()

def password_hash(value):
    salt = secrets.token_hex(16)
    return salt + ":" + hashlib.scrypt(value.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()

def password_valid(value, stored):
    try:
        salt, hashed = stored.split(":")
        actual = hashlib.scrypt(value.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(actual, hashed)
    except (ValueError, TypeError): return False

@dataclass
class Principal:
    telegram_user_id: int
    is_admin: bool = False
    account_id: int | None = None
    session_id: str = ""

def _access(session):
    now = int(time.time())
    return jwt.encode({"sub":str(session.owner_id),"sid":session.id,"iss":"career-pilot","aud":"dashboard","iat":now,"exp":now+TTL},_signing_key(),algorithm="HS256")

def issue_session(user_id, *, admin=False, account_id=None):
    # Internal helper retained for tests and Telegram sign-in; never accepts user input directly.
    from app.database import SessionLocal, AuthSession
    with SessionLocal() as db:
        row=AuthSession(id=secrets.token_hex(24),owner_id=int(user_id),is_admin=admin,account_id=account_id,
                        refresh_hash=digest(secrets.token_urlsafe(48)),csrf=secrets.token_hex(24),expires=int(time.time())+43200)
        db.add(row);db.commit()
        return _access(row)

def _principal(row, db):
    from app.database import WebAccount, User
    if not row or row.revoked or row.expires <= time.time(): raise HTTPException(401,"Sign in required")
    if row.account_id:
        account=db.get(WebAccount,row.account_id)
        if not account or not account.is_active: raise HTTPException(401,"Sign in required")
        uid,admin=account.owner_id,account.is_admin
    else: uid,admin=row.owner_id,row.is_admin
    if not admin:
        owner=db.query(User).filter_by(telegram_user_id=uid).first()
        if not owner or not owner.is_active: raise HTTPException(401,"Sign in required")
    return Principal(uid,bool(admin),row.account_id,row.id)

def current_user(request:Request):
    from app.database import SessionLocal, AuthSession
    try:
        claims=jwt.decode(request.cookies.get(COOKIE,""),_signing_key(),algorithms=["HS256"],issuer="career-pilot",audience="dashboard",options={"require":["exp","iat","sub","sid"]})
        with SessionLocal() as db: return _principal(db.get(AuthSession,claims['sid']),db)
    except jwt.PyJWTError: raise HTTPException(401,"Sign in required")

def require_admin(user:Principal=Depends(current_user)):
    if not user.is_admin: raise HTTPException(403,"Administrator access required")
    return user

def rate_limit(request, group="login", limit=10):
    host=(request.client.host if request.client else "unknown")+group
    now=time.time()
    for key,(start,_) in list(_attempts.items()):
        if now-start>=300: _attempts.pop(key,None)
    start,count=_attempts.get(host,(now,0))
    if count>=limit or len(_attempts)>10000: raise HTTPException(429,"کمی بعد دوباره تلاش کنید.")
    _attempts[host]=(start,count+1)

def _set_cookies(response, request, row, refresh, remember):
    secure=request.url.scheme=="https"
    common=dict(secure=secure,samesite="strict",path="/")
    response.set_cookie(COOKIE,_access(row),httponly=True,max_age=(TTL if remember else None),**common)
    response.set_cookie(REFRESH,refresh,httponly=True,max_age=(30*86400 if remember else None),**common)
    response.set_cookie("career_csrf",row.csrf,httponly=False,max_age=(30*86400 if remember else None),**common)
    response.headers["Cache-Control"]="no-store"

def _start(response,request,uid,admin=False,account_id=None,remember=False):
    from app.database import SessionLocal, AuthSession
    refresh=secrets.token_urlsafe(48)
    with SessionLocal() as db:
        row=AuthSession(id=secrets.token_hex(24),owner_id=uid,is_admin=admin,account_id=account_id,refresh_hash=digest(refresh),csrf=secrets.token_hex(24),expires=int(time.time())+(30*86400 if remember else 43200))
        db.add(row);db.commit();_set_cookies(response,request,row,refresh,remember)
        return _profile(_principal(row,db),db)

def _profile(user,db):
    from app.database import WebAccount
    a=db.get(WebAccount,user.account_id) if user.account_id else None
    return {"is_admin":user.is_admin,"telegram_user_id":user.telegram_user_id,"account_id":user.account_id,"username":a.username if a else "","email":a.email if a else "","telegram_linked":user.telegram_user_id>0}

class LoginBody(BaseModel):
    username:str=Field(default="",max_length=254)
    password:str=Field(default="",max_length=256)
    init_data:str=Field(default="",max_length=10000)
    remember:bool=False

@router.post("/login")
def login(body:LoginBody,request:Request,response:Response):
    from app.database import SessionLocal, User, WebAccount
    rate_limit(request)
    if body.init_data:
        pairs=parse_qsl(body.init_data,keep_blank_values=True);fields=dict(pairs);signature=fields.pop('hash','')
        key=hmac.new(b'WebAppData',settings.telegram_review_bot_token.encode(),hashlib.sha256).digest()
        expected=hmac.new(key,'\n'.join(f'{k}={v}' for k,v in sorted(fields.items())).encode(),hashlib.sha256).hexdigest()
        try:
            if len(pairs)!=len(dict(pairs)) or not settings.telegram_review_bot_token or not hmac.compare_digest(signature,expected) or not 0<=time.time()-int(fields['auth_date'])<=300: raise ValueError()
            uid=int(json.loads(fields['user'])['id'])
        except (KeyError,ValueError,TypeError): raise HTTPException(401,'Invalid Telegram login')
        with SessionLocal() as db:
            owner=db.query(User).filter_by(telegram_user_id=uid).first()
            if not owner or not owner.is_active: raise HTTPException(403,'Start the Telegram bot first')
            account=db.query(WebAccount).filter_by(owner_id=uid).first()
            if account and not account.is_active: raise HTTPException(403,'Account disabled')
            return _start(response,request,uid,uid in settings.admin_telegram_ids,account.id if account else None,body.remember)
    with SessionLocal() as db:
        name=body.username.strip().lower()
        account=db.query(WebAccount).filter((WebAccount.username==name)|(WebAccount.email==name)).first() if name else None
        valid=password_valid(body.password,account.password_hash if account else '0'*32+':'+'0'*128)
        if account and account.is_active and valid:
            return _start(response,request,account.owner_id,account.is_admin,account.id,body.remember)
        # Existing operator can migrate without losing access. No new account inherits admin by name.
        if name in ('','admin') and not db.query(WebAccount).filter_by(is_admin=True).first() and settings.dashboard_admin_password and hmac.compare_digest(body.password,settings.dashboard_admin_password):
            return _start(response,request,0,True,remember=body.remember)
    raise HTTPException(401,'نام کاربری یا رمز عبور درست نیست.')

class RegisterBody(BaseModel):
    username:str=Field(min_length=3,max_length=40)
    email:str=Field(min_length=5,max_length=254)
    password:str=Field(min_length=12,max_length=256)

@router.post('/register')
def register(body:RegisterBody,request:Request,response:Response):
    from app.database import SessionLocal,WebAccount,User
    rate_limit(request,'register',5)
    username=body.username.strip().lower();email=body.email.strip().lower()
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,39}',username) or username=='admin': raise HTTPException(422,'نام کاربری باید ۳ تا ۴۰ حرف انگلیسی، عدد یا زیرخط باشد.')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): raise HTTPException(422,'ایمیل معتبر وارد کنید.')
    uid=-secrets.randbelow(2**50)-1;admin=False
    try: existing=current_user(request)
    except HTTPException: existing=None
    with SessionLocal() as db:
        if existing:
            if existing.account_id: raise HTTPException(409,'این حساب قبلاً نام کاربری دارد.')
            uid=existing.telegram_user_id;admin=existing.is_admin
        else: db.add(User(telegram_user_id=uid,chat_id=uid))
        account=WebAccount(username=username,email=email,password_hash=password_hash(body.password),owner_id=uid,is_admin=admin)
        db.add(account)
        try: db.commit()
        except IntegrityError:
            db.rollback();raise HTTPException(409,'این نام کاربری یا ایمیل قابل استفاده نیست.')
        return _start(response,request,uid,admin,account.id)

@router.get('/me')
def me(user:Principal=Depends(current_user)):
    from app.database import SessionLocal
    with SessionLocal() as db: return _profile(user,db)

@router.post('/refresh')
def refresh(request:Request,response:Response):
    from app.database import SessionLocal,AuthSession
    raw=request.cookies.get(REFRESH,'');hashed=digest(raw);new=secrets.token_urlsafe(48)
    with SessionLocal() as db:
        row=db.query(AuthSession).filter_by(refresh_hash=hashed).first();_principal(row,db)
        count=db.execute(update(AuthSession).where(AuthSession.id==row.id,AuthSession.refresh_hash==hashed,AuthSession.revoked==False).values(refresh_hash=digest(new))).rowcount
        if count!=1: raise HTTPException(401,'Refresh already used')
        db.commit();db.refresh(row);_set_cookies(response,request,row,new,row.expires-time.time()>43200)
        return _profile(_principal(row,db),db)

@router.post('/logout')
def logout(request:Request,response:Response):
    from app.database import SessionLocal,AuthSession
    with SessionLocal() as db:
        raw=request.cookies.get(REFRESH,'')
        row=db.query(AuthSession).filter_by(refresh_hash=digest(raw)).first() if raw else None
        if not row:
            try: row=db.get(AuthSession,current_user(request).session_id)
            except HTTPException: pass
        if row: row.revoked=True;db.commit()
    for name in (COOKIE,REFRESH,'career_csrf'): response.delete_cookie(name)
    return {'ok':True}

@router.post('/telegram-link')
def telegram_link(user:Principal=Depends(current_user)):
    from app.database import SessionLocal,AccountToken
    if not user.account_id: raise HTTPException(409,'ابتدا حساب وب بسازید.')
    if user.telegram_user_id>0: raise HTTPException(409,'تلگرام قبلاً متصل شده است.')
    raw=secrets.token_urlsafe(24)
    with SessionLocal() as db:
        db.add(AccountToken(token_hash=digest(raw),account_id=user.account_id,purpose='link',expires=int(time.time())+600));db.commit()
    return {'command':'/link '+raw,'expires_in':600}

def consume_link(raw,uid):
    from app.database import SessionLocal,AccountToken,WebAccount,User,BotApplication,DocumentArtifact
    with SessionLocal() as db:
        token=db.get(AccountToken,digest(raw));now=int(time.time())
        if not token or token.purpose!='link' or token.used or token.expires<now: raise ValueError('کد اتصال نامعتبر یا منقضی است.')
        account=db.get(WebAccount,token.account_id)
        owner=db.query(User).filter_by(telegram_user_id=uid).first()
        if not account or not account.is_active or not owner or not owner.is_active or account.owner_id>0: raise ValueError('حساب قابل اتصال نیست.')
        if db.query(WebAccount).filter_by(owner_id=uid).first(): raise ValueError('تلگرام به حساب دیگری متصل است.')
        # Web users cannot upload/generate before linking, so there is no second CV to overwrite.
        if db.query(BotApplication).filter_by(telegram_user_id=account.owner_id).first(): raise ValueError('انتقال نیازمند بررسی داده‌هاست.')
        consumed=db.execute(update(AccountToken).where(AccountToken.token_hash==token.token_hash,AccountToken.used==False).values(used=True)).rowcount
        if consumed!=1: raise ValueError('کد مصرف شده است.')
        account.owner_id=uid;account.is_admin=uid in settings.admin_telegram_ids
        try: db.commit()
        except IntegrityError: db.rollback();raise ValueError('تلگرام قبلاً متصل شده است.')

class ForgotBody(BaseModel):
    email:str=Field(max_length=254)

@router.post('/forgot-password')
def forgot(body:ForgotBody,request:Request):
    from app.database import SessionLocal,WebAccount,AccountToken
    rate_limit(request,'forgot',5)
    with SessionLocal() as db:
        account=db.query(WebAccount).filter_by(email=body.email.strip().lower()).first()
        if account and account.is_active:
            raw=secrets.token_urlsafe(32)
            db.add(AccountToken(token_hash=digest(raw),account_id=account.id,purpose='reset',expires=int(time.time())+1800));db.commit()
            try: send_reset(account.email,raw)
            except Exception:
                import logging
                logging.getLogger(__name__).warning('Password recovery delivery unavailable')
    return {'message':'اگر ایمیل ثبت شده باشد، راهنمای بازیابی برای شما ارسال می‌شود.'}

def send_reset(email,token):
    host=settings.auth_smtp_host;port=settings.auth_smtp_port
    sender=settings.auth_smtp_user;password=settings.auth_smtp_password
    if not sender or not password:
        from app.database import SessionLocal
        from app.linkedin.settings import load_linkedin_settings
        with SessionLocal() as db: cfg=load_linkedin_settings(db)
        sender,password=cfg.gmail_address,cfg.gmail_app_password
    if not sender or not password: raise RuntimeError('Recovery email is not configured')
    message=EmailMessage();message['From']=sender;message['To']=email;message['Subject']='Career Pilot — بازیابی رمز عبور'
    # A token, rather than an origin-derived URL, prevents Host-header reset poisoning.
    message.set_content('در صفحه بازیابی رمز Career Pilot این کد را وارد کنید. اعتبار: ۳۰ دقیقه.\n\n'+token)
    with smtplib.SMTP_SSL(host,port,timeout=20) as smtp: smtp.login(sender,password);smtp.send_message(message)

class ResetBody(BaseModel):
    token:str=Field(min_length=20,max_length=100)
    password:str=Field(min_length=12,max_length=256)

@router.post('/reset-password')
def reset(body:ResetBody,request:Request):
    from app.database import SessionLocal,AccountToken,WebAccount,AuthSession
    rate_limit(request,'reset')
    with SessionLocal() as db:
        token=db.get(AccountToken,digest(body.token))
        if not token or token.purpose!='reset' or token.used or token.expires<time.time(): raise HTTPException(400,'کد نامعتبر یا منقضی است.')
        count=db.execute(update(AccountToken).where(AccountToken.token_hash==token.token_hash,AccountToken.used==False).values(used=True)).rowcount
        if count!=1: raise HTTPException(400,'کد قبلاً مصرف شده است.')
        account=db.get(WebAccount,token.account_id)
        if not account or not account.is_active: raise HTTPException(400,'کد نامعتبر است.')
        account.password_hash=password_hash(body.password)
        db.execute(update(AuthSession).where(AuthSession.account_id==account.id).values(revoked=True));db.commit()
    return {'message':'رمز تغییر کرد. دوباره وارد شوید.'}

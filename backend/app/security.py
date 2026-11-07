import os
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy.orm import Session
from .database import get_db
from .models import User
SECRET = os.environ.get('JWT_SECRET', '')
if len(SECRET) < 32:
    raise RuntimeError('JWT_SECRET must contain at least 32 random characters')
hasher = PasswordHash.recommended()
DUMMY_HASH = hasher.hash('dummy-password-for-timing')
def token(user):
    return jwt.encode({'sub': str(user.id), 'v': user.token_version, 'exp': datetime.now(timezone.utc) + timedelta(hours=8)}, SECRET, algorithm='HS256')
def current_user(request: Request, db: Session = Depends(get_db)):
    role=request.headers.get('X-Laxora-Role') or (request.query_params.get('workspace_role') if request.method=='GET' else None)
    if role and role not in ('client','lawyer','admin'): raise HTTPException(403,'Invalid workspace role')
    raw = request.cookies.get('laxora_'+role+'_session') if role else None
    raw = raw or request.cookies.get('laxora_session')
    if not raw: raise HTTPException(401, 'Please sign in')
    try:
        payload = jwt.decode(raw, SECRET, algorithms=['HS256'], options={'require':['sub','exp','v']})
        user = db.get(User, int(payload['sub']))
        if not user or not user.active or user.deleted or user.token_version != payload['v']: raise ValueError()
        if role and user.role!=role: raise HTTPException(401,'Please sign in to this role workspace')
        expected=request.headers.get('X-Laxora-User')
        if expected and expected!=str(user.id): raise HTTPException(409,'Your account changed in another tab. Reload and sign in again before continuing.')
        return user
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(401, 'Session expired. Please sign in again')
def roles(*allowed):
    def check(user: User = Depends(current_user)):
        if user.role not in allowed: raise HTTPException(403, 'Permission denied')
        return user
    return check

import csv
import io
import os
import time
import uuid
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import select, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .models import User, Lawyer, Area, Credential, Slot, Appointment, Message, Notification, Activity, now
from .schemas import Register, Login, Profile, Password, LawyerProfile, SlotInput, Booking, BookingUpdate, MessageInput, Verification, AdminUser, ManualLawyer, AreaInput
from .security import current_user, roles, hasher, token, DUMMY_HASH

app = FastAPI(title='LAXORA API', version='1.0.0', description='Lawyer discovery, verification, consultation and appointment platform.')
from . import storage
from .storage import UPLOAD_DIR
ORIGINS = set(os.getenv('ALLOWED_ORIGINS', 'http://localhost:3000').split(','))
SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
START = time.monotonic()
METRICS = {'requests': 0, 'errors': 0, 'total_ms': 0.0}
ATTEMPTS = defaultdict(deque)

@app.middleware('http')
async def guard(request: Request, call_next):
    began = time.monotonic()
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and origin not in ORIGINS:
            return JSONResponse({'detail': 'Origin not allowed'}, status_code=403)
        if request.cookies.get('laxora_session') and request.headers.get('x-laxora-request') != '1':
            return JSONResponse({'detail': 'Missing request protection header'}, status_code=403)
    if request.url.path in ('/api/auth/login', '/api/auth/register', '/api/auth/admin-register') and request.method == 'POST':
        key = request.client.host if request.client else 'unknown'
        q = ATTEMPTS[key]
        while q and q[0] < time.monotonic()-60: q.popleft()
        if len(q) >= 20: return JSONResponse({'detail':'Too many attempts; try again in a minute'}, status_code=429)
        q.append(time.monotonic())
        if len(ATTEMPTS) > 10000:
            for k in list(ATTEMPTS):
                if not ATTEMPTS[k] or ATTEMPTS[k][-1] < time.monotonic()-60: ATTEMPTS.pop(k, None)
    response = await call_next(request)
    elapsed = (time.monotonic()-began)*1000
    METRICS['requests'] += 1
    METRICS['errors'] += int(response.status_code >= 500)
    METRICS['total_ms'] += elapsed
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Response-Time-Ms'] = str(round(elapsed, 1))
    return response

@app.exception_handler(IntegrityError)
async def integrity_error(_, exc):
    return JSONResponse({'detail': 'This record already exists, is still in use, or the slot was just booked. Refresh and try again.'}, status_code=409)

@app.exception_handler(Exception)
async def internal_error(_, exc):
    logging.exception('Unexpected request failure', exc_info=exc)
    return JSONResponse({'detail': 'An unexpected error occurred. Please try again.'}, status_code=500)

def commit(db): db.commit()
def required(db, model, id):
    item = db.get(model, id)
    if item is None: raise HTTPException(404, 'Record not found')
    return item

def public_user(u): return {'id':u.id, 'name':u.name, 'email':u.email, 'role':u.role, 'photo_url':f'/api/users/{u.id}/photo?v={u.avatar}' if u.avatar else '', 'phone':u.phone, 'city':u.city, 'address':u.address, 'bio':u.bio, 'active':u.active, 'created_at':u.created_at}
def log(db, actor, action): db.add(Activity(actor_id=actor.id if actor else None, action=action))
def notify(db, uid, message): db.add(Notification(user_id=uid, text=message))
def own_lawyer(db, user):
    l = db.scalar(select(Lawyer).where(Lawyer.user_id == user.id))
    if not l: raise HTTPException(404, 'Lawyer profile not found')
    return l

def lawyer_json(db, l):
    u = db.get(User, l.user_id)
    a = db.get(Area, l.area_id) if l.area_id else None
    return {'id':l.id, 'user_id':l.user_id, 'name':u.name, 'area_id':l.area_id, 'practice_area':a.name if a else 'General practice', 'biography':l.biography, 'education':l.education, 'experience':l.experience, 'jurisdiction':l.jurisdiction, 'location':l.location, 'photo':f'/api/users/{u.id}/photo?v={u.avatar}' if u.avatar else l.photo, 'verification':l.verification, 'verification_note':l.verification_note}

def aware(dt): return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
def validate_time(dt):
    if dt.tzinfo is None: raise HTTPException(422, 'Date must include timezone')
    dt = aware(dt)
    if dt <= now() or dt > now()+timedelta(days=365): raise HTTPException(422, 'Choose a future date within one year')
    if dt.minute not in (0,30) or dt.second or dt.microsecond: raise HTTPException(422, 'Use a 30-minute slot (00 or 30 minutes)')
    return dt

def appointment_access(db, user, id):
    a = required(db, Appointment, id)
    l = db.get(Lawyer, a.lawyer_id)
    if user.role != 'admin' and user.id not in (a.client_id, l.user_id): raise HTTPException(403, 'Permission denied')
    return a, l

def appointment_json(db,a):
    l=db.get(Lawyer,a.lawyer_id)
    s=db.get(Slot,a.slot_id)
    return {'id':a.id,'client_id':a.client_id,'client_name':db.get(User,a.client_id).name,'lawyer_id':a.lawyer_id,'lawyer_name':db.get(User,l.user_id).name,'slot_id':a.slot_id,'starts_at':aware(s.starts_at),'issue':a.issue,'contact':a.contact,'status':a.status,'created_at':a.created_at}

def create_user(db, data, role=None):
    u=User(name=data.name,email=str(data.email).lower(),password_hash=hasher.hash(data.password),role=role or data.role,phone=getattr(data,'phone',''),city=getattr(data,'city',''),address=getattr(data,'address',''))
    db.add(u); db.flush()
    if u.role=='lawyer': db.add(Lawyer(user_id=u.id))
    log(db,u,'Account created')
    for admin in db.scalars(select(User).where(User.role=='admin',User.active==True,User.deleted==False)):
        notify(db,admin.id,f'New {u.role} registered: {u.name}')
    return u

@app.get('/api/health')
def health(db: Session=Depends(get_db)):
    db.execute(text('SELECT 1'))
    return {'status':'ok','database':'connected'}
@app.post('/api/auth/register', status_code=201)
def register(data:Register,db:Session=Depends(get_db)):
    u=create_user(db,data); commit(db); return public_user(u)
@app.post('/api/auth/login')
def login(data:Login,response:Response,db:Session=Depends(get_db)):
    u=db.scalar(select(User).where(User.email==str(data.email).lower()))
    valid=hasher.verify(data.password,u.password_hash if u else DUMMY_HASH)
    if not u or not valid or not u.active or u.deleted: raise HTTPException(401,'Invalid email or password')
    if data.role and u.role != data.role: raise HTTPException(403, f'Use the {u.role} login page for this account')
    response.set_cookie('laxora_session',token(u),httponly=True,secure=SECURE,samesite='lax',max_age=28800,path='/')
    response.set_cookie('laxora_'+u.role+'_session',token(u),httponly=True,secure=SECURE,samesite='lax',max_age=28800,path='/')
    log(db,u,'Signed in'); commit(db); return public_user(u)
@app.post('/api/auth/logout')
def logout(response:Response,user:User=Depends(current_user),db:Session=Depends(get_db)):
    user.token_version+=1; commit(db)
    response.delete_cookie('laxora_'+user.role+'_session',path='/')
    response.delete_cookie('laxora_session',path='/'); return {'ok':True}
@app.get('/api/auth/me')
def me(user:User=Depends(current_user)): return public_user(user)
@app.put('/api/auth/me')
def profile(data:Profile,user:User=Depends(current_user),db:Session=Depends(get_db)):
    changed=any(getattr(user,k)!=v for k,v in data.model_dump().items())
    for k,v in data.model_dump().items(): setattr(user,k,v)
    if changed and user.role!='admin':
        from .verification import invalidate
        invalidate(db,user)
    commit(db); return public_user(user)
@app.put('/api/auth/password')
def password(data:Password,response:Response,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if not hasher.verify(data.current_password,user.password_hash): raise HTTPException(400,'Current password is incorrect')
    user.password_hash=hasher.hash(data.new_password); user.token_version+=1
    log(db,user,'Password changed'); commit(db)
    response.set_cookie('laxora_session',token(user),httponly=True,secure=SECURE,samesite='lax',max_age=28800,path='/')
    response.set_cookie('laxora_'+user.role+'_session',token(user),httponly=True,secure=SECURE,samesite='lax',max_age=28800,path='/')
    return {'ok':True}
@app.get('/api/areas')
def areas(db:Session=Depends(get_db)): return [{'id':a.id,'name':a.name} for a in db.scalars(select(Area).order_by(Area.name))]
@app.get('/api/lawyers')
def lawyers(q:str='',area_id:int|None=None,location:str='',jurisdiction:str='',experience:int=0,page:int=1,db:Session=Depends(get_db)):
    stmt=select(Lawyer).join(User).where(User.active==True,User.deleted==False)
    if q: stmt=stmt.where(User.name.ilike('%'+q[:120]+'%'))
    if area_id: stmt=stmt.where(Lawyer.area_id==area_id)
    if location: stmt=stmt.where(Lawyer.location.ilike('%'+location[:120]+'%'))
    if jurisdiction: stmt=stmt.where(Lawyer.jurisdiction.ilike('%'+jurisdiction[:120]+'%'))
    stmt=stmt.where(Lawyer.experience>=max(0,experience))
    total=db.scalar(select(func.count()).select_from(stmt.subquery()))
    return {'items':[lawyer_json(db,l) for l in db.scalars(stmt.order_by(Lawyer.id).offset((max(1,page)-1)*12).limit(12))], 'total':total,'page':max(1,page)}
@app.get('/api/lawyers/me/profile')
def own_profile(user:User=Depends(roles('lawyer')),db:Session=Depends(get_db)): return lawyer_json(db,own_lawyer(db,user))
@app.put('/api/lawyers/me/profile')
def update_lawyer(data:LawyerProfile,user:User=Depends(roles('lawyer')),db:Session=Depends(get_db)):
    l=own_lawyer(db,user)
    if data.area_id: required(db,Area,data.area_id)
    changed=any(getattr(l,k)!=v for k,v in data.model_dump().items() if k!='photo')
    for k,v in data.model_dump().items(): setattr(l,k,v)
    if changed:
        l.verification='pending'; l.verification_note='Profile updated; review required.'
        from .verification import invalidate
        invalidate(db,user)
    log(db,user,'Professional profile updated'); commit(db); return lawyer_json(db,l)
@app.get('/api/lawyers/{id}')
def lawyer(id:int,db:Session=Depends(get_db)):
    l=required(db,Lawyer,id); u=db.get(User,l.user_id)
    if not u.active or u.deleted: raise HTTPException(404,'Lawyer unavailable')
    return lawyer_json(db,l)
@app.get('/api/lawyers/{id}/slots')
def slots(id:int,db:Session=Depends(get_db)):
    required(db,Lawyer,id)
    used=select(Appointment.slot_id).where(Appointment.status.in_(['pending','approved']))
    return [{'id':s.id,'starts_at':aware(s.starts_at)} for s in db.scalars(select(Slot).where(Slot.lawyer_id==id,Slot.starts_at>now(),~Slot.id.in_(used)).order_by(Slot.starts_at).limit(500))]
@app.post('/api/lawyers/me/slots',status_code=201)
def create_slot(data:SlotInput,user:User=Depends(roles('lawyer')),db:Session=Depends(get_db)):
    l=own_lawyer(db,user); s=Slot(lawyer_id=l.id,starts_at=validate_time(data.starts_at)); db.add(s); commit(db)
    return {'id':s.id,'starts_at':s.starts_at}
@app.delete('/api/lawyers/me/slots/{id}')
def delete_slot(id:int,user:User=Depends(roles('lawyer')),db:Session=Depends(get_db)):
    s=required(db,Slot,id)
    if s.lawyer_id!=own_lawyer(db,user).id: raise HTTPException(403,'Permission denied')
    if db.scalar(select(Appointment.id).where(Appointment.slot_id==id)): raise HTTPException(409,'A slot with appointment history cannot be removed')
    db.delete(s); commit(db); return {'ok':True}
@app.post('/api/lawyers/me/credentials',status_code=201)
async def upload(kind:str=Form(...),file:UploadFile=File(...),user:User=Depends(roles('lawyer')),db:Session=Depends(get_db)):
    if kind not in ('bar_license','certificate','identity'): raise HTTPException(422,'Invalid document type')
    l=own_lawyer(db,user)
    from .verification import documents
    if len(documents(db,user))>=20: raise HTTPException(422,'Maximum 20 documents; remove an old document first')
    content=await file.read(10*1024*1024+1)
    if len(content)>10*1024*1024: raise HTTPException(413,'Maximum document size is 10 MB')
    mime='application/pdf' if content.startswith(b'%PDF-') else 'image/png' if content.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if content.startswith(b'\xff\xd8\xff') else None
    if not mime: raise HTTPException(422,'Upload a PDF, PNG or JPEG file')
    name=uuid.uuid4().hex; storage.write(name,content,mime)
    try:
        c=Credential(lawyer_id=l.id,kind=kind,filename=Path(file.filename or 'document').name[:200],stored_name=name,mime=mime)
        from .verification import invalidate
        invalidate(db,user)
        db.add(c); l.verification='pending'; l.verification_note='Documents submitted for review'
        for admin in db.scalars(select(User).where(User.role=='admin',User.active==True)): notify(db,admin.id,f'{user.name} submitted verification documents')
        log(db,user,'Credential uploaded'); commit(db)
    except Exception:
        storage.cleanup(name); raise
    return {'id':c.id}
@app.get('/api/lawyers/{id}/credentials')
def credentials(id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    l=required(db,Lawyer,id)
    if user.role!='admin' and user.id!=l.user_id: raise HTTPException(403,'Permission denied')
    return [{'id':c.id,'kind':c.kind,'filename':c.filename,'created_at':c.created_at} for c in db.scalars(select(Credential).where(Credential.lawyer_id==id))]
@app.get('/api/credentials/{id}/download')
def download(id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    c=required(db,Credential,id); l=db.get(Lawyer,c.lawyer_id)
    if user.role!='admin' and user.id!=l.user_id: raise HTTPException(403,'Permission denied')
    return storage.download(c.stored_name,c.mime,c.filename)
@app.delete('/api/credentials/{id}')
def delete_credential(id:int,user:User=Depends(roles('lawyer')),db:Session=Depends(get_db)):
    c=required(db,Credential,id); l=own_lawyer(db,user)
    if c.lawyer_id!=l.id: raise HTTPException(403,'Permission denied')
    from .verification import invalidate
    invalidate(db,user)
    name=c.stored_name; db.delete(c); l.verification='pending'; commit(db); storage.cleanup(name); return {'ok':True}
@app.post('/api/appointments',status_code=201)
def book(data:Booking,user:User=Depends(roles('client')),db:Session=Depends(get_db)):
    l=required(db,Lawyer,data.lawyer_id); lu=db.get(User,l.user_id)
    if l.verification!='verified' or not lu.active or lu.deleted: raise HTTPException(400,'Only active, verified lawyers can receive bookings')
    s=required(db,Slot,data.slot_id)
    if s.lawyer_id!=l.id or aware(s.starts_at)<=now(): raise HTTPException(400,'Choose an available future slot')
    a=Appointment(client_id=user.id,**data.model_dump()); db.add(a); db.flush()
    notify(db,l.user_id,f'New consultation request from {user.name} (#{a.id})'); log(db,user,f'Consultation #{a.id} requested'); commit(db)
    return appointment_json(db,a)
@app.get('/api/appointments')
def appointments(user:User=Depends(current_user),db:Session=Depends(get_db)):
    stmt=select(Appointment)
    if user.role=='client': stmt=stmt.where(Appointment.client_id==user.id)
    if user.role=='lawyer': stmt=stmt.where(Appointment.lawyer_id==own_lawyer(db,user).id)
    return [appointment_json(db,a) for a in db.scalars(stmt.order_by(Appointment.created_at.desc()))]
@app.patch('/api/appointments/{id}')
def update_appointment(id:int,data:BookingUpdate,user:User=Depends(current_user),db:Session=Depends(get_db)):
    # Row lock serializes competing state transitions on PostgreSQL.
    db.scalar(select(Appointment).where(Appointment.id==id).with_for_update())
    a,l=appointment_access(db,user,id)
    if a.status not in ('pending','approved'): raise HTTPException(409,'This appointment is closed')
    if user.role=='client' and (data.status!='cancelled' or data.slot_id is not None): raise HTTPException(403,'Clients may only cancel appointments')
    if not data.status and data.slot_id is None: raise HTTPException(422,'No update provided')
    if data.slot_id is not None:
        if data.status is not None: raise HTTPException(422,'Reschedule separately from a status update')
        s=required(db,Slot,data.slot_id)
        if s.lawyer_id!=l.id or aware(s.starts_at)<=now(): raise HTTPException(400,'Invalid future slot')
        a.slot_id=s.id; a.status='approved'
    if data.status:
        allowed={'pending':{'approved','rejected','cancelled'},'approved':{'completed','cancelled'}}
        if data.status not in allowed[a.status]: raise HTTPException(409,'Invalid appointment transition')
        if data.status=='completed' and aware(db.get(Slot,a.slot_id).starts_at)>now(): raise HTTPException(400,'A future appointment cannot be completed')
        a.status=data.status
    for uid in (a.client_id,l.user_id): notify(db,uid,f'Appointment #{a.id}: '+('rescheduled' if data.slot_id is not None else a.status))
    log(db,user,f'Appointment #{a.id} updated: {a.status}'); commit(db); return appointment_json(db,a)
@app.get('/api/appointments/{id}/messages')
def messages(id:int,user:User=Depends(roles('client','lawyer')),db:Session=Depends(get_db)):
    appointment_access(db,user,id)
    return [{'id':m.id,'sender_id':m.sender_id,'sender_name':db.get(User,m.sender_id).name,'body':m.body,'created_at':m.created_at} for m in db.scalars(select(Message).where(Message.appointment_id==id).order_by(Message.id))]
@app.post('/api/appointments/{id}/messages',status_code=201)
def message(id:int,data:MessageInput,user:User=Depends(roles('client','lawyer')),db:Session=Depends(get_db)):
    a,l=appointment_access(db,user,id)
    if a.status not in ('pending','approved'): raise HTTPException(409,'This conversation is closed')
    m=Message(appointment_id=id,sender_id=user.id,body=data.body); db.add(m)
    notify(db,l.user_id if user.id==a.client_id else a.client_id,f'New message about appointment #{id}'); commit(db); return {'id':m.id}
@app.get('/api/notifications')
def notifications(user:User=Depends(current_user),db:Session=Depends(get_db)):
    return [{'id':n.id,'text':n.text,'read':n.read,'created_at':n.created_at} for n in db.scalars(select(Notification).where(Notification.user_id==user.id).order_by(Notification.id.desc()).limit(100))]
@app.post('/api/notifications/read')
def read_notifications(user:User=Depends(current_user),db:Session=Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.user_id==user.id,Notification.read==False)): n.read=True
    commit(db); return {'ok':True}
@app.get('/api/admin/users')
def users(user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    return [public_user(u) for u in db.scalars(select(User).where(User.deleted==False).order_by(User.id))]
@app.patch('/api/admin/users/{id}')
def update_user(id:int,data:AdminUser,user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    u=required(db,User,id)
    if u.role=='admin' and data.active is False: raise HTTPException(400,'Admin accounts cannot be blocked here')
    changes=data.model_dump(exclude_none=True)
    if u.role!='admin' and any(k!='active' and getattr(u,k)!=v for k,v in changes.items()):
        from .verification import invalidate
        invalidate(db,u)
    for k,v in changes.items(): setattr(u,k,v)
    if data.active is False: u.token_version+=1
    log(db,user,f'User #{id} updated'); commit(db); return public_user(u)
@app.delete('/api/admin/users/{id}')
def remove_user(id:int,user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    u=required(db,User,id)
    if u.role=='admin': raise HTTPException(400,'Admin accounts cannot be removed here')
    u.deleted=True;u.active=False;u.token_version+=1
    log(db,user,f'User #{id} soft-deleted');commit(db);return {'ok':True}
@app.post('/api/admin/lawyers',status_code=201)
def manual_lawyer(data:ManualLawyer,user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    if data.professional.area_id: required(db,Area,data.professional.area_id)
    u=create_user(db,data,'lawyer'); db.flush(); l=own_lawyer(db,u)
    for k,v in data.professional.model_dump().items(): setattr(l,k,v)
    log(db,user,f'Lawyer account #{u.id} created manually');commit(db);return lawyer_json(db,l)
@app.get('/api/admin/lawyers')
def admin_lawyers(user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    return [lawyer_json(db,l) for l in db.scalars(select(Lawyer).join(User).where(User.deleted==False).order_by(Lawyer.id))]
@app.patch('/api/admin/lawyers/{id}/verification')
def verify(id:int,data:Verification,user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    l=required(db,Lawyer,id)
    raise HTTPException(409,'Use the complete application review in Admin → Verification. A submitted application and current version are required.')

@app.post('/api/admin/areas',status_code=201)
def add_area(data:AreaInput,user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    a=Area(name=data.name);db.add(a);log(db,user,'Practice area added');commit(db);return {'id':a.id,'name':a.name}
@app.put('/api/admin/areas/{id}')
def edit_area(id:int,data:AreaInput,user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    a=required(db,Area,id);a.name=data.name;commit(db);return {'id':a.id,'name':a.name}
@app.delete('/api/admin/areas/{id}')
def delete_area(id:int,user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    a=required(db,Area,id)
    if db.scalar(select(Lawyer.id).where(Lawyer.area_id==id)): raise HTTPException(409,'Reassign lawyers before deleting this practice area')
    db.delete(a);commit(db);return {'ok':True}

def report_data(db):
    count=lambda model,*filters:db.scalar(select(func.count()).select_from(model).where(*filters))
    return {'total_users':count(User,User.deleted==False),'total_lawyers':count(Lawyer,Lawyer.user_id.in_(select(User.id).where(User.deleted==False))),'verified_lawyers':count(Lawyer,Lawyer.verification=='verified',Lawyer.user_id.in_(select(User.id).where(User.active==True,User.deleted==False))),'appointments':count(Appointment),'pending_appointments':count(Appointment,Appointment.status=='pending'),'activities':count(Activity)}
@app.get('/api/admin/reports')
def reports(user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    return {'summary':report_data(db),'statuses':dict(db.execute(select(Appointment.status,func.count()).group_by(Appointment.status)).all()),'activities':[{'id':a.id,'action':a.action,'actor_id':a.actor_id,'created_at':a.created_at} for a in db.scalars(select(Activity).order_by(Activity.id.desc()).limit(100))], 'monitoring':{'uptime_seconds':round(time.monotonic()-START),'requests':METRICS['requests'],'server_errors':METRICS['errors'],'average_response_ms':round(METRICS['total_ms']/max(1,METRICS['requests']),2),'scope':'Current API process; resets on restart'}}
@app.get('/api/admin/reports.csv')
def reports_csv(user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    buf=io.StringIO();w=csv.writer(buf);w.writerow(['Metric','Value']);w.writerows(report_data(db).items())
    w.writerow([]);w.writerow(['Appointment ID','Client ID','Lawyer ID','Status','Date UTC'])
    for a in db.scalars(select(Appointment).order_by(Appointment.id)): w.writerow([a.id,a.client_id,a.lawyer_id,a.status,aware(db.get(Slot,a.slot_id).starts_at).isoformat()])
    w.writerow([]);w.writerow(['Activity ID','Actor ID','Action','Date UTC'])
    for a in db.scalars(select(Activity).order_by(Activity.id)):
        action=a.action
        if action.startswith(('=','+','-','@')): action="'"+action
        w.writerow([a.id,a.actor_id,action,a.created_at.isoformat()])
    return StreamingResponse(iter([buf.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=laxora-report.csv'})

# V2 routes use the same role guards and database transaction conventions.
from .features import router as features_router
app.include_router(features_router)

from .verification import router as verification_router
app.include_router(verification_router)

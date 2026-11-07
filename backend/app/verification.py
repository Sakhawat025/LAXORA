"""Photo uploads and explicit identity/professional verification submissions."""
import io
import uuid
import warnings
from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from PIL import Image, ImageOps, UnidentifiedImageError
from .database import get_db
from .models import User, Lawyer, Credential, VerificationApplication as Application, VerificationDocument as Document, now
from .security import current_user, roles
from .schemas import Input
from . import storage
from .main import required, notify, log, public_user, lawyer_json
router=APIRouter()
Image.MAX_IMAGE_PIXELS=20_000_000
class Details(Input):
    legal_name:str=Field(default='',max_length=120)
    identity_type:Literal['national_id','passport']='national_id'
    country:str=Field(default='',max_length=100)
    bar_council:str=Field(default='',max_length=150)
    enrollment_number:str=Field(default='',max_length=100)
    enrollment_date:date|None=None
    bar_association:str=Field(default='',max_length=150)
    practicing_courts:str=Field(default='',max_length=500)
    chamber_name:str=Field(default='',max_length=200)
    chamber_address:str=Field(default='',max_length=500)
    chamber_phone:str=Field(default='',max_length=40)
    degree:str=Field(default='',max_length=150)
    university:str=Field(default='',max_length=200)
    graduation_year:int|None=Field(default=None,ge=1950,le=2100)
    higher_court_practice:bool=False
    declaration:bool=False
    consent:bool=False
class Decision(Input):
    status:Literal['verified','rejected']
    note:str=Field(min_length=3,max_length=2000)
    version:int

def get_application(db,user):
    a=db.scalar(select(Application).where(Application.user_id==user.id).with_for_update().execution_options(populate_existing=True))
    if not a:a=Application(user_id=user.id,details={});db.add(a);db.flush()
    return a

def invalidate(db,user):
    a=db.scalar(select(Application).where(Application.user_id==user.id).with_for_update().execution_options(populate_existing=True))
    if a:
        a.status='draft';a.version+=1;a.reviewed_by=None;a.reviewed_at=None;a.note='Information changed. Review and submit your application again.'
    l=db.scalar(select(Lawyer).where(Lawyer.user_id==user.id))
    if l:l.verification='pending';l.verification_note='Information changed; a new verification submission is required.'

def documents(db,user):
    items=[{'id':d.id,'kind':d.kind,'filename':d.filename,'url':f'/api/verification/documents/{d.id}/download','legacy':False} for d in db.scalars(select(Document).where(Document.user_id==user.id))]
    l=db.scalar(select(Lawyer).where(Lawyer.user_id==user.id))
    if l:
        items += [{'id':d.id,'kind':d.kind,'filename':d.filename,'url':f'/api/credentials/{d.id}/download','legacy':True} for d in db.scalars(select(Credential).where(Credential.lawyer_id==l.id))]
    return items

def missing_requirements(db,user,details):
    missing=[]
    for key,label in [('legal_name','Legal name'),('country','Country')]:
        if not details.get(key):missing.append(label)
    for key,label in [('phone','Contact phone'),('city','City'),('address','Address'),('avatar','Profile photo')]:
        if not getattr(user,key):missing.append(label)
    if not details.get('declaration'):missing.append('Accuracy declaration')
    if not details.get('consent'):missing.append('Document review consent')
    kinds={x['kind'] for x in documents(db,user)}
    required_docs={'identity':'Identity document'}
    if user.role=='lawyer':
        required_docs.update({'bar_license':'Bar enrollment/license document','certificate':'Law degree certificate'})
        for key,label in [('bar_council','Bar council / licensing body'),('enrollment_number','Enrollment number'),('enrollment_date','Enrollment date'),('bar_association','Bar association'),('practicing_courts','Practicing courts'),('chamber_name','Chamber name'),('chamber_address','Chamber address'),('chamber_phone','Chamber contact'),('degree','Law degree'),('university','University'),('graduation_year','Graduation year')]:
            if not details.get(key):missing.append(label)
        l=db.scalar(select(Lawyer).where(Lawyer.user_id==user.id))
        if not l or not all([l.area_id,l.biography,l.education,l.location,l.jurisdiction]):missing.append('Complete professional profile (practice area, biography, education, location, jurisdiction)')
        if details.get('higher_court_practice'):required_docs['court_permission']='Higher-court permission document'
    for kind,label in required_docs.items():
        if kind not in kinds:missing.append(label)
    if details.get('enrollment_date') and date.fromisoformat(details['enrollment_date'])>date.today():missing.append('Enrollment date cannot be in the future')
    if details.get('graduation_year') and details['graduation_year']>date.today().year:missing.append('Graduation year cannot be in the future')
    return missing

def serialize(db,user,a):
    l=db.scalar(select(Lawyer).where(Lawyer.user_id==user.id))
    return {'id':a.id if a else None,'user':public_user(user),'professional':lawyer_json(db,l) if l else None,'status':a.status if a else 'not_submitted','details':a.details if a else {},'note':a.note if a else '', 'submitted_at':a.submitted_at if a else None,'reviewed_at':a.reviewed_at if a else None,'version':a.version if a else 0,'documents':documents(db,user),'missing':missing_requirements(db,user,a.details if a else {})}

@router.post('/api/auth/photo')
async def photo(file:UploadFile=File(...),user:User=Depends(current_user),db:Session=Depends(get_db)):
    raw=await file.read(5*1024*1024+1)
    if len(raw)>5*1024*1024:raise HTTPException(413,'Choose an image smaller than 5 MB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as img:
                if img.format not in ('JPEG','PNG','WEBP'):raise ValueError()
                img.load();img=ImageOps.exif_transpose(img).convert('RGB');img.thumbnail((900,900))
                out=io.BytesIO();img.save(out,format='JPEG',quality=88)
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):raise HTTPException(422,'Upload a valid JPG, PNG or WebP image (up to 20 megapixels)')
    name=uuid.uuid4().hex+'.jpg';storage.write(name,out.getvalue(),'image/jpeg');old=user.avatar
    try:
        user.avatar=name
        if user.role!='admin':invalidate(db,user)
        db.commit()
    except Exception:storage.cleanup(name);raise
    if old:storage.cleanup(old)
    return public_user(user)

@router.delete('/api/auth/photo')
def remove_photo(user:User=Depends(current_user),db:Session=Depends(get_db)):
    old=user.avatar;user.avatar=''
    if user.role!='admin':invalidate(db,user)
    db.commit()
    if old:storage.cleanup(old)
    return public_user(user)

@router.get('/api/users/{id}/photo')
def get_photo(id:int,request:Request,db:Session=Depends(get_db)):
    u=required(db,User,id)
    if u.role!='lawyer' or not u.active or u.deleted:
        allowed=False
        for role in (u.role,'admin',None):
            scope=dict(request.scope);scope['headers']=[(k,v) for k,v in request.scope['headers'] if k.lower() not in (b'x-laxora-role',b'x-laxora-user')]
            if role:scope['headers'].append((b'x-laxora-role',role.encode()))
            try:
                viewer=current_user(Request(scope),db)
                if viewer.id==id or viewer.role=='admin':allowed=True;break
            except HTTPException:pass
        if not allowed:
            current_user(request,db)
            raise HTTPException(403,'Private profile photo')
    if not u.avatar:raise HTTPException(404,'No profile photo')
    return storage.download(u.avatar,'image/jpeg')

@router.get('/api/verification/me')
def my_application(user:User=Depends(roles('client','lawyer')),db:Session=Depends(get_db)):
    a=db.scalar(select(Application).where(Application.user_id==user.id).with_for_update().execution_options(populate_existing=True))
    return serialize(db,user,a)

@router.put('/api/verification/me')
def save_application(data:Details,user:User=Depends(roles('client','lawyer')),db:Session=Depends(get_db)):
    a=get_application(db,user);invalidate(db,user);a.details=data.model_dump(mode='json');db.commit()
    return serialize(db,user,a)

@router.post('/api/verification/submit')
def submit_application(user:User=Depends(roles('client','lawyer')),db:Session=Depends(get_db)):
    a=get_application(db,user)
    if a.status=='pending':raise HTTPException(409,'Your application is already awaiting review')
    if a.status=='verified':raise HTTPException(409,'Your application is already verified')
    missing=missing_requirements(db,user,a.details)
    if missing:raise HTTPException(422,'Please complete: '+', '.join(missing))
    a.status='pending';a.submitted_at=now();a.note='';a.version+=1
    l=db.scalar(select(Lawyer).where(Lawyer.user_id==user.id))
    if l:l.verification='pending';l.verification_note='Application submitted for review'
    for admin in db.scalars(select(User).where(User.role=='admin',User.active==True,User.deleted==False)):
        notify(db,admin.id,f'{user.name} submitted {user.role} verification')
    log(db,user,'Verification application submitted');db.commit();return serialize(db,user,a)

@router.post('/api/verification/documents',status_code=201)
async def upload_document(kind:str=Form(...),file:UploadFile=File(...),user:User=Depends(roles('client','lawyer')),db:Session=Depends(get_db)):
    allowed={'identity'} if user.role=='client' else {'identity','bar_license','certificate','court_permission','association_certificate'}
    if kind not in allowed:raise HTTPException(422,'Invalid document type')
    if len(documents(db,user))>=20:raise HTTPException(422,'Remove an old document before adding another (maximum 20)')
    content=await file.read(10*1024*1024+1)
    if len(content)>10*1024*1024:raise HTTPException(413,'Maximum document size is 10 MB')
    mime='application/pdf' if content.startswith(b'%PDF-') else 'image/png' if content.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if content.startswith(b'\xff\xd8\xff') else None
    if not mime:raise HTTPException(422,'Upload a PDF, PNG or JPEG')
    filename=uuid.uuid4().hex;storage.write(filename,content,mime)
    try:
        get_application(db,user);invalidate(db,user)
        db.add(Document(user_id=user.id,kind=kind,filename=(file.filename or 'document').replace('\\','/').split('/')[-1][:200],stored_name=filename,mime=mime));db.commit()
    except Exception:storage.cleanup(filename);raise
    return {'ok':True}

@router.get('/api/verification/documents/{id}/download')
def document_download(id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    d=required(db,Document,id)
    if d.user_id!=user.id and user.role!='admin':raise HTTPException(403,'Private document')
    return storage.download(d.stored_name,d.mime,d.filename)

@router.delete('/api/verification/documents/{id}')
def delete_document(id:int,user:User=Depends(roles('client','lawyer')),db:Session=Depends(get_db)):
    d=required(db,Document,id)
    if d.user_id!=user.id:raise HTTPException(403,'Permission denied')
    name=d.stored_name;db.delete(d);invalidate(db,user);db.commit();storage.cleanup(name);return {'ok':True}

@router.get('/api/admin/verifications')
def applications(user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    rows=db.scalars(select(Application).join(User,Application.user_id==User.id).where(User.deleted==False).order_by(Application.id.desc()))
    return [serialize(db,db.get(User,a.user_id),a) for a in rows]

@router.patch('/api/admin/verifications/{id}')
def review_application(id:int,data:Decision,user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    a=db.scalar(select(Application).where(Application.id==id).with_for_update())
    if not a:raise HTTPException(404,'Application not found')
    owner=required(db,User,a.user_id)
    if not owner.active or owner.deleted:raise HTTPException(409,'This account is not active')
    if a.status!='pending' or a.version!=data.version:raise HTTPException(409,'Application changed or was already reviewed. Refresh before deciding.')
    missing=missing_requirements(db,owner,a.details)
    if data.status=='verified' and missing:raise HTTPException(422,'Missing: '+', '.join(missing))
    a.status=data.status;a.note=data.note;a.reviewed_by=user.id;a.reviewed_at=now();a.version+=1
    l=db.scalar(select(Lawyer).where(Lawyer.user_id==owner.id))
    if l:l.verification=data.status;l.verification_note=data.note
    notify(db,owner.id,f'Your verification is {data.status}: {data.note}');log(db,user,f'Verification for user #{owner.id}: {data.status}');db.commit()
    return serialize(db,owner,a)

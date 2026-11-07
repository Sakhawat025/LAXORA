"""Role onboarding, administrative detail views and direct client/lawyer messaging."""
import hashlib
import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update, or_, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from .database import get_db
from .models import User, Lawyer, Credential, Appointment, Activity, AdminInvite, Conversation, DirectMessage, now
from .schemas import AdminRegister, InviteInput, ConversationInput, MessageInput
from .security import roles, current_user
from .main import public_user, required, lawyer_json, appointment_json, create_user, notify, log, aware
router = APIRouter()

def new_invite(db, email, actor_id=None):
    code=secrets.token_urlsafe(32)
    expires=now()+timedelta(hours=48)
    db.add(AdminInvite(email=email.lower(),token_hash=hashlib.sha256(code.encode()).hexdigest(),expires_at=expires,created_by=actor_id))
    return {'email':email.lower(),'invite_code':code,'expires_at':expires}

@router.post('/api/admin/invites',status_code=201)
def invite(data:InviteInput,user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    if db.scalar(select(User.id).where(User.email==str(data.email).lower())): raise HTTPException(409,'Email already registered')
    result=new_invite(db,str(data.email),user.id);log(db,user,'Admin invitation created');db.commit();return result

@router.post('/api/auth/admin-register',status_code=201)
def admin_register(data:AdminRegister,db:Session=Depends(get_db)):
    # Atomic one-use redemption, including when two requests arrive concurrently.
    result=db.execute(update(AdminInvite).where(AdminInvite.email==str(data.email).lower(),AdminInvite.token_hash==hashlib.sha256(data.invite_code.encode()).hexdigest(),AdminInvite.used==False,AdminInvite.expires_at>now()).values(used=True))
    if result.rowcount!=1: raise HTTPException(400,'Invitation is invalid, expired, already used, or belongs to another email')
    u=create_user(db,data,'admin');db.commit();return public_user(u)

def conversation_access(db,user,id):
    c=required(db,Conversation,id)
    if user.role=='admin' or user.id not in (c.client_id,c.lawyer_user_id):raise HTTPException(403,'This conversation is private')
    return c

def conversation_json(db,c,user):
    client=db.get(User,c.client_id);lawyer=db.get(User,c.lawyer_user_id)
    other=lawyer if user.id==c.client_id else client
    latest=db.scalar(select(DirectMessage).where(DirectMessage.conversation_id==c.id).order_by(DirectMessage.id.desc()).limit(1))
    unread=db.scalar(select(func.count()).select_from(DirectMessage).where(DirectMessage.conversation_id==c.id,DirectMessage.sender_id!=user.id,DirectMessage.read_at==None)) if user.role!='admin' else 0
    return {'id':c.id,'client_id':c.client_id,'lawyer_user_id':c.lawyer_user_id,'client_name':client.name,'lawyer_name':lawyer.name,'other_id':other.id,'other_name':other.name,'other_role':other.role,'can_message':user.role!='admin' and client.active and lawyer.active and not client.deleted and not lawyer.deleted,'last_message':latest.body[:160] if latest else '', 'updated_at':aware(latest.created_at if latest else c.created_at),'unread':unread}

@router.get('/api/conversations')
def conversations(user:User=Depends(roles('client','lawyer')),db:Session=Depends(get_db)):
    stmt=select(Conversation)
    stmt=stmt.where(or_(Conversation.client_id==user.id,Conversation.lawyer_user_id==user.id))
    data=[conversation_json(db,c,user) for c in db.scalars(stmt)]
    return sorted(data,key=lambda c:c['updated_at'],reverse=True)

@router.get('/api/contacts')
def contacts(user:User=Depends(roles('client','lawyer')),db:Session=Depends(get_db)):
    if user.role=='client':
        users=db.scalars(select(User).where(User.role=='lawyer',User.active==True,User.deleted==False).order_by(User.name).limit(300))
    else:
        lawyer=db.scalar(select(Lawyer).where(Lawyer.user_id==user.id))
        appointments=select(Appointment.client_id).where(Appointment.lawyer_id==lawyer.id)
        conversations=select(Conversation.client_id).where(Conversation.lawyer_user_id==user.id)
        users=db.scalars(select(User).where(User.active==True,User.deleted==False,or_(User.id.in_(appointments),User.id.in_(conversations))).order_by(User.name))
    # Do not expose private addresses/email/contact details in the contact picker.
    return [{'id':u.id,'name':u.name,'role':u.role} for u in users]

@router.post('/api/conversations',status_code=201)
def start_conversation(data:ConversationInput,user:User=Depends(roles('client','lawyer')),db:Session=Depends(get_db)):
    other=required(db,User,data.recipient_id)
    if other.role==user.role or other.role=='admin' or not other.active or other.deleted:raise HTTPException(400,'Choose an active client/lawyer contact')
    client_id=user.id if user.role=='client' else other.id
    lawyer_id=other.id if user.role=='client' else user.id
    existing=db.scalar(select(Conversation).where(Conversation.client_id==client_id,Conversation.lawyer_user_id==lawyer_id))
    if existing:return conversation_json(db,existing,user)
    if user.role=='lawyer':
        l=db.scalar(select(Lawyer).where(Lawyer.user_id==user.id))
        if not db.scalar(select(Appointment.id).where(Appointment.client_id==other.id,Appointment.lawyer_id==l.id)):
            raise HTTPException(403,'You can contact clients who have booked with you or already contacted you')
    c=Conversation(client_id=client_id,lawyer_user_id=lawyer_id);db.add(c)
    try:
        db.flush();db.commit()
    except IntegrityError:
        db.rollback()
        c=db.scalar(select(Conversation).where(Conversation.client_id==client_id,Conversation.lawyer_user_id==lawyer_id))
        if c is None: raise
    return conversation_json(db,c,user)

@router.get('/api/conversations/{id}/messages')
def direct_messages(id:int,before:int|None=None,user:User=Depends(current_user),db:Session=Depends(get_db)):
    conversation_access(db,user,id)
    stmt=select(DirectMessage).where(DirectMessage.conversation_id==id)
    if before:stmt=stmt.where(DirectMessage.id<before)
    found=list(db.scalars(stmt.order_by(DirectMessage.id.desc()).limit(101)))
    items=found[:100];has_more=len(found)>100
    return {'items':[{'id':m.id,'sender_id':m.sender_id,'sender_name':db.get(User,m.sender_id).name,'sender_role':db.get(User,m.sender_id).role,'body':m.body,'created_at':aware(m.created_at),'read_at':aware(m.read_at) if m.read_at else None} for m in reversed(items)],'has_more':has_more}

@router.post('/api/conversations/{id}/read')
def read_conversation(id:int,user:User=Depends(roles('client','lawyer')),db:Session=Depends(get_db)):
    conversation_access(db,user,id)
    db.execute(update(DirectMessage).where(DirectMessage.conversation_id==id,DirectMessage.sender_id!=user.id,DirectMessage.read_at==None).values(read_at=now()))
    db.commit();return {'ok':True}

@router.post('/api/conversations/{id}/messages',status_code=201)
def send_direct(id:int,data:MessageInput,user:User=Depends(roles('client','lawyer')),db:Session=Depends(get_db)):
    c=conversation_access(db,user,id)
    recipient=db.get(User,c.lawyer_user_id if user.id==c.client_id else c.client_id)
    if not recipient.active or recipient.deleted:raise HTTPException(409,'This account is unavailable; conversation is read-only')
    m=DirectMessage(conversation_id=id,sender_id=user.id,body=data.body);db.add(m)
    notify(db,recipient.id,f'New direct message from {user.name}')
    db.commit();return {'id':m.id}

@router.get('/api/admin/users/{id}/details')
def user_details(id:int,user:User=Depends(roles('admin')),db:Session=Depends(get_db)):
    u=required(db,User,id);profile=db.scalar(select(Lawyer).where(Lawyer.user_id==id))
    stmt=select(Appointment).where(Appointment.lawyer_id==profile.id) if profile else select(Appointment).where(Appointment.client_id==id)
    details={'user':public_user(u),'deleted':u.deleted,'professional':lawyer_json(db,profile) if profile else None,
        'credentials':[{'id':c.id,'kind':c.kind,'filename':c.filename,'created_at':c.created_at} for c in db.scalars(select(Credential).where(Credential.lawyer_id==profile.id))] if profile else [],
        'appointments':[appointment_json(db,a) for a in db.scalars(stmt.order_by(Appointment.created_at.desc()))],
        'activities':[{'id':a.id,'action':a.action,'created_at':a.created_at} for a in db.scalars(select(Activity).where(Activity.actor_id==id).order_by(Activity.id.desc()).limit(50))]}
    log(db,user,f'Admin viewed account #{id}');db.commit()
    from .verification import serialize, Application
    details['verification_application']=serialize(db,u,db.scalar(select(Application).where(Application.user_id==u.id))) if u.role!='admin' else None
    return details

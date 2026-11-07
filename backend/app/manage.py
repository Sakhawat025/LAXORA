"""Operator commands: create-admin, seed-demo. Run with python -m app.manage."""
import argparse
import getpass
import os
from datetime import timedelta
from sqlalchemy import select
from .database import SessionLocal
from .models import User, Lawyer, Area, Slot, Activity, now
from .security import hasher

def create_admin():
    email=input('Admin email: ').strip().lower(); name=input('Admin name: ').strip()
    password=getpass.getpass('Password (minimum 10 characters): ')
    from pydantic import TypeAdapter, EmailStr
    TypeAdapter(EmailStr).validate_python(email)
    if len(password)<10 or len(name)<2: raise SystemExit('Invalid name or password')
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email==email)): raise SystemExit('Email already registered')
        db.add(User(name=name,email=email,password_hash=hasher.hash(password),role='admin'));db.commit()
    print('Admin created.')

def seed_demo():
    password=os.getenv('DEMO_PASSWORD','')
    if len(password)<10: raise SystemExit('Set DEMO_PASSWORD (minimum 10 characters) before seeding')
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email=='admin@laxora.example')): raise SystemExit('Demo data already exists; no changes made')
        areas=[]
        for name in ['Corporate Law','Family Law','Criminal Law','Property Law','Immigration Law','Employment Law']:
            a=db.scalar(select(Area).where(Area.name==name))
            if not a: a=Area(name=name);db.add(a);db.flush()
            areas.append(a)
        for role in ['admin','client']:
            db.add(User(name='Demo '+role.title(),email=role+'@laxora.example',password_hash=hasher.hash(password),role=role))
        data=[('Ayesha Rahman','Dhaka',12,'Supreme Court of Bangladesh'),('Farhan Ahmed','Dhaka',9,'Dhaka District Court'),('Nusrat Jahan','Chattogram',14,'Chattogram District Court'),('Rafiq Hasan','Rajshahi',7,'Rajshahi District Court'),('Sadia Islam','Sylhet',11,'Sylhet District Court'),('Arif Chowdhury','Dhaka',16,'Supreme Court of Bangladesh')]
        for i,(name,location,years,jurisdiction) in enumerate(data):
            u=User(name=name+' (Demo)',email=f'lawyer{i+1}@laxora.example',password_hash=hasher.hash(password),role='lawyer');db.add(u);db.flush()
            l=Lawyer(user_id=u.id,area_id=areas[i].id,location=location,jurisdiction=jurisdiction,experience=years,education='LL.B. (Honours), LL.M. — fictional demonstration profile',biography=f'Demonstration profile for {areas[i].name.lower()}. Thoughtful guidance and clear communication for every stage of your legal journey. This is fictional data, not a real legal service.',verification='verified',verification_note='Demo badge only — not a real credential review.')
            db.add(l);db.flush()
            for day in range(1,8):
                for hour in (4,5,8):
                    db.add(Slot(lawyer_id=l.id,starts_at=(now()+timedelta(days=day)).replace(hour=hour,minute=0,second=0,microsecond=0)))
        db.add(Activity(action='Fictional demonstration dataset seeded'));db.commit()
    print('Demo data ready. Accounts: admin@laxora.example, client@laxora.example, lawyer1@laxora.example through lawyer6@laxora.example. Use DEMO_PASSWORD.')
def invite_admin():
    # Keep CLI independent of the HTTP router to avoid circular imports.
    import secrets, hashlib
    from .models import AdminInvite
    from pydantic import TypeAdapter, EmailStr
    email=str(TypeAdapter(EmailStr).validate_python(input('New admin email: ').strip())).lower()
    code=secrets.token_urlsafe(32)
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email==email)):raise SystemExit('Email already registered')
        db.add(AdminInvite(email=email,token_hash=hashlib.sha256(code.encode()).hexdigest(),expires_at=now()+timedelta(hours=48)))
        db.commit()
    print('Admin registration page: http://localhost:3000/admin/register')
    print('One-time invite code (valid 48 hours):',code)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['create-admin','seed-demo','invite-admin']);a=p.parse_args()
    {'create-admin':create_admin,'seed-demo':seed_demo,'invite-admin':invite_admin}[a.command]()

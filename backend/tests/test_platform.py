"""Integration tests. Set TEST_DATABASE_URL for a disposable PostgreSQL database."""
import os
import tempfile
from datetime import timedelta
os.environ['DATABASE_URL']=os.getenv('TEST_DATABASE_URL','sqlite:///'+tempfile.mktemp(suffix='.db'))
os.environ['JWT_SECRET']='test-only-secret-not-for-deployment-1234567890'
os.environ['UPLOAD_DIR']=tempfile.mkdtemp()
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.database import Base,engine,SessionLocal
from app.models import User,Lawyer,Area,Slot,Appointment,now
from app.security import hasher
from app.main import app,ATTEMPTS

@pytest.fixture()
def setup():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine);ATTEMPTS.clear()
    with SessionLocal() as db:
        a=Area(name='Family Law');db.add(a);db.flush()
        for role,email in [('admin','admin@test.com'),('client','client@test.com'),('client','other@test.com'),('lawyer','lawyer@test.com')]:
            u=User(name=role.title(),role=role,email=email,password_hash=hasher.hash('Password123!'));db.add(u);db.flush()
            if role=='lawyer':
                l=Lawyer(user_id=u.id,area_id=a.id,location='Dhaka',jurisdiction='District Court',experience=12,verification='verified');db.add(l);db.flush()
                for day in range(1,5):db.add(Slot(lawyer_id=l.id,starts_at=(now()+timedelta(days=day)).replace(hour=10,minute=0,second=0,microsecond=0)))
        db.commit()
    yield
    Base.metadata.drop_all(engine)

def client(email):
    c=TestClient(app,headers={'X-Laxora-Request':'1'})
    r=c.post('/api/auth/login',json={'email':email,'password':'Password123!'})
    assert r.status_code==200,r.text
    return c

def book(c):
    r=c.post('/api/appointments',json={'lawyer_id':1,'slot_id':1,'issue':'I need advice on a family matter','contact':'client@test.com'})
    assert r.status_code==201,r.text
    return r.json()['id']

def test_auth_and_roles(setup):
    c=TestClient(app)
    assert c.get('/api/auth/me').status_code==401
    assert c.post('/api/auth/register',json={'name':'Attacker','email':'evil@test.com','password':'Password123!','role':'admin'}).status_code==422
    assert c.post('/api/auth/login',json={'email':'client@test.com','password':'wrong'}).status_code==401
    c=client('client@test.com')
    assert c.get('/api/admin/users').status_code==403
    assert c.get('/api/lawyers/me/profile').status_code==403
    assert 'HttpOnly' in c.cookies.jar._cookies['testserver.local']['/']['laxora_session']._rest
    assert c.put('/api/auth/password',json={'current_password':'wrong','new_password':'NewPassword12!'}).status_code==400
    assert c.put('/api/auth/password',json={'current_password':'Password123!','new_password':'NewPassword12!'}).status_code==200
    assert c.post('/api/auth/logout').status_code==200
    assert c.get('/api/auth/me').status_code==401

def test_booking_workflow_and_privacy(setup):
    c=client('client@test.com');other=client('other@test.com');l=client('lawyer@test.com');id=book(c)
    assert other.get('/api/appointments').json()==[]
    assert other.get(f'/api/appointments/{id}/messages').status_code==403
    assert c.patch(f'/api/appointments/{id}',json={'status':'approved'}).status_code==403
    assert other.post('/api/appointments',json={'lawyer_id':1,'slot_id':1,'issue':'Another consultation request','contact':'other@test.com'}).status_code==409
    assert l.patch(f'/api/appointments/{id}',json={'status':'approved'}).status_code==200
    assert l.patch(f'/api/appointments/{id}',json={'slot_id':2}).status_code==200
    assert c.post(f'/api/appointments/{id}/messages',json={'body':'Thank you for your time'}).status_code==201
    assert len(l.get(f'/api/appointments/{id}/messages').json())==1
    assert l.patch(f'/api/appointments/{id}',json={'status':'completed'}).status_code==400
    assert c.patch(f'/api/appointments/{id}',json={'status':'cancelled'}).status_code==200
    assert l.patch(f'/api/appointments/{id}',json={'status':'approved'}).status_code==409
    assert c.post(f'/api/appointments/{id}/messages',json={'body':'closed'}).status_code==409
    assert len(c.get('/api/notifications').json())>=2
    assert c.post('/api/notifications/read').status_code==200
    assert all(n['read'] for n in c.get('/api/notifications').json())

def test_credentials_and_verification(setup):
    l=client('lawyer@test.com');a=client('admin@test.com');c=client('client@test.com')
    assert a.patch('/api/admin/lawyers/1/verification',json={'status':'verified','note':'ok'}).status_code==409
    assert l.post('/api/lawyers/me/credentials',data={'kind':'identity'},files={'file':('bad.html',b'<script>alert(1)</script>','text/html')}).status_code==422
    ids=[]
    for kind in ['bar_license','identity']:
        r=l.post('/api/lawyers/me/credentials',data={'kind':kind},files={'file':('../../test.pdf',b'%PDF-1.4\nTest document','application/pdf')})
        assert r.status_code==201,r.text
        ids.append(r.json()['id'])
    assert c.get(f'/api/credentials/{ids[0]}/download').status_code==403
    assert c.get('/api/lawyers/1/credentials').status_code==403
    assert a.get(f'/api/credentials/{ids[0]}/download').status_code==200
    assert a.patch('/api/admin/lawyers/1/verification',json={'status':'verified','note':'Reviewed'}).status_code==409
    assert l.delete(f'/api/credentials/{ids[0]}').status_code==200
    assert l.get('/api/lawyers/me/profile').json()['verification']=='pending'

def test_admin_management_search_and_reports(setup):
    a=client('admin@test.com');c=client('client@test.com')
    assert c.get('/api/lawyers?location=Dhaka&experience=10').json()['total']==1
    assert c.get('/api/lawyers?location=Sylhet').json()['total']==0
    r=a.post('/api/admin/areas',json={'name':'Property Law'});assert r.status_code==201;aid=r.json()['id']
    assert a.put(f'/api/admin/areas/{aid}',json={'name':'Property'}).status_code==200
    assert a.delete('/api/admin/areas/1').status_code==409
    assert a.delete(f'/api/admin/areas/{aid}').status_code==200
    assert a.post('/api/admin/lawyers',json={'name':'New Lawyer','email':'new@test.com','password':'Password123!','role':'lawyer','professional':{'area_id':1,'experience':3}}).status_code==201
    users=a.get('/api/admin/users').json();cid=next(u['id'] for u in users if u['email']=='client@test.com')
    assert a.patch(f'/api/admin/users/{cid}',json={'active':False}).status_code==200
    assert c.get('/api/auth/me').status_code==401
    assert a.patch(f'/api/admin/users/{cid}',json={'active':True}).status_code==200
    assert a.delete(f'/api/admin/users/{cid}').status_code==200
    assert len(a.get('/api/admin/users').json())==4
    assert a.get('/api/admin/reports').json()['summary']['total_users']==4
    assert a.get('/api/admin/reports.csv').headers['content-type'].startswith('text/csv')

def test_csrf_validation_and_slots(setup):
    c=client('client@test.com')
    assert c.put('/api/auth/me',headers={'origin':'https://evil.test'},json={'name':'Changed','phone':''}).status_code==403
    c.headers.pop('X-Laxora-Request')
    assert c.put('/api/auth/me',json={'name':'Changed','phone':''}).status_code==403
    l=client('lawyer@test.com')
    assert l.post('/api/lawyers/me/slots',json={'starts_at':'2020-01-01T10:00:00Z'}).status_code==422
    future=(now()+timedelta(days=8)).replace(hour=12,minute=0,second=0,microsecond=0).isoformat()
    r=l.post('/api/lawyers/me/slots',json={'starts_at':future});assert r.status_code==201
    assert l.post('/api/lawyers/me/slots',json={'starts_at':future}).status_code==409
    assert l.delete('/api/lawyers/me/slots/'+str(r.json()['id'])).status_code==200

def test_concurrent_booking_postgres(setup):
    if engine.dialect.name!='postgresql':pytest.skip('Real concurrency test requires PostgreSQL')
    from concurrent.futures import ThreadPoolExecutor
    c=client('client@test.com');d=client('other@test.com')
    payload={'lawyer_id':1,'slot_id':1,'issue':'Concurrent consultation request','contact':'test@test.com'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda x:x.post('/api/appointments',json=payload).status_code,[c,d]))
    assert sorted(results)==[201,409]

def test_role_login_and_invitation_onboarding(setup):
    from app.models import AdminInvite
    a=client('admin@test.com');public=TestClient(app)
    assert public.post('/api/auth/login',json={'email':'client@test.com','password':'Password123!','role':'lawyer'}).status_code==403
    assert 'laxora_session' not in public.cookies
    assert public.post('/api/admin/invites',json={'email':'newadmin@test.com'}).status_code==401
    r=a.post('/api/admin/invites',json={'email':'newadmin@test.com'})
    assert r.status_code==201,r.text
    code=r.json()['invite_code']
    payload={'name':'Invited Admin','email':'newadmin@test.com','password':'NewPassword123!','invite_code':code}
    assert public.post('/api/auth/admin-register',json={**payload,'email':'wrong@test.com'}).status_code==400
    r=public.post('/api/auth/admin-register',json=payload)
    assert r.status_code==201 and r.json()['role']=='admin',r.text
    assert public.post('/api/auth/admin-register',json=payload).status_code==400
    assert public.post('/api/auth/login',json={'email':'newadmin@test.com','password':'NewPassword123!','role':'admin'}).status_code==200
    r=a.post('/api/admin/invites',json={'email':'expired@test.com'});code=r.json()['invite_code']
    with SessionLocal() as db:
        i=db.scalar(select(AdminInvite).where(AdminInvite.email=='expired@test.com'));i.expires_at=now()-timedelta(hours=1);db.commit()
    other=TestClient(app)
    assert other.post('/api/auth/admin-register',json={**payload,'email':'expired@test.com','invite_code':code}).status_code==400

def test_direct_messaging_privacy_replies_and_reads(setup):
    from app.models import User
    c=client('client@test.com');l=client('lawyer@test.com');o=client('other@test.com');a=client('admin@test.com')
    lid=l.get('/api/auth/me').json()['id'];cid=c.get('/api/auth/me').json()['id'];oid=o.get('/api/auth/me').json()['id']
    assert l.post('/api/conversations',json={'recipient_id':oid}).status_code==403
    assert l.get('/api/contacts').json()==[]
    r=c.post('/api/conversations',json={'recipient_id':lid});assert r.status_code==201,r.text
    tid=r.json()['id']
    assert c.post('/api/conversations',json={'recipient_id':lid}).json()['id']==tid
    assert c.post(f'/api/conversations/{tid}/messages',json={'body':'Hello, can we discuss my legal question?'}).status_code==201
    assert o.get(f'/api/conversations/{tid}/messages').status_code==403
    assert o.post(f'/api/conversations/{tid}/messages',json={'body':'unauthorized'}).status_code==403
    assert o.post(f'/api/conversations/{tid}/read').status_code==403
    assert l.get('/api/conversations').json()[0]['unread']==1
    assert l.post(f'/api/conversations/{tid}/read').status_code==200
    assert c.get(f'/api/conversations/{tid}/messages').json()['items'][0]['read_at'] is not None
    assert l.post(f'/api/conversations/{tid}/messages',json={'body':'Yes, please share more details.'}).status_code==201
    assert len(c.get(f'/api/conversations/{tid}/messages').json()['items'])==2
    assert c.get('/api/conversations').json()[0]['unread']==1
    assert l.get('/api/contacts').json()[0]['id']==cid
    assert a.get(f'/api/conversations/{tid}/messages').status_code==403
    assert a.get('/api/conversations').status_code==403
    assert a.get('/api/contacts').status_code==403
    assert a.post(f'/api/conversations/{tid}/messages',json={'body':'Admin cannot impersonate a participant'}).status_code==403
    assert a.post(f'/api/conversations/{tid}/read').status_code==403
    assert a.patch(f'/api/admin/users/{lid}',json={'active':False}).status_code==200
    assert c.post(f'/api/conversations/{tid}/messages',json={'body':'blocked'}).status_code==409
    assert c.get(f'/api/conversations/{tid}/messages').status_code==200

def test_admin_complete_account_details_and_message_pagination(setup):
    from app.models import DirectMessage
    c=client('client@test.com');l=client('lawyer@test.com');a=client('admin@test.com')
    cid=c.get('/api/auth/me').json()['id'];lid=l.get('/api/auth/me').json()['id']
    assert c.put('/api/auth/me',json={'name':'Client Name','phone':'12345','city':'Dhaka','address':'A private address','bio':'A private client profile'}).status_code==200
    assert l.get(f'/api/admin/users/{cid}/details').status_code==403
    book(c)
    tid=c.post('/api/conversations',json={'recipient_id':lid}).json()['id']
    with SessionLocal() as db:
        db.add_all([DirectMessage(conversation_id=tid,sender_id=cid,body=f'Message {i}') for i in range(105)]);db.commit()
    d=a.get(f'/api/admin/users/{cid}/details').json()
    assert d['user']['address']=='A private address' and d['user']['city']=='Dhaka'
    assert len(d['appointments'])==1 and 'conversations' not in d
    assert 'password_hash' not in d['user'] and 'token_version' not in d['user']
    ld=a.get(f'/api/admin/users/{lid}/details').json();assert ld['professional']['experience']==12
    first=c.get(f'/api/conversations/{tid}/messages').json();assert len(first['items'])==100 and first['has_more']
    older=c.get(f'/api/conversations/{tid}/messages?before={first["items"][0]["id"]}').json()
    assert len(older['items'])==5 and not older['has_more']

def photo_bytes():
    import io
    from PIL import Image
    b=io.BytesIO();Image.new('RGB',(40,40),(25,40,60)).save(b,format='PNG');return b.getvalue()

def complete_identity(c):
    assert c.put('/api/auth/me',json={'name':'Test Person','phone':'01700000000','city':'Dhaka','address':'Test street','bio':'Profile information'}).status_code==200
    r=c.post('/api/auth/photo',files={'file':('profile.png',photo_bytes(),'image/png')});assert r.status_code==200,r.text
    r=c.put('/api/verification/me',json={'legal_name':'Test Person','country':'Bangladesh','declaration':True,'consent':True});assert r.status_code==200,r.text
    r=c.post('/api/verification/documents',data={'kind':'identity'},files={'file':('identity.pdf',b'%PDF-1.4\nIdentity','application/pdf')});assert r.status_code==201,r.text

def test_photos_privacy_validation_and_logout_all_roles(setup):
    a=client('admin@test.com');c=client('client@test.com');l=client('lawyer@test.com');other=client('other@test.com');public=TestClient(app)
    for owner in [c,l,a]:
        assert owner.post('/api/auth/photo',files={'file':('bad.png',b'not an image','image/png')}).status_code==422
        r=owner.post('/api/auth/photo',files={'file':('valid.png',photo_bytes(),'image/png')});assert r.status_code==200,r.text
        url=r.json()['photo_url'];assert owner.get(url).status_code==200
        assert a.get(url).status_code==200
        is_lawyer=r.json()['role']=='lawyer'
        assert public.get(url).status_code==(200 if is_lawyer else 401)
        assert other.get(url).status_code==(200 if is_lawyer else 403)
        assert owner.delete('/api/auth/photo').status_code==200
        assert owner.get(url).status_code==404
        assert owner.post('/api/auth/logout').status_code==200
        assert owner.get('/api/auth/me').status_code==401

def test_new_registrations_visible_to_admin(setup):
    a=client('admin@test.com')
    for role in ['client','lawyer']:
        c=TestClient(app,headers={'X-Laxora-Request':'1'})
        r=c.post('/api/auth/register',json={'name':'New Person','email':role+'new@test.com','password':'Password123!','role':role});assert r.status_code==201,r.text
        assert r.json()['id'] in [u['id'] for u in a.get('/api/admin/users').json()]
        assert any('New '+role+' registered' in n['text'] for n in a.get('/api/notifications').json())

def test_client_verification_submission_review_and_invalidation(setup):
    c=client('client@test.com');a=client('admin@test.com');o=client('other@test.com')
    assert c.get('/api/verification/me').json()['status']=='not_submitted'
    assert c.post('/api/verification/submit').status_code==422
    complete_identity(c)
    doc=c.get('/api/verification/me').json()['documents'][0]
    assert o.get(doc['url']).status_code==403
    assert a.get(doc['url']).status_code==200
    assert o.delete('/api/verification/documents/'+str(doc['id'])).status_code==403
    r=c.post('/api/verification/submit');assert r.status_code==200,r.text
    data=r.json();assert data['status']=='pending' and not data['missing']
    assert c.post('/api/verification/submit').status_code==409
    assert any(x['id']==data['id'] for x in a.get('/api/admin/verifications').json())
    payload={'status':'verified','note':'Identity checked','version':data['version']}
    url='/api/admin/verifications/'+str(data['id'])
    assert c.patch(url,json=payload).status_code==403
    assert a.patch(url,json={**payload,'version':0}).status_code==409
    assert a.patch(url,json=payload).status_code==200
    assert c.get('/api/verification/me').json()['status']=='verified'
    assert a.patch(url,json=payload).status_code==409
    assert any('verification is verified' in n['text'] for n in c.get('/api/notifications').json())
    assert c.delete('/api/auth/photo').status_code==200
    assert c.get('/api/verification/me').json()['status']=='draft'
    assert c.post('/api/verification/submit').status_code==422
    info=a.get('/api/admin/users/2/details').json()['verification_application'];assert info['details']['legal_name']=='Test Person'

def test_lawyer_full_verification_higher_court_and_rejection(setup):
    l=client('lawyer@test.com');a=client('admin@test.com')
    complete_identity(l)
    assert l.put('/api/lawyers/me/profile',json={'area_id':1,'biography':'Family law practitioner','education':'LLB','experience':5,'jurisdiction':'Dhaka','location':'Dhaka'}).status_code==200
    detail={'legal_name':'Test Person','country':'Bangladesh','declaration':True,'consent':True,'bar_council':'Test Council','enrollment_number':'TEST-123','enrollment_date':'2020-01-01','bar_association':'Test association','practicing_courts':'District Court','chamber_name':'Test chamber','chamber_address':'Test address','chamber_phone':'01700000000','degree':'LLB','university':'Test university','graduation_year':2019,'higher_court_practice':True}
    assert l.put('/api/verification/me',json=detail).status_code==200
    for kind in ['bar_license','certificate']:
        assert l.post('/api/verification/documents',data={'kind':kind},files={'file':(kind+'.pdf',b'%PDF-1.4\nDocument','application/pdf')}).status_code==201
    assert l.post('/api/verification/submit').status_code==422
    assert l.post('/api/verification/documents',data={'kind':'court_permission'},files={'file':('court.pdf',b'%PDF-1.4\nCourt','application/pdf')}).status_code==201
    r=l.post('/api/verification/submit');assert r.status_code==200,r.text
    d=r.json();url='/api/admin/verifications/'+str(d['id'])
    assert a.patch(url,json={'status':'rejected','note':'Upload a clearer license copy','version':d['version']}).status_code==200
    assert l.get('/api/lawyers/me/profile').json()['verification']=='rejected'
    assert l.put('/api/verification/me',json=detail).status_code==200
    d=l.post('/api/verification/submit').json()
    assert a.patch(url,json={'status':'verified','note':'All documents reviewed','version':d['version']}).status_code==200
    assert l.get('/api/lawyers/me/profile').json()['verification']=='verified'
    assert l.post('/api/lawyers/me/credentials',data={'kind':'certificate'},files={'file':('extra.pdf',b'%PDF-1.4\nextra','application/pdf')}).status_code==201
    assert l.get('/api/verification/me').json()['status']=='draft'


def test_same_browser_role_sessions_sender_identity_and_private_access(setup):
    browser=TestClient(app,headers={'X-Laxora-Request':'1'})
    ids={}
    for role in ['client','lawyer','admin']:
        r=browser.post('/api/auth/login',json={'email':role+'@test.com','password':'Password123!','role':role})
        assert r.status_code==200
        ids[role]=r.json()['id']
    def headers(role):return {'X-Laxora-Role':role,'X-Laxora-User':str(ids[role])}
    for role in ids:assert browser.get('/api/auth/me',headers=headers(role)).json()['role']==role
    r=browser.post('/api/conversations',headers=headers('client'),json={'recipient_id':ids['lawyer']})
    assert r.status_code==201,r.text
    tid=r.json()['id'];url=f'/api/conversations/{tid}/messages'
    assert browser.post(url,headers=headers('client'),json={'body':'Client question'}).status_code==201
    assert browser.post(url,headers=headers('lawyer'),json={'body':'Lawyer reply'}).status_code==201
    for role in ['client','lawyer']:
        items=browser.get(url,headers=headers(role)).json()['items']
        assert [(m['sender_id'],m['sender_name'],m['sender_role']) for m in items]==[(ids['client'],'Client','client'),(ids['lawyer'],'Lawyer','lawyer')]
        assert [m['sender_id']==ids[role] for m in items]==([True,False] if role=='client' else [False,True])
    assert browser.get(url,headers=headers('admin')).status_code==403
    assert browser.get('/api/conversations',headers=headers('admin')).status_code==403
    assert 'conversations' not in browser.get('/api/admin/users/2/details',headers=headers('admin')).json()
    aid=browser.post('/api/appointments',headers=headers('client'),json={'lawyer_id':1,'slot_id':1,'issue':'Need legal consultation','contact':'client@test.com'}).json()['id']
    assert browser.post(f'/api/appointments/{aid}/messages',headers=headers('client'),json={'body':'Private appointment message'}).status_code==201
    assert browser.get(f'/api/appointments/{aid}/messages',headers=headers('admin')).status_code==403
    assert browser.post(f'/api/appointments/{aid}/messages',headers=headers('admin'),json={'body':'No admin messages'}).status_code==403
    assert browser.post('/api/auth/logout',headers=headers('admin')).status_code==200
    assert browser.get('/api/auth/me',headers=headers('client')).status_code==200
    assert browser.get('/api/auth/me',headers=headers('lawyer')).status_code==200
    assert browser.post('/api/auth/login',json={'email':'other@test.com','password':'Password123!','role':'client'}).status_code==200
    assert browser.post(url,headers=headers('client'),json={'body':'Must not be sent from stale tab'}).status_code==409
    assert len(browser.get(url,headers=headers('lawyer')).json()['items'])==2

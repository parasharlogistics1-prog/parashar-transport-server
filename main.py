import os, re, sqlite3, secrets
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

DB = os.getenv('DB_FILE', 'parashar_cloud.db')
API_KEY = os.getenv('PARASHAR_API_KEY', '')
app = FastAPI(title='PARASHAR TRANSPORT Internet API', version='1.0')

def conn():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init():
    c=conn(); c.executescript('''
    CREATE TABLE IF NOT EXISTS lr_entries(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      vehicle_no TEXT NOT NULL,
      station TEXT NOT NULL,
      lr_no TEXT NOT NULL,
      lr_key TEXT NOT NULL,
      weight TEXT NOT NULL,
      submitted_by TEXT NOT NULL,
      submitted_at TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT 'ANDROID'
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_lr_key ON lr_entries(lr_key);
    CREATE TABLE IF NOT EXISTS audit_log(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      action TEXT NOT NULL,
      lr_id INTEGER,
      lr_no TEXT,
      user_name TEXT NOT NULL,
      event_time TEXT NOT NULL,
      details TEXT NOT NULL
    );
    '''); c.commit(); c.close()
init()

def key_parts(s):
    parts=re.findall(r'[A-Za-z0-9]+', str(s).upper())
    return ''.join(parts), parts

def auth(x_api_key):
    if API_KEY and x_api_key != API_KEY: raise HTTPException(401,'Invalid API key')

class LR(BaseModel):
    vehicle_no: str = Field(min_length=1, max_length=40)
    station: str = Field(min_length=1, max_length=100)
    lr_no: str = Field(min_length=1, max_length=80)
    weight: str = Field(min_length=1, max_length=40)
    submitted_by: str = Field(default='Android User', max_length=80)

@app.get('/health')
def health(): return {'ok':True,'service':'PARASHAR TRANSPORT','utc':datetime.now(timezone.utc).isoformat()}

@app.post('/api/lr')
def create_lr(item: LR, x_api_key: str = Header(default='')):
    auth(x_api_key)
    vehicle=item.vehicle_no.strip().upper(); station=item.station.strip(); lr=item.lr_no.strip(); weight=item.weight.strip(); user=item.submitted_by.strip() or 'Android User'
    norm,_=key_parts(lr)
    if not norm: raise HTTPException(400,'Invalid LR number')
    c=conn(); rows=c.execute('SELECT id,lr_no FROM lr_entries').fetchall()
    for r in rows:
        oldnorm, oldparts=key_parts(r['lr_no'])
        _, newparts=key_parts(lr)
        if norm==oldnorm or set(newparts)&set(oldparts):
            c.close(); raise HTTPException(409,f'LR number already used: {r["lr_no"]}')
    now=datetime.now(timezone.utc).isoformat()
    cur=c.execute('INSERT INTO lr_entries(vehicle_no,station,lr_no,lr_key,weight,submitted_by,submitted_at) VALUES(?,?,?,?,?,?,?)',(vehicle,station,lr,norm,weight,user,now))
    lrid=cur.lastrowid
    c.execute('INSERT INTO audit_log(action,lr_id,lr_no,user_name,event_time,details) VALUES(?,?,?,?,?,?)',('CREATE',lrid,lr,user,now,f'Android entry | Vehicle={vehicle} | Station={station} | Weight={weight}'))
    c.commit(); c.close()
    return {'ok':True,'id':lrid,'message':'LR submitted and audit updated','submitted_at':now}

@app.get('/api/lr/recent')
def recent(limit:int=30, x_api_key:str=Header(default='')):
    auth(x_api_key); limit=max(1,min(limit,200)); c=conn(); rows=c.execute('SELECT * FROM lr_entries ORDER BY id DESC LIMIT ?', (limit,)).fetchall(); c.close(); return [dict(r) for r in rows]

@app.get('/api/audit')
def audit(limit:int=100, x_api_key:str=Header(default='')):
    auth(x_api_key); limit=max(1,min(limit,500)); c=conn(); rows=c.execute('SELECT * FROM audit_log ORDER BY id DESC LIMIT ?', (limit,)).fetchall(); c.close(); return [dict(r) for r in rows]

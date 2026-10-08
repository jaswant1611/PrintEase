from flask import Flask, request, jsonify, send_from_directory, session, render_template, redirect
from werkzeug.utils import secure_filename
from pathlib import Path
from datetime import datetime
import sqlite3, hashlib, os, uuid, time

BASE = Path(__file__).resolve().parent
DATA = path(os.environ.get('PRINTEASE_DATA_DIR', BASE / 'data'))
UPLOADS = DATA / 'uploads'
DB = DATA / 'printease.db'
UPLOADS.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get('PRINTEASE_SECRET', 'CHANGE_THIS_SECRET_BEFORE_DEPLOY')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
ADMIN_USER = os.environ.get('PRINTEASE_ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('PRINTEASE_ADMIN_PASS', 'admin123')
ALLOWED = {'.pdf','.doc','.docx','.ppt','.pptx','.xls','.xlsx','.csv','.txt'}
DEFAULT_RATES = {'bw_single':1,'bw_double':1.5,'color_single':5,'color_double':8,'a3_extra':5,'service':5,'first_discount':50}
STATUSES = ['Waiting','Printing','Ready','Collected','Cancelled']

def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def hp(x): return hashlib.sha256((x or '').encode()).hexdigest()

def init():
    c = con()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS customers(
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT UNIQUE NOT NULL,
      password TEXT NOT NULL, member INTEGER DEFAULT 0, orders INTEGER DEFAULT 0,
      created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS rates(key TEXT PRIMARY KEY, value REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS orders(
      id INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL, customer_id INTEGER,
      filename TEXT, stored TEXT, pages INTEGER, copies INTEGER, color TEXT,
      sides TEXT, paper TEXT, printing REAL, service REAL, discount REAL,
      total REAL, paid INTEGER DEFAULT 0, status TEXT DEFAULT 'Waiting',
      created TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(customer_id) REFERENCES customers(id));
    ''')
    for k,v in DEFAULT_RATES.items(): c.execute('INSERT OR IGNORE INTO rates VALUES (?,?)',(k,v))
    c.commit(); c.close()

def rates():
    c=con(); r={x['key']:x['value'] for x in c.execute('SELECT * FROM rates')}; c.close(); return r

def page_count(path):
    if path.suffix.lower() != '.pdf': return None
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except Exception: return None

def calculate(pages,copies,color,sides,paper,member,first):
    r=rates(); key=('color_' if color=='Color' else 'bw_') + ('double' if sides=='Double' else 'single')
    unit=float(r[key]) + (float(r['a3_extra']) if paper=='A3' else 0)
    printing=pages*copies*unit
    service=0 if member else float(r['service'])
    discount=(printing+service)*float(r['first_discount'])/100 if first else 0
    return tuple(round(x,2) for x in (printing,service,discount,printing+service-discount))

def current_customer():
    cid=session.get('cid')
    if not cid: return None
    c=con(); u=c.execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone(); c.close(); return u

def admin_ok(): return bool(session.get('admin'))

def api_error(msg,code=400): return jsonify(error=msg),code

@app.get('/')
def home(): return render_template('student.html')
@app.get('/admin')
def admin(): return render_template('admin.html')

@app.post('/api/register')
def register():
    d=request.json or {}
    if not all(str(d.get(k,'')).strip() for k in ('name','phone','password')): return api_error('Name, phone and password are required')
    if len(d['password'])<6: return api_error('Password must be at least 6 characters')
    c=con()
    try:
        c.execute('INSERT INTO customers(name,phone,password) VALUES(?,?,?)',(d['name'].strip(),d['phone'].strip(),hp(d['password'])))
        c.commit()
    except sqlite3.IntegrityError:
        c.close(); return api_error('Phone number already registered',409)
    c.close(); return jsonify(ok=True)

@app.post('/api/login')
def login():
    d=request.json or {}; c=con(); u=c.execute('SELECT * FROM customers WHERE phone=? AND password=?',(d.get('phone','').strip(),hp(d.get('password','')))).fetchone(); c.close()
    if not u: return api_error('Invalid phone or password',401)
    session.clear(); session['cid']=u['id']; return jsonify(ok=True,name=u['name'])

@app.get('/api/me')
def me():
    u=current_customer(); return jsonify(logged_in=bool(u), **(dict(u) if u else {}))

@app.post('/api/logout')
def logout(): session.clear(); return jsonify(ok=True)

@app.post('/api/quote')
def quote():
    d=request.json or {}; u=current_customer(); member=bool(u['member']) if u else False; first=bool(u and u['orders']==0)
    try: p=max(1,int(d.get('pages',1))); n=max(1,int(d.get('copies',1)))
    except: return api_error('Pages/copies must be numbers')
    vals=calculate(p,n,d.get('color','B&W'),d.get('sides','Single'),d.get('paper','A4'),member,first)
    return jsonify(printing=vals[0],service=vals[1],discount=vals[2],total=vals[3],member=member,first_order=first)

@app.post('/api/order')
def order():
    u=current_customer()
    if not u: return api_error('Login required',401)
    f=request.files.get('file')
    if not f or not f.filename: return api_error('Choose a document')
    ext=Path(f.filename).suffix.lower()
    if ext not in ALLOWED: return api_error('Unsupported file type. Use PDF, DOC/DOCX, PPT/PPTX, XLS/XLSX, CSV or TXT.')
    try: copies=max(1,int(request.form.get('copies',1)))
    except: return api_error('Copies must be a number')
    supplied=request.form.get('pages','').strip()
    saved_name=secure_filename(f.filename) or 'document'
    token='P'+datetime.now().strftime('%y%m%d')+'-'+uuid.uuid4().hex[:5].upper()
    stored=token+'_'+saved_name
    target=UPLOADS/stored; f.save(target)
    auto=page_count(target)
    try: pages=max(1,int(supplied or auto or 1))
    except: pages=max(1,auto or 1)
    color=request.form.get('color','B&W'); sides=request.form.get('sides','Single'); paper=request.form.get('paper','A4')
    printing,service,discount,total=calculate(pages,copies,color,sides,paper,bool(u['member']),u['orders']==0)
    c=con(); c.execute('''INSERT INTO orders(token,customer_id,filename,stored,pages,copies,color,sides,paper,printing,service,discount,total)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(token,u['id'],saved_name,stored,pages,copies,color,sides,paper,printing,service,discount,total))
    c.execute('UPDATE customers SET orders=orders+1 WHERE id=?',(u['id'],)); c.commit(); c.close()
    return jsonify(ok=True,token=token,total=total,pages=pages,auto_pages=bool(auto),status='Waiting')

@app.get('/api/orders')
def myorders():
    u=current_customer()
    if not u: return api_error('Login required',401)
    c=con(); rows=c.execute('SELECT token,filename,pages,copies,color,sides,paper,total,paid,status,created FROM orders WHERE customer_id=? ORDER BY id DESC',(u['id'],)).fetchall(); c.close()
    return jsonify(orders=[dict(x) for x in rows])

@app.post('/api/admin/login')
def admin_login():
    d=request.json or {}
    if d.get('username')==ADMIN_USER and d.get('password')==ADMIN_PASS:
        session.clear(); session['admin']=True; return jsonify(ok=True)
    return api_error('Invalid admin login',401)

@app.post('/api/admin/logout')
def admin_logout(): session.clear(); return jsonify(ok=True)

@app.get('/api/admin/orders')
def admin_orders():
    if not admin_ok(): return api_error('Admin login required',401)
    c=con(); rows=c.execute('''SELECT o.*,c.name,c.phone FROM orders o LEFT JOIN customers c ON c.id=o.customer_id ORDER BY o.id DESC''').fetchall(); c.close()
    return jsonify(orders=[dict(x) for x in rows])

@app.get('/api/admin/stats')
def stats():
    if not admin_ok(): return api_error('Admin login required',401)
    c=con(); today=datetime.now().strftime('%Y-%m-%d')
    row=c.execute('''SELECT COUNT(*) n,COALESCE(SUM(total),0) revenue,COALESCE(SUM(pages*copies),0) pages FROM orders WHERE date(created)=?''',(today,)).fetchone()
    ready=c.execute("SELECT COUNT(*) n FROM orders WHERE status='Ready'").fetchone()['n']; c.close()
    return jsonify(orders=row['n'],revenue=round(row['revenue'],2),pages=row['pages'],ready=ready)

@app.post('/api/admin/order/<token>/status')
def set_status(token):
    if not admin_ok(): return api_error('Admin login required',401)
    s=(request.json or {}).get('status')
    if s not in STATUSES: return api_error('Invalid status')
    c=con(); cur=c.execute('UPDATE orders SET status=? WHERE token=?',(s,token)); c.commit(); c.close()
    if cur.rowcount==0: return api_error('Order not found',404)
    return jsonify(ok=True)

@app.post('/api/admin/order/<token>/paid')
def set_paid(token):
    if not admin_ok(): return api_error('Admin login required',401)
    paid=1 if (request.json or {}).get('paid') else 0; c=con(); c.execute('UPDATE orders SET paid=? WHERE token=?',(paid,token)); c.commit(); c.close(); return jsonify(ok=True)

@app.route('/api/admin/rates',methods=['GET','POST'])
def admin_rates():
    if not admin_ok(): return api_error('Admin login required',401)
    if request.method=='GET': return jsonify(rates=rates())
    c=con()
    for k,v in (request.json or {}).items():
        if k in DEFAULT_RATES:
            try: c.execute('UPDATE rates SET value=? WHERE key=?',(float(v),k))
            except: pass
    c.commit(); c.close(); return jsonify(ok=True,rates=rates())

@app.get('/files/<path:name>')
def file_download(name):
    if not admin_ok(): return 'Unauthorized',401
    return send_from_directory(UPLOADS,name,as_attachment=True)

@app.errorhandler(413)
def too_large(e): return api_error('File too large. Maximum upload size is 50 MB.',413)

init()

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT','8080')),debug=False)

import os
import re
import uuid
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, session, redirect, url_for, flash, g, render_template_string
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# Сырсөздөрдү .env файлынан алат, эгер жок болсо демо-маанилерди колдонот
app.secret_key = os.getenv('SECRET_KEY', 'super-secret-key-123')
app.config['ADMIN_PASSWORD'] = os.getenv('ADMIN_PASSWORD', 'admin123') # Админдин паролу

DB_PATH = os.getenv('DB_PATH', 'app.db')
MIN_WITHDRAW = 100.0
DAILY_BONUS = 2.0 # Күнүмдүк кирүү бонусу
COMMISSION_RATE = 0.20 # Ар бир тапшырмадан сизге (админге) түшө турган 20% пайыз

# ═══════════════════════════════════════════
#  БАЗА ТҮЗҮҮ
# ═══════════════════════════════════════════
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            phone TEXT UNIQUE NOT NULL,
            name TEXT DEFAULT '',
            referral_code TEXT UNIQUE NOT NULL,
            referred_by TEXT,
            balance REAL DEFAULT 0,
            admin_balance REAL DEFAULT 0, -- Админдин пайдасы үчүн
            last_bonus_date TEXT, -- Күнүмдүк бонус үчүн
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            reward REAL NOT NULL,
            task_type TEXT DEFAULT 'task', -- 'video', 'game', 'survey', 'task'
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            phone TEXT NOT NULL,
            method TEXT DEFAULT 'MegaCom', -- Visa, MBank, MegaCom, O!, Beeline
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            processed_at TEXT
        );
        """)
        # Демо тапшырмаларды кошуу
        if conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO tasks (title, description, reward, task_type) VALUES (?,?,?,?)",
                [
                    ("Кыска видео көрүү", "Жарнаманы көрүп, акча алыңыз", 2.0, "video"),
                    ("Оюн ойноо (3D Cube)", "Оюнду ойноп бүтүрүңүз", 5.0, "game"),
                    ("Сурамжылоо", "Кыска суроолорго жооп бериңиз", 3.0, "survey"),
                    ("Күнүмдүк активдүүлүк", "Системага киргениңиз үчүн", 1.0, "task")
                ]
            )
        conn.commit()

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# ═══════════════════════════════════════════
#  ЖАРДАМЧЫ ФУНКЦИЯЛАР
# ═══════════════════════════════════════════
def normalize_phone(phone):
    digits = re.sub(r'\D', '', str(phone))
    if digits.startswith('996'): digits = digits[3:]
    elif digits.startswith('0'): digits = digits[1:]
    if len(digits) != 9 or digits[0] not in '2579': return None
    return '+996' + digits

def now_iso(): return datetime.utcnow().isoformat()

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            flash('Сураныч, кириңиз', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped

def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('is_admin'):
            flash('Админ уруксаты жок!', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped

def render(body_template, **kwargs):
    body_html = render_template_string(body_template, **kwargs)
    return render_template_string(BASE_LAYOUT, body=body_html, **kwargs)

# ═══════════════════════════════════════════
#  ДИЗАЙН (BASE LAYOUT)
# ═══════════════════════════════════════════
BASE_LAYOUT = """
<!DOCTYPE html>
<html lang="ky">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Бонус Системасы</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0;font-family:sans-serif}
  body{background:#0f172a;color:#e2e8f0;padding:16px}
  .container{max-width:600px;margin:0 auto}
  .card{background:#1e293b;border-radius:12px;padding:20px;margin-bottom:16px;box-shadow:0 4px 6px rgba(0,0,0,0.3)}
  h1,h2,h3{margin-bottom:12px;color:#38bdf8}
  .btn{display:block;width:100%;background:#2563eb;color:#fff;padding:12px;border-radius:8px;border:none;text-decoration:none;cursor:pointer;font-size:16px;text-align:center;margin-bottom:10px}
  .btn:hover{background:#1d4ed8}
  .btn-success{background:#16a34a}.btn-success:hover{background:#15803d}
  .btn-danger{background:#dc2626}.btn-danger:hover{background:#b91c1c}
  .input{width:100%;padding:12px;border:1px solid #475569;border-radius:8px;background:#0f172a;color:#fff;margin-bottom:12px;font-size:16px}
  .msg{padding:10px;border-radius:8px;margin-bottom:16px}
  .msg-success{background:#166534;color:#dcfce7}
  .msg-error{background:#991b1b;color:#fee2e2}
  .balance{font-size:36px;font-weight:bold;color:#4ade80;text-align:center}
  .nav{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px;background:#1e293b;padding:10px;border-radius:8px}
  .nav a{color:#94a3b8;text-decoration:none;font-size:14px;padding:5px 10px;border-radius:5px}
  .nav a:hover{background:#334155;color:#fff}
  .task{border:1px solid #334155;padding:15px;border-radius:8px;margin-bottom:10px;background:#0f172a}
  .tag{font-size:12px;background:#334155;padding:2px 6px;border-radius:4px;margin-left:5px}
  .row{display:flex;gap:10px}.row>*{flex:1}
</style>
</head>
<body>
<div class="container">
{% if session.user_id or session.is_admin %}
<div class="nav">
  {% if session.is_admin %}
    <a href="{{ url_for('admin_panel') }}">⚙️ Админ Панель</a>
    <a href="{{ url_for('logout') }}">🚪 Чыгуу</a>
  {% else %}
    <a href="{{ url_for('dashboard') }}">🏠 Башкы</a>
    <a href="{{ url_for('tasks') }}">🎮 Тапшырмалар & Оюндар</a>
    <a href="{{ url_for('withdraw') }}">💸 Чыгаруу</a>
    <a href="{{ url_for('logout') }}">🚪 Чыгуу</a>
  {% endif %}
</div>
{% endif %}
{% with msgs = get_flashed_messages(with_categories=true) %}
  {% for cat, m in msgs %}<div class="msg msg-{{ cat }}">{{ m }}</div>{% endfor %}
{% endwith %}
{{ body|safe }}
</div>
</body>
</html>
"""

# ═══════════════════════════════════════════
#  БЕТТЕРДИН КОДУ
# ═══════════════════════════════════════════
LOGIN_BODY = """
<div class="card">
  <h2>Кирүү</h2>
  <form method="POST">
    <input class="input" type="tel" name="phone" placeholder="+996 700 123 456" required>
    <button class="btn" type="submit">Кирүү</button>
  </form>
  <p style="text-align:center;margin-top:15px;font-size:14px">
    Аккаунтуңуз жокпу? <a href="{{ url_for('register') }}" style="color:#38bdf8">Каттоо</a><br><br>
    <a href="{{ url_for('admin_login') }}" style="color:#94a3b8;font-size:12px">Админ катары кирүү</a>
  </p>
</div>
"""

REGISTER_BODY = """
<div class="card">
  <h2>Каттоо</h2>
  <form method="POST">
    <input class="input" type="tel" name="phone" placeholder="+996 700 123 456" required>
    <input class="input" type="text" name="name" placeholder="Атыңыз">
    <input type="hidden" name="ref" value="{{ ref }}">
    <button class="btn" type="submit">Каттоо</button>
  </form>
</div>
"""

DASHBOARD_BODY = """
<div class="card">
  <h2>Салам, {{ user.name or user.phone }}!</h2>
  <div class="balance">{{ '%.2f'|format(user.balance) }} сом</div>
  {% if daily_bonus_given %}
    <p style="color:#4ade80;text-align:center;margin-top:10px">🎁 Күнүмдүк бонус: +{{ daily_bonus }} сом!</p>
  {% endif %}
</div>

<div class="card">
  <h3>🎁 Реферал шилтеме</h3>
  <p style="font-size:14px;margin-bottom:10px">Ар бир дос үчүн 50 сом аласыз.</p>
  <input class="input" type="text" value="{{ ref_link }}" readonly>
</div>

<div class="card">
  <h3>📊 Акыркы транзакциялар</h3>
  <table style="width:100%;font-size:13px;text-align:left">
    <tr><th>Түрү</th><th>Сумма</th></tr>
    {% for t in transactions %}
    <tr>
      <td>{{ t.note }}</td>
      <td style="color:{{ '#4ade80' if t.amount >= 0 else '#f87171' }}">{{ t.amount }}</td>
    </tr>
    {% endfor %}
  </table>
</div>
"""

TASKS_BODY = """
<div class="card">
  <h2>🎮 Оюндар & Тапшырмалар</h2>
  <p style="font-size:14px;color:#94a3b8;margin-bottom:15px">Ар бир тапшырманы чексиз аткарсаңыз болот!</p>
  
  {% for t in tasks %}
  <div class="task">
    <h3>{{ t.title }} <span class="tag">{{ t.task_type }}</span></h3>
    <p style="font-size:14px;color:#cbd5e1;margin-bottom:10px">{{ t.description }}</p>
    <div class="row">
      <div style="font-weight:bold;color:#4ade80;display:flex;align-items:center">+{{ t.reward }} сом</div>
      <form method="POST" action="{{ url_for('do_task', task_id=t.id) }}">
        <button class="btn btn-success" type="submit">
          {% if t.task_type == 'game' %}Ойноо 🎲
          {% elif t.task_type == 'video' %}Көрүү ▶️
          {% else %}Аткаруу ✅{% endif %}
        </button>
      </form>
    </div>
  </div>
  {% endfor %}
</div>
"""

WITHDRAW_BODY = """
<div class="card">
  <h2>💸 Акча чыгаруу</h2>
  <p>Балансыңыз: <b style="color:#4ade80">{{ '%.2f'|format(user.balance) }} сом</b></p>
  <p style="font-size:13px;color:#94a3b8;margin-bottom:15px">Минимум: {{ min_withdraw }} сом</p>
  
  <form method="POST">
    <select class="input" name="method">
      <option value="MegaCom">MegaCom</option>
      <option value="O!">O! Деньги</option>
      <option value="Beeline">Beeline</option>
      <option value="MBank">MBank (Visa)</option>
      <option value="Visa">Башка Visa картасы</option>
    </select>
    <input class="input" type="tel" name="phone" placeholder="Телефон же Карта номери" required>
    <input class="input" type="number" name="amount" min="{{ min_withdraw }}" placeholder="Сумма (сом)" required>
    <button class="btn" type="submit">Сурам жөнөтүү</button>
  </form>
</div>

<div class="card">
  <h3>Тарых</h3>
  {% for w in withdrawals %}
  <div style="border-bottom:1px solid #334155;padding:10px 0;font-size:14px">
    {{ w.amount }} сом ({{ w.method }}) - <b>{{ w.status }}</b>
  </div>
  {% endfor %}
</div>
"""

ADMIN_LOGIN_BODY = """
<div class="card">
  <h2>Админ Панель</h2>
  <form method="POST">
    <input class="input" type="password" name="password" placeholder="Сырсөздү жазыңыз" required>
    <button class="btn btn-danger" type="submit">Кирүү</button>
  </form>
</div>
"""

ADMIN_PANEL_BODY = """
<div class="card">
  <h2>⚙️ Админ Статистикасы</h2>
  <p>Сиздин таза пайдаңыз (Пайыздардан): <b style="color:#4ade80;font-size:20px">{{ '%.2f'|format(admin_balance) }} сом</b></p>
  <p style="font-size:13px;color:#94a3b8">Ар бир колдонуучунун тапкан акчасынан {{ commission_pct }}% сизге түшөт.</p>
</div>

<div class="card">
  <h2>Акча чыгаруу сурамдары</h2>
  {% for w in withdrawals %}
  <div class="task">
    <p><b>{{ w.user_phone }}</b> талап кылат: {{ w.amount }} сом</p>
    <p style="font-size:13px;color:#94a3b8">Ыкмасы: {{ w.method }} | Номер: {{ w.phone }}</p>
    <div class="row">
      <form method="POST" action="{{ url_for('admin_action', wid=w.id, action='approve') }}">
        <button class="btn btn-success" type="submit">✓ Тастыктоо</button>
      </form>
      <form method="POST" action="{{ url_for('admin_action', wid=w.id, action='reject') }}">
        <button class="btn btn-danger" type="submit">✗ Четке кагуу</button>
      </form>
    </div>
  </div>
  {% else %}
  <p>Күтүүдөгү сурамдар жок.</p>
  {% endfor %}
</div>
"""

# ═══════════════════════════════════════════
#  РОУТТАР (МАРШРУТТАР)
# ═══════════════════════════════════════════
@app.route('/')
def index():
    if session.get('is_admin'): return redirect(url_for('admin_panel'))
    return redirect(url_for('dashboard') if 'user_id' in session else url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = normalize_phone(request.form.get('phone', ''))
        row = get_db().execute('SELECT * FROM users WHERE phone=?', (phone,)).fetchone()
        if row:
            session['user_id'] = row['id']
            return redirect(url_for('dashboard'))
        flash('Колдонуучу табылган жок', 'error')
    return render(LOGIN_BODY)

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == app.config['ADMIN_PASSWORD']:
            session['is_admin'] = True
            return redirect(url_for('admin_panel'))
        flash('Сырсөз туура эмес!', 'error')
    return render(ADMIN_LOGIN_BODY)

@app.route('/register', methods=['GET', 'POST'])
def register():
    ref = request.args.get('ref', '')
    if request.method == 'POST':
        phone = normalize_phone(request.form.get('phone', ''))
        name = request.form.get('name', '')
        ref = request.form.get('ref', '')
        db = get_db()
        
        if db.execute('SELECT 1 FROM users WHERE phone=?', (phone,)).fetchone():
            flash('Бул номер катталган', 'error')
            return redirect(url_for('login'))

        user_id = str(uuid.uuid4())
        referred_by = None
        if ref:
            r = db.execute('SELECT id FROM users WHERE referral_code=?', (ref,)).fetchone()
            if r: referred_by = r['id']

        db.execute("INSERT INTO users (id,phone,name,referral_code,referred_by,balance,created_at) VALUES (?,?,?,?,?,0,?)",
                   (user_id, phone, name, user_id[:8], referred_by, now_iso()))
        
        if referred_by:
            # Досуна 50 сом
            db.execute("UPDATE users SET balance=balance+50 WHERE id=?", (referred_by,))
            db.execute("INSERT INTO transactions (user_id,type,amount,note,created_at) VALUES (?,?,?,?,?)",
                       (referred_by, 'ref_bonus', 50, 'Дос чакырганы үчүн', now_iso()))
            # Жаңыга 25 сом
            db.execute("UPDATE users SET balance=balance+25 WHERE id=?", (user_id,))
            db.execute("INSERT INTO transactions (user_id,type,amount,note,created_at) VALUES (?,?,?,?,?)",
                       (user_id, 'welcome', 25, 'Кош келиңиз', now_iso()))

        db.commit()
        session['user_id'] = user_id
        return redirect(url_for('dashboard'))
    return render(REGISTER_BODY, ref=ref)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    
    # Күнүмдүк бонусту текшерүү (Auto Accrual)
    today_str = datetime.utcnow().strftime('%Y-%m-%d')
    bonus_given = False
    if user['last_bonus_date'] != today_str:
        db.execute("UPDATE users SET balance=balance+?, last_bonus_date=? WHERE id=?", 
                   (DAILY_BONUS, today_str, user['id']))
        db.execute("INSERT INTO transactions (user_id,type,amount,note,created_at) VALUES (?,?,?,?,?)",
                   (user['id'], 'daily_bonus', DAILY_BONUS, 'Күнүмдүк бонус', now_iso()))
        db.commit()
        user = db.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone()
        bonus_given = True

    txs = db.execute('SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 10', (user['id'],)).fetchall()
    ref_link = f"{request.host_url}r/{user['referral_code']}"
    return render(DASHBOARD_BODY, user=user, transactions=txs, ref_link=ref_link, 
                  daily_bonus_given=bonus_given, daily_bonus=DAILY_BONUS)

@app.route('/tasks')
@login_required
def tasks():
    db = get_db()
    tasks_list = db.execute("SELECT * FROM tasks WHERE active=1").fetchall()
    return render(TASKS_BODY, tasks=tasks_list)

@app.route('/tasks/<int:task_id>/do', methods=['POST'])
@login_required
def do_task(task_id):
    db = get_db()
    task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    if not task:
        return redirect(url_for('tasks'))

    reward = task['reward']
    admin_cut = reward * COMMISSION_RATE # Сиздин пайызыңыз (20%)
    user_cut = reward - admin_cut        # Колдонуучуга тийүүчү сумма (80%)

    # Колдонуучуга акча кошуу
    db.execute("UPDATE users SET balance=balance+? WHERE id=?", (user_cut, session['user_id']))
    db.execute("INSERT INTO transactions (user_id,type,amount,note,created_at) VALUES (?,?,?,?,?)",
               (session['user_id'], 'task_reward', user_cut, task['title'], now_iso()))
    
    # Админге (сизге) пайыз кошуу (Бул жерде бардык админдердин жалпы балансына кошулат)
    # Жөнөкөйлүк үчүн атайын "admin" деген колдонуучуга жазабыз, же биринчи колдонуучуга
    db.execute("UPDATE users SET admin_balance=admin_balance+? WHERE phone='ADMIN'", (admin_cut,))
    # Эгер 'ADMIN' деген жок болсо, аны түзөбүз (биринчи иштегенде)
    if db.total_changes == 0:
        db.execute("INSERT OR IGNORE INTO users (id, phone, admin_balance, created_at) VALUES ('admin_id', 'ADMIN', ?, ?)",
                   (admin_cut, now_iso()))

    db.commit()
    flash(f'Ийгиликтүү! Сиз {user_cut:.2f} сом алдыңыз.', 'success')
    return redirect(url_for('tasks'))

@app.route('/withdraw', methods=['GET', 'POST'])
@login_required
def withdraw():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()

    if request.method == 'POST':
        amount = float(request.form.get('amount', 0))
        phone = request.form.get('phone', '')
        method = request.form.get('method', 'MegaCom')

        if amount < MIN_WITHDRAW:
            flash(f'Минимум {MIN_WITHDRAW} сом', 'error')
        elif amount > user['balance']:
            flash('Балансыңыз жетишсиз', 'error')
        else:
            db.execute('UPDATE users SET balance=balance-? WHERE id=?', (amount, user['id']))
            db.execute('INSERT INTO withdrawals (user_id,phone,method,amount,created_at) VALUES (?,?,?,?,?)',
                       (user['id'], phone, method, amount, now_iso()))
            db.execute('INSERT INTO transactions (user_id,type,amount,note,created_at) VALUES (?,?,?,?,?)',
                       (user['id'], 'withdraw_hold', -amount, f'{method} аркылуу чыгаруу', now_iso()))
            db.commit()
            flash('Сурам кабыл алынды', 'success')
            return redirect(url_for('dashboard'))

    wds = db.execute('SELECT * FROM withdrawals WHERE user_id=? ORDER BY id DESC', (user['id'],)).fetchall()
    return render(WITHDRAW_BODY, user=user, withdrawals=wds, min_withdraw=MIN_WITHDRAW)

@app.route('/admin')
@admin_required
def admin_panel():
    db = get_db()
    admin_data = db.execute("SELECT admin_balance FROM users WHERE phone='ADMIN'").fetchone()
    admin_bal = admin_data['admin_balance'] if admin_data else 0.0
    
    pending = db.execute("""
        SELECT w.*, u.phone AS user_phone FROM withdrawals w 
        JOIN users u ON u.id=w.user_id WHERE w.status='pending'
    """).fetchall()
    
    return render(ADMIN_PANEL_BODY, admin_balance=admin_bal, commission_pct=int(COMMISSION_RATE*100), withdrawals=pending)

@app.route('/admin/action/<int:wid>/<action>', methods=['POST'])
@admin_required
def admin_action(wid, action):
    db = get_db()
    w = db.execute('SELECT * FROM withdrawals WHERE id=?', (wid,)).fetchone()
    if w and w['status'] == 'pending':
        if action == 'approve':
            db.execute("UPDATE withdrawals SET status='completed', processed_at=? WHERE id=?", (now_iso(), wid))
        else:
            db.execute("UPDATE withdrawals SET status='rejected', processed_at=? WHERE id=?", (now_iso(), wid))
            # Акчаны кайтаруу
            db.execute("UPDATE users SET balance=balance+? WHERE id=?", (w['amount'], w['user_id']))
            db.execute('INSERT INTO transactions (user_id,type,amount,note,created_at) VALUES (?,?,?,?,?)',
                       (w['user_id'], 'refund', w['amount'], 'Четке кагылды, кайтарылды', now_iso()))
        db.commit()
    return redirect(url_for('admin_panel'))

init_db()
if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
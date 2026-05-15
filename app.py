
from flask import Flask, request, redirect, url_for, session, g, render_template_string
import sqlite3, os, json, datetime, traceback
from functools import wraps

APP_VERSION = "SD Invoice Python V1.2 Single File Render Fix"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "sd_invoice_python.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "sd-invoice-python-secret")

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    conn = g.pop("db", None)
    if conn:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS clients(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT, email TEXT, user_id TEXT, password TEXT,
        gstin TEXT, pan TEXT, state TEXT, state_code TEXT, phone TEXT,
        address TEXT, bank_name TEXT, bank_account TEXT, bank_ifsc TEXT,
        payment_terms TEXT, footer_text TEXT DEFAULT 'This invoice generated from SD Invoice portal.',
        footer_enabled INTEGER DEFAULT 1, status TEXT DEFAULT 'Active'
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS branches(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER, name TEXT, prefix TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS customers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER, name TEXT, gstin TEXT, pan TEXT, phone TEXT, email TEXT,
        state TEXT, state_code TEXT, address TEXT,
        shipping_name TEXT, shipping_address TEXT, shipping_state TEXT, shipping_state_code TEXT,
        due_days INTEGER DEFAULT 15
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER, name TEXT, hsn TEXT, price REAL DEFAULT 0,
        gst REAL DEFAULT 0, unit TEXT DEFAULT 'Nos'
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS rate_contracts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER, customer_id INTEGER, product_id INTEGER,
        customer_name TEXT, item_name TEXT, hsn TEXT, uom TEXT,
        approved_rate REAL DEFAULT 0, gst REAL DEFAULT 0,
        valid_from TEXT, valid_to TEXT, status TEXT DEFAULT 'Active',
        remarks TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS invoices(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER, branch_id INTEGER, invoice_type TEXT, invoice_no TEXT,
        invoice_date TEXT, due_date TEXT, customer_id INTEGER, customer_name TEXT,
        total REAL DEFAULT 0, status TEXT DEFAULT 'Unpaid', invoice_json TEXT
    )""")

    c.execute("SELECT COUNT(*) FROM clients")
    if c.fetchone()[0] == 0:
        c.execute("""INSERT INTO clients(company_name,email,user_id,password,gstin,pan,state,state_code,phone,address,payment_terms)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                  ("Demo Client Company","demo@sdinvoice.com","admin","1234","24ABCDE1234F1Z5","ABCDE1234F","Gujarat","24","9999999999","Ahmedabad, Gujarat","As per agreement"))
        client_id = c.lastrowid
        c.execute("INSERT INTO branches(client_id,name,prefix) VALUES(?,?,?)", (client_id, "Main Branch", "INV"))
    conn.commit()
    conn.close()

# Important for Render/Gunicorn
init_db()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("login_type"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def current_client_id():
    if session.get("login_type") == "superadmin":
        row = db().execute("SELECT id FROM clients ORDER BY id LIMIT 1").fetchone()
        return row["id"] if row else None
    return session.get("client_id")

def gst_state_code(gstin):
    gstin = (gstin or "").strip()
    return gstin[:2] if len(gstin) >= 2 and gstin[:2].isdigit() else ""

def safe_float(v, default=0):
    try:
        return float(v or default)
    except Exception:
        return float(default)

LOGIN_HTML = """
<!DOCTYPE html><html><head><title>{{ version }}</title>
<style>
body{font-family:Arial;background:#123b63;margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center}
.card{background:#fff;border-radius:18px;padding:32px;width:640px;box-shadow:0 8px 30px #0003}
input,select{width:100%;padding:12px;margin:8px 0;border:1px solid #cbd5e1;border-radius:8px}
button{background:#0f3157;color:white;border:0;padding:12px 18px;border-radius:8px;font-weight:bold}
.err{color:#b91c1c;font-weight:bold}
</style></head><body><div class="card">
<h1>{{ version }}</h1>
<p><b>Super Admin:</b> superadmin / admin123</p>
<p><b>Demo Client:</b> demo@sdinvoice.com / admin / 1234</p>
{% if error %}<p class="err">{{ error }}</p>{% endif %}
<form method="post" action="/login">
<label>Login Type</label><select name="login_type"><option value="superadmin">Super Admin</option><option value="client">Client</option></select>
<label>Email</label><input name="email" placeholder="Client email">
<label>User ID</label><input name="user_id" value="superadmin">
<label>Password</label><input name="password" type="password" value="admin123">
<button>Login</button>
</form></div></body></html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html><html><head><title>{{ version }}</title>
<style>
body{font-family:Arial;margin:0;background:#eef4fb;color:#00112b}
header{background:#123b63;color:white;padding:22px;display:flex;justify-content:space-between}
section{background:white;margin:16px;padding:20px;border-radius:14px;border:1px solid #cbd5e1}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
input,select{padding:10px;border:1px solid #cbd5e1;border-radius:8px}
button{background:#16813a;color:white;border:0;border-radius:8px;padding:11px 16px;font-weight:bold}
table{width:100%;border-collapse:collapse;margin-top:14px}th,td{border:1px solid #cbd5e1;padding:9px}th{background:#e8f0fb}
a{color:#0f3157;font-weight:bold}
</style>
<script>
function fillProduct(){
 const sel=document.getElementById("roc_product"); const opt=sel.options[sel.selectedIndex];
 document.getElementById("roc_item").value=opt.dataset.name||"";
 document.getElementById("roc_hsn").value=opt.dataset.hsn||"";
 document.getElementById("roc_rate").value=opt.dataset.price||"";
 document.getElementById("roc_gst").value=opt.dataset.gst||"";
 document.getElementById("roc_uom").value=opt.dataset.unit||"Nos";
}
function fillInvoiceProduct(){
 const sel=document.getElementById("inv_product"); const opt=sel.options[sel.selectedIndex];
 document.getElementById("inv_rate").value=opt.dataset.price||"";
 document.getElementById("inv_gst").value=opt.dataset.gst||"";
}
</script></head><body>
<header><h1>{{ version }}</h1><div><a style="color:white" href="/logout">Logout</a></div></header>
<section><h2>Welcome, {{ user }} | {{ login_type }}</h2><p><b>Current Client:</b> {{ client.company_name }} | {{ client.email }}</p></section>

<section><h2>Customer Master</h2>
<form method="post" action="/customer/save" class="grid">
<input name="name" placeholder="Customer Name" required><input name="gstin" placeholder="GSTIN"><input name="pan" placeholder="PAN"><input name="phone" placeholder="Phone">
<input name="email" placeholder="Email"><input name="state" placeholder="State"><input name="state_code" placeholder="State Code"><input name="due_days" placeholder="Due Days" value="15">
<input name="address" placeholder="Bill To Address"><input name="shipping_name" placeholder="Ship To Name"><input name="shipping_address" placeholder="Ship To Address"><input name="shipping_state" placeholder="Ship To State">
<input name="shipping_state_code" placeholder="Ship To State Code"><button>Save Customer</button>
</form></section>

<section><h2>Product Master</h2>
<form method="post" action="/product/save" class="grid">
<input name="name" placeholder="Product / Service" required><input name="hsn" placeholder="HSN/SAC"><input name="price" placeholder="Rate" type="number" step="0.01"><input name="gst" placeholder="GST %" type="number" step="0.01">
<input name="unit" placeholder="Unit" value="Nos"><button>Save Product</button>
</form></section>

<section><h2>Rate Contract</h2>
<form method="post" action="/roc/save" class="grid">
<select name="customer_id" required><option value="">Select Customer/Vendor</option>{% for c in customers %}<option value="{{c.id}}">{{c.name}}</option>{% endfor %}</select>
<select name="product_id" id="roc_product" onchange="fillProduct()"><option value="">Manual / Select Product</option>{% for p in products %}<option value="{{p.id}}" data-name="{{p.name}}" data-hsn="{{p.hsn}}" data-price="{{p.price}}" data-gst="{{p.gst}}" data-unit="{{p.unit}}">{{p.name}}</option>{% endfor %}</select>
<input name="item_name" id="roc_item" placeholder="Item / Service Name"><input name="hsn" id="roc_hsn" placeholder="HSN/SAC"><input name="uom" id="roc_uom" value="Nos">
<input name="approved_rate" id="roc_rate" placeholder="Approved Rate" type="number" step="0.01"><input name="gst" id="roc_gst" placeholder="GST %" type="number" step="0.01"><input name="valid_from" type="date"><input name="valid_to" type="date">
<input name="status" value="Active"><input name="remarks" placeholder="Remarks"><button>Save Rate Contract</button>
</form></section>

<section><h2>Create Invoice</h2>
<form method="post" action="/invoice/save" class="grid">
<select name="invoice_type"><option>Tax Invoice</option><option>Proforma Invoice</option><option>Quotation</option></select>
<select name="branch_id">{% for b in branches %}<option value="{{b.id}}">{{b.name}}</option>{% endfor %}</select>
<input name="invoice_no" placeholder="Invoice No auto if blank"><input name="invoice_date" type="date"><input name="due_date" type="date">
<select name="customer_id" required><option value="">Select Customer</option>{% for c in customers %}<option value="{{c.id}}">{{c.name}}</option>{% endfor %}</select>
<select name="product_id" id="inv_product" onchange="fillInvoiceProduct()" required><option value="">Select Product</option>{% for p in products %}<option value="{{p.id}}" data-price="{{p.price}}" data-gst="{{p.gst}}">{{p.name}}</option>{% endfor %}</select>
<input name="qty" value="1" type="number"><input name="rate" id="inv_rate" placeholder="Rate" type="number" step="0.01"><input name="gst" id="inv_gst" placeholder="GST %" type="number" step="0.01"><button>Save Invoice</button>
</form></section>

<section><h2>Invoices</h2><table><tr><th>No</th><th>Date</th><th>Customer</th><th>Total</th><th>Status</th><th>Action</th></tr>
{% for i in invoices %}<tr><td>{{i.invoice_no}}</td><td>{{i.invoice_date}}</td><td>{{i.customer_name}}</td><td>₹{{"%.2f"|format(i.total)}}</td><td>{{i.status}}</td><td><a href="/invoice/{{i.id}}" target="_blank">View/Print</a></td></tr>{% endfor %}
</table></section>

<section><h2>Saved Masters</h2><table><tr><th>Customers</th><td>{{customers|length}}</td><th>Products</th><td>{{products|length}}</td><th>ROC</th><td>{{rocs|length}}</td></tr></table></section>
</body></html>
"""

INVOICE_HTML = """
<!DOCTYPE html><html><head><title>{{ inv.invoice_no }}</title>
<style>
body{font-family:Arial;background:#eef2f7;margin:0;padding:24px;color:#111}.toolbar{text-align:right;max-width:1000px;margin:auto;margin-bottom:12px}
button{background:#0f3157;color:#fff;border:0;border-radius:8px;padding:10px 15px}.wrap{background:#fff;max-width:1000px;margin:auto;border-radius:14px;padding:28px;box-shadow:0 8px 24px #0002}
.top{display:flex;justify-content:space-between;border-bottom:2px solid #0f3157;padding-bottom:16px}h1,h2{color:#0f3157}.boxes{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:18px}
.box{background:#f8fafc;border:1px solid #cbd5e1;border-radius:10px;padding:14px}table{width:100%;border-collapse:collapse;margin-top:18px}th,td{border:1px solid #cbd5e1;padding:10px}th{background:#0f3157;color:#fff}.r{text-align:right}
.total{text-align:right;font-size:22px;font-weight:bold;margin-top:18px}.footer{text-align:center;color:#64748b;font-size:12px;border-top:1px solid #cbd5e1;margin-top:24px;padding-top:10px}
@media print{body{background:white;padding:0}.toolbar{display:none}.wrap{box-shadow:none}}
</style></head><body><div class="toolbar"><button onclick="window.print()">Print / Save PDF</button></div><div class="wrap">
<div class="top"><div><h1>{{ client.company_name }}</h1><p><b>GSTIN:</b> {{ client.gstin or '-' }} | <b>PAN:</b> {{ client.pan or '-' }}</p><p>{{ client.address or '-' }}</p></div>
<div><h2>{{ inv.invoice_type }}</h2><p><b>No:</b> {{ inv.invoice_no }}</p><p><b>Date:</b> {{ inv.invoice_date }}</p><p><b>Due:</b> {{ inv.due_date }}</p></div></div>
<div class="boxes"><div class="box"><h3>Bill To</h3><b>{{ data.customer_name }}</b><p>{{ data.bill_to_address or '-' }}</p></div><div class="box"><h3>Ship To</h3><b>{{ data.ship_to_name or data.customer_name }}</b><p>{{ data.ship_to_address or data.bill_to_address or '-' }}</p></div></div>
<table><tr><th>#</th><th>Item</th><th>HSN</th><th>Qty</th><th>Rate</th><th>GST</th><th>Total</th></tr>
{% for it in data["items"] %}<tr><td>{{loop.index}}</td><td>{{it.name}}</td><td>{{it.hsn}}</td><td class="r">{{it.qty}}</td><td class="r">₹{{"%.2f"|format(it.rate)}}</td><td class="r">{{it.gst}}%</td><td class="r">₹{{"%.2f"|format(it.total)}}</td></tr>{% endfor %}
</table><div class="total">Grand Total: ₹{{"%.2f"|format(inv.total)}}</div>
{% if client.footer_enabled %}<div class="footer">{{ client.footer_text }}</div>{% endif %}
</div></body></html>
"""

ERROR_HTML = """
<h1>Application Error</h1>
<p style='color:red;font-weight:bold'>{{ error }}</p>
<pre>{{ trace }}</pre>
<a href='/'>Back to login</a>
"""

@app.errorhandler(Exception)
def handle_error(e):
    trace = traceback.format_exc()
    print(trace, flush=True)
    return render_template_string(ERROR_HTML, error=str(e), trace=trace), 500

@app.route("/")
def login():
    return render_template_string(LOGIN_HTML, version=APP_VERSION)

@app.post("/login")
def do_login():
    login_type = request.form.get("login_type")
    email = request.form.get("email","").strip()
    user_id = request.form.get("user_id","").strip()
    password = request.form.get("password","").strip()

    if login_type == "superadmin":
        if user_id == "superadmin" and password == "admin123":
            session.clear(); session["login_type"] = "superadmin"; session["user"] = "superadmin"
            return redirect(url_for("dashboard"))
        return render_template_string(LOGIN_HTML, version=APP_VERSION, error="Invalid Super Admin login")

    client = db().execute("SELECT * FROM clients WHERE email=? AND user_id=? AND password=?", (email, user_id, password)).fetchone()
    if client:
        session.clear(); session["login_type"] = "client"; session["client_id"] = client["id"]; session["user"] = user_id
        return redirect(url_for("dashboard"))

    return render_template_string(LOGIN_HTML, version=APP_VERSION, error="Invalid Client login")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    cid = current_client_id()
    if not cid:
        return redirect(url_for("login"))
    client = db().execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
    customers = db().execute("SELECT * FROM customers WHERE client_id=? ORDER BY id DESC", (cid,)).fetchall()
    products = db().execute("SELECT * FROM products WHERE client_id=? ORDER BY id DESC", (cid,)).fetchall()
    branches = db().execute("SELECT * FROM branches WHERE client_id=? ORDER BY id", (cid,)).fetchall()
    rocs = db().execute("SELECT * FROM rate_contracts WHERE client_id=? ORDER BY id DESC", (cid,)).fetchall()
    invoices = db().execute("SELECT * FROM invoices WHERE client_id=? ORDER BY id DESC", (cid,)).fetchall()
    return render_template_string(DASHBOARD_HTML, version=APP_VERSION, client=client, customers=customers, products=products, branches=branches, rocs=rocs, invoices=invoices, login_type=session.get("login_type"), user=session.get("user"))

@app.post("/customer/save")
@login_required
def save_customer():
    cid = current_client_id()
    f = request.form
    state_code = f.get("state_code") or gst_state_code(f.get("gstin"))
    db().execute("""INSERT INTO customers(client_id,name,gstin,pan,phone,email,state,state_code,address,shipping_name,shipping_address,shipping_state,shipping_state_code,due_days)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (cid, f.get("name"), f.get("gstin"), f.get("pan"), f.get("phone"), f.get("email"), f.get("state"), state_code,
                  f.get("address"), f.get("shipping_name") or f.get("name"), f.get("shipping_address") or f.get("address"),
                  f.get("shipping_state") or f.get("state"), f.get("shipping_state_code") or state_code, f.get("due_days") or 15))
    db().commit()
    return redirect(url_for("dashboard"))

@app.post("/product/save")
@login_required
def save_product():
    cid = current_client_id()
    f = request.form
    db().execute("INSERT INTO products(client_id,name,hsn,price,gst,unit) VALUES(?,?,?,?,?,?)",
                 (cid, f.get("name"), f.get("hsn"), safe_float(f.get("price")), safe_float(f.get("gst")), f.get("unit") or "Nos"))
    db().commit()
    return redirect(url_for("dashboard"))

@app.post("/roc/save")
@login_required
def save_roc():
    cid = current_client_id()
    f = request.form
    customer = db().execute("SELECT * FROM customers WHERE id=? AND client_id=?", (f.get("customer_id"), cid)).fetchone()
    product = db().execute("SELECT * FROM products WHERE id=? AND client_id=?", (f.get("product_id"), cid)).fetchone()
    db().execute("""INSERT INTO rate_contracts(client_id,customer_id,product_id,customer_name,item_name,hsn,uom,approved_rate,gst,valid_from,valid_to,status,remarks)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (cid, f.get("customer_id"), f.get("product_id"), customer["name"] if customer else "",
                  f.get("item_name") or (product["name"] if product else ""), f.get("hsn") or (product["hsn"] if product else ""),
                  f.get("uom") or (product["unit"] if product else "Nos"), safe_float(f.get("approved_rate")),
                  safe_float(f.get("gst") or (product["gst"] if product else 0)), f.get("valid_from"), f.get("valid_to"), f.get("status") or "Active", f.get("remarks")))
    db().commit()
    return redirect(url_for("dashboard"))

@app.post("/invoice/save")
@login_required
def save_invoice():
    cid = current_client_id()
    f = request.form
    customer = db().execute("SELECT * FROM customers WHERE id=? AND client_id=?", (f.get("customer_id"), cid)).fetchone()
    product = db().execute("SELECT * FROM products WHERE id=? AND client_id=?", (f.get("product_id"), cid)).fetchone()
    branch = db().execute("SELECT * FROM branches WHERE id=? AND client_id=?", (f.get("branch_id"), cid)).fetchone()

    if not customer:
        raise Exception("Customer not found. Please save/select customer.")
    if not product:
        raise Exception("Product not found. Please save/select product.")
    if not branch:
        raise Exception("Branch not found.")

    qty = safe_float(f.get("qty"), 1)
    rate = safe_float(f.get("rate") or product["price"])
    gst = safe_float(f.get("gst") or product["gst"])
    taxable = qty * rate
    gst_amt = taxable * gst / 100
    total = taxable + gst_amt

    invoice_no = f.get("invoice_no") or f"{branch['prefix']}/{datetime.datetime.now().year}-{int(datetime.datetime.now().timestamp())}"
    invoice_date = f.get("invoice_date") or datetime.date.today().isoformat()
    due_date = f.get("due_date") or invoice_date

    invoice_json = {"customer_id": customer["id"], "customer_name": customer["name"], "bill_to_address": customer["address"],
        "ship_to_name": customer["shipping_name"] or customer["name"], "ship_to_address": customer["shipping_address"] or customer["address"],
        "items": [{"name": product["name"], "hsn": product["hsn"], "qty": qty, "rate": rate, "gst": gst, "taxable": taxable, "gst_amount": gst_amt, "total": total}]}

    db().execute("""INSERT INTO invoices(client_id,branch_id,invoice_type,invoice_no,invoice_date,due_date,customer_id,customer_name,total,status,invoice_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                 (cid, f.get("branch_id"), f.get("invoice_type") or "Tax Invoice", invoice_no, invoice_date, due_date,
                  customer["id"], customer["name"], total, "Unpaid", json.dumps(invoice_json)))
    db().commit()
    return redirect(url_for("dashboard"))

@app.route("/invoice/<int:invoice_id>")
@login_required
def view_invoice(invoice_id):
    inv = db().execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        raise Exception("Invoice not found")
    client = db().execute("SELECT * FROM clients WHERE id=?", (inv["client_id"],)).fetchone()
    branch = db().execute("SELECT * FROM branches WHERE id=?", (inv["branch_id"],)).fetchone()
    data = json.loads(inv["invoice_json"] or "{}")
    return render_template_string(INVOICE_HTML, inv=inv, client=client, branch=branch, data=data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)

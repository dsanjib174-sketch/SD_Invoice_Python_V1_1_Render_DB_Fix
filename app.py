
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, g, send_file
import sqlite3, os, json, datetime
from functools import wraps

APP_VERSION = "SD Invoice Python V1"
DB_PATH = os.path.join(os.path.dirname(__file__), "sd_invoice_python.db")

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
        payment_terms TEXT, logo_data TEXT, signature_name TEXT,
        footer_text TEXT DEFAULT 'This invoice generated from SD Invoice portal.',
        footer_enabled INTEGER DEFAULT 1,
        status TEXT DEFAULT 'Active'
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

@app.route("/")
def login():
    return render_template("login.html", version=APP_VERSION)

@app.post("/login")
def do_login():
    login_type = request.form.get("login_type")
    email = request.form.get("email","").strip()
    user_id = request.form.get("user_id","").strip()
    password = request.form.get("password","").strip()

    if login_type == "superadmin":
        if user_id == "superadmin" and password == "admin123":
            session.clear()
            session["login_type"] = "superadmin"
            session["user"] = "superadmin"
            return redirect(url_for("dashboard"))
        return render_template("login.html", version=APP_VERSION, error="Invalid Super Admin login")

    client = db().execute("SELECT * FROM clients WHERE email=? AND user_id=? AND password=?", (email, user_id, password)).fetchone()
    if client:
        session.clear()
        session["login_type"] = "client"
        session["client_id"] = client["id"]
        session["user"] = user_id
        return redirect(url_for("dashboard"))

    return render_template("login.html", version=APP_VERSION, error="Invalid Client login")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    cid = current_client_id()
    client = db().execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
    customers = db().execute("SELECT * FROM customers WHERE client_id=? ORDER BY id DESC", (cid,)).fetchall()
    products = db().execute("SELECT * FROM products WHERE client_id=? ORDER BY id DESC", (cid,)).fetchall()
    branches = db().execute("SELECT * FROM branches WHERE client_id=? ORDER BY id", (cid,)).fetchall()
    rocs = db().execute("SELECT * FROM rate_contracts WHERE client_id=? ORDER BY id DESC", (cid,)).fetchall()
    invoices = db().execute("SELECT * FROM invoices WHERE client_id=? ORDER BY id DESC", (cid,)).fetchall()
    return render_template("dashboard.html", version=APP_VERSION, client=client, customers=customers, products=products, branches=branches, rocs=rocs, invoices=invoices, login_type=session.get("login_type"))

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
                 (cid, f.get("name"), f.get("hsn"), float(f.get("price") or 0), float(f.get("gst") or 0), f.get("unit") or "Nos"))
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
                  f.get("uom") or (product["unit"] if product else "Nos"), float(f.get("approved_rate") or 0),
                  float(f.get("gst") or (product["gst"] if product else 0)), f.get("valid_from"), f.get("valid_to"), f.get("status") or "Active", f.get("remarks")))
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

    qty = float(f.get("qty") or 1)
    rate = float(f.get("rate") or (product["price"] if product else 0))
    gst = float(f.get("gst") or (product["gst"] if product else 0))
    taxable = qty * rate
    gst_amt = taxable * gst / 100
    total = taxable + gst_amt

    invoice_no = f.get("invoice_no") or f"{branch['prefix'] if branch else 'INV'}/{datetime.datetime.now().year}-{int(datetime.datetime.now().timestamp())}"
    invoice_date = f.get("invoice_date") or datetime.date.today().isoformat()
    due_date = f.get("due_date") or invoice_date

    invoice_json = {
        "customer_id": customer["id"] if customer else None,
        "customer_name": customer["name"] if customer else "",
        "bill_to_address": customer["address"] if customer else "",
        "ship_to_name": customer["shipping_name"] if customer else "",
        "ship_to_address": customer["shipping_address"] if customer else "",
        "items": [{
            "name": product["name"] if product else f.get("item_name","Item"),
            "hsn": product["hsn"] if product else "",
            "qty": qty, "rate": rate, "gst": gst,
            "taxable": taxable, "gst_amount": gst_amt, "total": total
        }]
    }

    db().execute("""INSERT INTO invoices(client_id,branch_id,invoice_type,invoice_no,invoice_date,due_date,customer_id,customer_name,total,status,invoice_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                 (cid, f.get("branch_id"), f.get("invoice_type") or "Tax Invoice", invoice_no, invoice_date, due_date,
                  customer["id"] if customer else None, customer["name"] if customer else "", total, "Unpaid", json.dumps(invoice_json)))
    db().commit()
    return redirect(url_for("dashboard"))

@app.route("/invoice/<int:invoice_id>")
@login_required
def view_invoice(invoice_id):
    inv = db().execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    client = db().execute("SELECT * FROM clients WHERE id=?", (inv["client_id"],)).fetchone()
    branch = db().execute("SELECT * FROM branches WHERE id=?", (inv["branch_id"],)).fetchone()
    data = json.loads(inv["invoice_json"] or "{}")
    return render_template("invoice.html", inv=inv, client=client, branch=branch, data=data)

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import mysql.connector as mycon
import hashlib
import random
import math
from datetime import datetime
from flask import Response
import csv
from datetime import date, timedelta
import yagmail
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from datetime import date, timedelta
import os
import uuid


app = Flask(__name__)
app.secret_key = "supersecretkey"

# ===================== DATABASE CONNECTION =====================
con = mycon.connect(
    host="localhost",
    user="root",
    password="123456"
)
cursor = con.cursor()
con.autocommit = True


UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ===================== DATABASE & TABLE =====================
cursor.execute("CREATE DATABASE IF NOT EXISTS banking")
cursor.execute("USE banking")

cursor.execute("""
CREATE TABLE IF NOT EXISTS customers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name CHAR(100),
    username VARCHAR(100) UNIQUE,
    phno BIGINT,
    age INT,
    gender CHAR(2),
    password_hash VARCHAR(64),
    balance DECIMAL(10,2) DEFAULT 0
)
""")

# ===================== PASSWORD HASH =====================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()
def get_account_id_from_session():
    cursor.execute("""
        SELECT a.id
        FROM customers c
        JOIN accounts a ON c.account_id = a.id
        WHERE c.id = %s
    """, (session["user_id"],))
    return cursor.fetchone()[0]


def get_transactions_for_account(account_id):
    cursor.execute("""
        SELECT id, created_at, description, amount, type
        FROM transactions
        WHERE account_id = %s
        ORDER BY created_at ASC
    """, (account_id,))
    return cursor.fetchall()


def generate_card_number():
    return "".join([str(random.randint(0, 9)) for _ in range(16)])

def generate_cvv():
    return str(random.randint(100, 999))

def generate_expiry():
    year = datetime.now().year + 5
    return f"06/{str(year)[-2:]}"

def calculate_emi(principal, annual_rate, tenure_months):
    monthly_rate = annual_rate / (12 * 100)

    if monthly_rate == 0:
        return round(principal / tenure_months, 2)

    emi = (
        principal
        * monthly_rate
        * math.pow(1 + monthly_rate, tenure_months)
        / (math.pow(1 + monthly_rate, tenure_months) - 1)
    )

    return round(emi, 2)

def accrued_interest(outstanding, annual_rate, days):
    daily_rate = annual_rate / (365 * 100)
    return outstanding * daily_rate * days


def foreclosure_amount(outstanding, annual_rate, penalty_percent, days):
    interest = accrued_interest(outstanding, annual_rate, days)
    penalty = outstanding * penalty_percent / 100

    total = outstanding + interest + penalty

    return {
        "principal": round(outstanding, 2),
        "interest": round(interest, 2),
        "penalty": round(penalty, 2),
        "total": round(total, 2)
    }


def foreclosure_savings(emi, remaining_months, foreclosure_total):
    total_future = emi * remaining_months
    savings = total_future - foreclosure_total
    return max(0, round(savings, 2))




def partial_prepayment(outstanding, prepay_amount, rate, months):
    new_principal = outstanding - prepay_amount
    if new_principal <= 0:
        return 0, 0
    new_emi = calculate_emi(new_principal, rate, months)
    return round(new_principal, 2), new_emi

# ===================== HOME =====================
@app.route("/")
def home():
    return render_template("index.html")

# ===================== AJAX VALIDATION =====================
@app.route("/validate", methods=["POST"])
def validate():
    data = request.json
    username = data.get("username", "")
    phno = data.get("phno", "")
    password = data.get("password", "")

    msg = {"username": "", "phno": "", "password": ""}

    if username:
        cursor.execute("SELECT * FROM customers WHERE username=%s", (username,))
        msg["username"] = "❌ Username exists" if cursor.fetchone() else "✅ Username available"

    if phno:
        msg["phno"] = "❌ Invalid phone" if len(phno) != 10 or not phno.isdigit() else "✅ Valid phone"

    if password:
        if len(password) < 10:
            msg["password"] = "❌ Minimum 10 characters"
        elif not any(c.isupper() for c in password):
            msg["password"] = "❌ One uppercase required"
        elif not any(c in "!@#$%^&*" for c in password):
            msg["password"] = "❌ One special character required"
        else:
            msg["password"] = "✅ Strong password"

    return jsonify(msg)

# ===================== SIGNUP =====================
@app.route("/signup.html", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name")
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        mpin = request.form.get("mpin")   # ✅ NEW

        # ---------- BASIC VALIDATION ----------
        if not name or not username or not password or not mpin:
            flash("All fields are required", "error")
            return redirect(url_for("signup"))

        # ---------- MPIN VALIDATION ----------
        if not mpin.isdigit() or len(mpin) != 4:
            flash("MPIN must be exactly 4 digits", "error")
            return redirect(url_for("signup"))

        # ---------- CHECK USERNAME ----------
        cursor.execute("SELECT id FROM customers WHERE username=%s", (username,))
        if cursor.fetchone():
            flash("Username already exists!", "error")
            return redirect(url_for("signup"))

        # ---------- GENERATE CARD DETAILS ----------
        card_number = generate_card_number()
        expiry_date = generate_expiry()
        cvv = generate_cvv()

        # ---------- CREATE ACCOUNT ----------
        cursor.execute("""
            INSERT INTO accounts (balance, type, card_number, expiry_date, cvv)
            VALUES (%s, %s, %s, %s, %s)
        """, (0, "SAVINGS", card_number, expiry_date, cvv))
        con.commit()

        account_id = cursor.lastrowid

        # ---------- CREATE CUSTOMER (WITH MPIN) ----------
        cursor.execute("""
            INSERT INTO customers (name, username, password_hash, account_id, mpin, email)
            VALUES (%s, %s, %s, %s, %s,%s)
        """, (
            name,
            username,
            hash_password(password),
            account_id,
            hash_password(mpin)   # ✅ STORE HASHED MPIN
        ))
        con.commit()

        flash("Account created successfully. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")

# ===================== LOGIN =====================
@app.route("/login.html", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        cursor.execute("""
            SELECT id, password_hash FROM customers WHERE username=%s
        """, (username,))
        user = cursor.fetchone()

        if not user:
            flash("❌ Username not found")
            return redirect(url_for("login"))

        if hash_password(password) == user[1]:
            session["user_id"] = user[0]
            return redirect(url_for("dashboard"))
        else:
            flash("❌ Incorrect password")
            return redirect(url_for("login"))

    return render_template("login.html")

# ===================== DASHBOARD =====================
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # ---------- USER + ACCOUNT DETAILS ----------
    cursor.execute("""
        SELECT c.name, a.id, a.balance, a.type,c.ext_loans, c.ext_loan_type
        FROM customers c
        JOIN accounts a ON c.account_id = a.id
        WHERE c.id = %s
    """, (user_id,))

    user = cursor.fetchone()

    if not user:
        return "ERROR: Customer has no linked account."

    name = user[0]
    account_id = user[1]
    balance = float(user[2])
    account_type = user[3]
    ext_loans = user[4]
    ext_loan_type = user[5]

    # ---------- FETCH TRANSACTIONS ----------
    cursor.execute("""
        SELECT 
            DATE_FORMAT(created_at, '%d %b') AS date,
            description,
            amount,
            type,
            created_at
        FROM transactions
        WHERE account_id = %s
        ORDER BY created_at DESC
    """, (account_id,))

    rows = cursor.fetchall()

    transactions = []
    card_activities = []
    spent = 0

    for i, r in enumerate(rows):
        amt = float(r[2])

        if r[3] == "DEBIT":
            spent += amt
            signed_amt = -amt
        else:
            signed_amt = amt

        transactions.append({
            "date": r[0],
            "desc": r[1],
            "amount": signed_amt,
            "status": "Completed"
        })

        # Last 3 for card activities
        if i < 3:
            card_activities.append({
                "desc": r[1],
                "amount": signed_amt
            })

    saving = balance
    balance = round(balance, 2)
    spent=round(spent,2)


    # ---------- CHART DATA (RUNNING BALANCE) ----------
    cursor.execute("""
        SELECT amount, type, DATE_FORMAT(created_at, '%b')
        FROM transactions
        WHERE account_id = %s
        ORDER BY created_at
    """, (account_id,))

    running_balance = 0
    chart_labels = []
    chart_data = []

    for amt, ttype, month in cursor.fetchall():
        if ttype == "DEBIT":
            running_balance -= float(amt)
        else:
            running_balance += float(amt)

        chart_labels.append(month)
        chart_data.append(running_balance)

    return render_template(
        "dashboard.html",
        name=name,
        balance=balance,
        spent=spent,
        saving=saving,
        account_type=account_type,
        transactions=transactions,
        card_activities=card_activities,
        chart_labels=chart_labels,
        chart_data=chart_data,
        ext_loans=ext_loans,         
        ext_loan_type=ext_loan_type
        
    )

# ===================== LOGOUT =====================
@app.route("/fund-transfer", methods=["GET", "POST"])
def fund_transfer():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        receiver_name = request.form["receiver_name"].strip()
        card_number = request.form["card_number"].replace(" ", "")
        expiry_date = request.form["expiry_date"].strip()
        cvv = request.form["cvv"].strip()
        amount = float(request.form["amount"])
        mpin = request.form["mpin"]   # ✅ READ MPIN FROM POPUP
        description = request.form.get("description", "Fund Transfer")

        user_id = session["user_id"]

        # ---------- GET SENDER ACCOUNT + MPIN ----------
        cursor.execute("""
            SELECT account_id, mpin
            FROM customers
            WHERE id=%s
        """, (user_id,))
        sender = cursor.fetchone()

        if not sender:
            flash("Sender account not found", "error")
            return redirect(url_for("fund_transfer"))

        sender_account_id = sender[0]
        stored_mpin = sender[1]   # ✅ HASHED MPIN FROM DB

        # ---------- MPIN VERIFICATION ----------
        if hash_password(mpin) != stored_mpin:
            flash("Invalid MPIN", "error")
            return redirect(url_for("fund_transfer"))

        # ---------- FIND RECEIVER ACCOUNT (CARD DETAILS) ----------
        cursor.execute("""
            SELECT a.id
            FROM accounts a
            WHERE a.card_number=%s
              AND a.expiry_date=%s
              AND a.cvv=%s
        """, (card_number, expiry_date, cvv))

        receiver = cursor.fetchone()
        if not receiver:
            flash("Details are incorrect", "error")
            return redirect(url_for("fund_transfer"))

        receiver_account_id = receiver[0]

        # ---------- VERIFY CARD HOLDER NAME ----------
        cursor.execute("""
            SELECT c.id
            FROM customers c
            WHERE c.account_id=%s
              AND c.name=%s
        """, (receiver_account_id, receiver_name))

        if not cursor.fetchone():
            flash("Details are incorrect", "error")
            return redirect(url_for("fund_transfer"))

        # ---------- CHECK BALANCE ----------
        cursor.execute(
            "SELECT balance FROM accounts WHERE id=%s",
            (sender_account_id,)
        )
        sender_balance = float(cursor.fetchone()[0])

        if sender_balance < amount:
            flash("Insufficient balance", "error")
            return redirect(url_for("fund_transfer"))

        # ---------- PERFORM TRANSFER ----------
        cursor.execute("""
            UPDATE accounts
            SET balance = balance - %s
            WHERE id=%s
        """, (amount, sender_account_id))

        cursor.execute("""
            INSERT INTO transactions (account_id, amount, type, description)
            VALUES (%s, %s, 'DEBIT', %s)
        """, (sender_account_id, amount, description))

        cursor.execute("""
            UPDATE accounts
            SET balance = balance + %s
            WHERE id=%s
        """, (amount, receiver_account_id))

        cursor.execute("""
            INSERT INTO transactions (account_id, amount, type, description)
            VALUES (%s, %s, 'CREDIT', %s)
        """, (receiver_account_id, amount, description))

        con.commit()

        flash("Amount transferred successfully", "success")
        return redirect(url_for("dashboard"))

    return render_template("FT.html")

@app.route("/transactions")
def transactions_page():
    if "user_id" not in session:
        return redirect(url_for("login"))

    # Get account id
    cursor.execute("""
        SELECT a.id, a.balance
        FROM customers c
        JOIN accounts a ON c.account_id = a.id
        WHERE c.id = %s
    """, (session["user_id"],))
    acc = cursor.fetchone()

    if not acc:
        flash("Account not found", "error")
        return redirect(url_for("dashboard"))

    account_id = acc[0]
    current_balance = float(acc[1])

    # Fetch transactions (oldest first for balance calc)
    cursor.execute("""
        SELECT id, created_at, description, amount, type
        FROM transactions
        WHERE account_id = %s
        ORDER BY created_at ASC
    """, (account_id,))
    rows = cursor.fetchall()

    transactions = []
    running_balance = 0

    for r in rows:
        txn_id = f"TXN{r[0]:06d}"
        date = r[1].strftime("%d %b %Y")
        desc = r[2]
        amt = float(r[3])
        ttype = r[4]

        debit = amt if ttype == "DEBIT" else ""
        credit = amt if ttype == "CREDIT" else ""

        if ttype == "CREDIT":
            running_balance += amt
        else:
            running_balance -= amt

        transactions.append({
            "date": date,
            "txn_id": txn_id,
            "desc": desc,
            "debit": debit,
            "credit": credit,
            "balance": round(running_balance, 2),
            "status": "Completed"
        })

    return render_template(
        "transactions.html",
        transactions=transactions
    )

@app.route("/transactions/export/csv")
def export_transactions_csv():
    if "user_id" not in session:
        return redirect(url_for("login"))

    account_id = get_account_id_from_session()
    rows = get_transactions_for_account(account_id)

    def generate():
        yield "Date,Txn ID,Description,Debit,Credit,Balance,Status\n"
        running_balance = 0

        for r in rows:
            amt = float(r[3])

            if r[4] == "CREDIT":
                credit, debit = amt, ""
                running_balance += amt
            else:
                debit, credit = amt, ""
                running_balance -= amt

            yield (
                f"{r[1].strftime('%d-%m-%Y')},"
                f"TXN{r[0]:06d},"
                f"{r[2]},"
                f"{debit},"
                f"{credit},"
                f"{round(running_balance,2)},"
                f"Completed\n"
            )

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"}
    )
@app.route("/transactions/export/pdf")
def export_transactions_pdf():
    if "user_id" not in session:
        return redirect(url_for("login"))

    account_id = get_account_id_from_session()
    rows = get_transactions_for_account(account_id)

    response = Response(content_type="application/pdf")
    response.headers["Content-Disposition"] = "attachment; filename=transactions.pdf"

    c = canvas.Canvas(response.stream, pagesize=A4)
    width, height = A4

    y = height - 40
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, "Transaction Statement")
    y -= 30

    c.setFont("Helvetica", 9)
    running_balance = 0

    for r in rows:
        if y < 50:
            c.showPage()
            y = height - 40
            c.setFont("Helvetica", 9)

        amt = float(r[3])

        if r[4] == "CREDIT":
            running_balance += amt
            debit, credit = "", amt
        else:
            running_balance -= amt
            debit, credit = amt, ""

        line = (
            f"{r[1].strftime('%d-%m-%Y')} | "
            f"TXN{r[0]:06d} | "
            f"{r[2]} | "
            f"D:{debit} C:{credit} | "
            f"Bal:{round(running_balance,2)} | Completed"
        )

        c.drawString(40, y, line)
        y -= 14

    c.save()
    return response
@app.route("/wallet")
def wallet():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Get account + card details
    cursor.execute("""
        SELECT 
            c.name,
            a.id,
            a.balance,
            a.type,
            a.card_number,
            a.expiry_date
        FROM customers c
        JOIN accounts a ON c.account_id = a.id
        WHERE c.id = %s
    """, (user_id,))
    data = cursor.fetchone()

    if not data:
        flash("Wallet not found", "error")
        return redirect(url_for("dashboard"))

    name, account_id, balance, acc_type, card_number, expiry = data

    # Mask card number
    masked_card = "**** **** **** " + card_number[-4:]

    # Recent transactions
    cursor.execute("""
        SELECT description, amount, type
        FROM transactions
        WHERE account_id = %s
        ORDER BY created_at DESC
        LIMIT 5
    """, (account_id,))
    txns = cursor.fetchall()

    return render_template(
        "wallet.html",
        name=name,
        balance=balance,
        acc_type=acc_type,
        card_number=masked_card,
        expiry=expiry,
        transactions=txns
    )

@app.route("/loans", methods=["GET", "POST"])
def loans():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        loan_type = request.form.get("loan_type")
        amount = float(request.form.get("amount"))
        tenure = int(request.form.get("tenure"))

        interest_map = {
            "Home Loan": 8.5,
            "Education Loan": 6.5,
            "Personal Loan": 12,
            "Vehicle Loan": 9,
            "Gold Loan": 7
        }

        rate = interest_map.get(loan_type)
        emi = calculate_emi(amount, rate, tenure)

        # 🔽 IMAGE UPLOAD PART
        file = request.files.get("property_image")

        if file and file.filename != "":
            filename = str(uuid.uuid4()) + "_" + file.filename
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
        else:
            filepath = None

        # get account_id
        cursor.execute("""
            SELECT account_id FROM customers WHERE id=%s
        """, (session["user_id"],))
        account_id = cursor.fetchone()[0]

        # limit max active loans
        cursor.execute("""
            SELECT COUNT(*) FROM loans
            WHERE account_id=%s AND status='ACTIVE'
        """, (account_id,))
        active_loans = cursor.fetchone()[0]

        if active_loans >= 3:
            flash("Maximum 3 active loans allowed", "error")
            return redirect(url_for("loans"))

        # 🔽 INSERT UPDATED (added property_image)
        cursor.execute("""
            INSERT INTO loans
            (account_id, loan_type, loan_amount, interest_rate,
             tenure_months, emi_amount, status, start_date, property_image)
            VALUES (%s,%s,%s,%s,%s,%s,'ACTIVE',CURDATE(),%s)
        """, (
            account_id, loan_type, amount,
            rate, tenure, emi, filepath
        ))

        flash("Loan approved successfully", "success")
        return redirect(url_for("emi_dashboard"))

    return render_template("loans.html")

@app.route("/emi")
def emi_dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    cursor.execute("""
        SELECT account_id FROM customers WHERE id=%s
    """, (session["user_id"],))
    account_id = cursor.fetchone()[0]

    cursor.execute("""
        SELECT id, loan_type, loan_amount, emi_amount, status
        FROM loans
        WHERE account_id=%s AND status='ACTIVE'
        LIMIT 3
    """, (account_id,))
    loans = cursor.fetchall()

    c = 1

    if c == 1:
        return render_template("emi_dashboard.html", loans=loans)
    else:
        return render_template("emi_dashboard.html", loans=[])

@app.route("/emi/<int:loan_id>", methods=["GET", "POST"])
def emi_detail(loan_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    cursor.execute("SELECT account_id FROM customers WHERE id=%s", (session["user_id"],))
    account_id = cursor.fetchone()[0]

    cursor.execute("""
        SELECT loan_amount, emi_amount, tenure_months, interest_rate, property_image
        FROM loans
        WHERE id=%s AND account_id=%s
    """, (loan_id, account_id))
    loan = cursor.fetchone()

    if not loan:
        flash("Invalid loan", "error")
        return redirect(url_for("emi_dashboard"))

    # ✅ FIX HERE (use index, not key)
    loan_amount = float(loan[0])
    emi_amount = float(loan[1])
    tenure = int(loan[2])
    rate = float(loan[3])
    property_image = loan[4]   # ✅ CORRECT

    # principal paid only
    cursor.execute("""
        SELECT IFNULL(SUM(principal_component),0)
        FROM emi_payments WHERE loan_id=%s
    """, (loan_id,))
    principal_paid = float(cursor.fetchone()[0])

    outstanding = round(loan_amount - principal_paid, 2)

    cursor.execute("SELECT COUNT(*) FROM emi_payments WHERE loan_id=%s", (loan_id,))
    paid_months = cursor.fetchone()[0]

    remaining_months = max(tenure - paid_months, 0)

    total_future_emi = remaining_months * emi_amount

    if paid_months == 0:
        savings = 0
    else:
        penalty = outstanding * 0.02
        foreclosure_total = outstanding + penalty
        savings = total_future_emi - foreclosure_total

        if savings < 0:
            savings = 0

    savings = round(savings, 2)

    progress = int((principal_paid / loan_amount) * 100) if loan_amount > 0 else 0

    cursor.execute("""
        SELECT COUNT(*) FROM emi_payments
        WHERE loan_id=%s
        AND MONTH(paid_date)=MONTH(CURDATE())
        AND YEAR(paid_date)=YEAR(CURDATE())
    """, (loan_id,))
    already_paid = cursor.fetchone()[0] > 0

    # ================= EMI PAYMENT =================
    if request.method == "POST":

        if already_paid:
            flash("EMI already paid this month", "error")
            return redirect(url_for("emi_detail", loan_id=loan_id))

        cursor.execute("SELECT balance FROM accounts WHERE id=%s", (account_id,))
        balance = float(cursor.fetchone()[0])

        if balance < emi_amount:
            flash("Insufficient balance", "error")
            return redirect(url_for("emi_detail", loan_id=loan_id))

        monthly_rate = rate / (12 * 100)
        interest = outstanding * monthly_rate
        principal = emi_amount - interest

        cursor.execute("""
            UPDATE accounts SET balance = balance - %s WHERE id=%s
        """, (emi_amount, account_id))

        cursor.execute("""
            INSERT INTO emi_payments
            (loan_id, paid_amount, principal_component, interest_component)
            VALUES (%s,%s,%s,%s)
        """, (loan_id, emi_amount, principal, interest))

        cursor.execute("""
            INSERT INTO transactions (account_id, amount, type, description)
            VALUES (%s,%s,'DEBIT','EMI Payment')
        """, (account_id, emi_amount))

        if outstanding - principal <= 0:
            cursor.execute("UPDATE loans SET status='CLOSED' WHERE id=%s", (loan_id,))
            flash("🎉 Loan fully closed!", "success")
        else:
            flash("EMI paid successfully", "success")

        return redirect(url_for("emi_detail", loan_id=loan_id))

    cursor.execute("""
        SELECT DATE_FORMAT(MAX(paid_date), '%d %b %Y')
        FROM emi_payments WHERE loan_id=%s
    """, (loan_id,))
    last_paid = cursor.fetchone()[0]

    cursor.execute("SELECT balance FROM accounts WHERE id=%s", (account_id,))
    balance = float(cursor.fetchone()[0])

    return render_template(
        "emi_detail.html",
        loan_id=loan_id,
        loan_amount=loan_amount,
        emi_amount=emi_amount,
        outstanding=outstanding,
        balance=balance,
        progress=progress,
        already_paid=already_paid,
        property_image=property_image,  # ✅ now works
        last_paid=last_paid,
        savings=savings
    )

@app.route("/loan/foreclose/<int:loan_id>", methods=["POST"])
def foreclose(loan_id):

    account_id = get_account_id_from_session()

    cursor.execute("""
        SELECT l.loan_amount, l.interest_rate,
               IFNULL(SUM(e.principal_component),0)
        FROM loans l
        LEFT JOIN emi_payments e ON l.id=e.loan_id
        WHERE l.id=%s
        GROUP BY l.id
    """, (loan_id,))
    row = cursor.fetchone()

    if not row:
        flash("Loan not found", "error")
        return redirect(url_for("emi_dashboard"))

    loan_amount = float(row[0])
    rate = float(row[1])
    principal_paid = float(row[2])

    outstanding = loan_amount - principal_paid

    daily_rate = rate / (365 * 100)
    accrued_interest = outstanding * daily_rate * 30

    penalty = outstanding * 0.02
    foreclosure_total = outstanding + accrued_interest + penalty

    cursor.execute("SELECT balance FROM accounts WHERE id=%s", (account_id,))
    balance = float(cursor.fetchone()[0])

    if balance < foreclosure_total:
        flash("Insufficient balance", "error")
        return redirect(url_for("emi_dashboard"))

    cursor.execute("""
        UPDATE accounts SET balance = balance - %s WHERE id=%s
    """, (foreclosure_total, account_id))

    cursor.execute("""
        INSERT INTO transactions (account_id, amount, type, description)
        VALUES (%s,%s,'DEBIT','Loan Foreclosure')
    """, (account_id, foreclosure_total))

    cursor.execute("UPDATE loans SET status='FORECLOSED' WHERE id=%s", (loan_id,))

    flash(f"Loan foreclosed. Paid ₹{round(foreclosure_total,2)}", "success")

    return redirect(url_for("emi_dashboard"))


@app.route("/loan/prepay/<int:loan_id>", methods=["POST"])
def partial_prepay(loan_id):

    prepay_amount = float(request.form["amount"])
    account_id = get_account_id_from_session()

    cursor.execute("""
        SELECT l.loan_amount, l.interest_rate,
               IFNULL(SUM(e.principal_component),0)
        FROM loans l
        LEFT JOIN emi_payments e ON l.id=e.loan_id
        WHERE l.id=%s
        GROUP BY l.id
    """, (loan_id,))
    row = cursor.fetchone()

    if not row:
        flash("Loan not found", "error")
        return redirect(url_for("emi_dashboard"))

    loan_amount = float(row[0])
    rate = float(row[1])
    principal_paid = float(row[2])

    outstanding = loan_amount - principal_paid

    monthly_rate = rate / (12 * 100)
    accrued_interest = outstanding * monthly_rate

    interest_paid = min(prepay_amount, accrued_interest)
    remaining = prepay_amount - interest_paid
    principal_paid_now = min(remaining, outstanding)

    new_principal = outstanding - principal_paid_now

    cursor.execute("""
        UPDATE accounts SET balance = balance - %s WHERE id=%s
    """, (prepay_amount, account_id))

    cursor.execute("""
        INSERT INTO transactions (account_id, amount, type, description)
        VALUES (%s,%s,'DEBIT','Partial Loan Prepayment')
    """, (account_id, prepay_amount))

    if new_principal <= 0:
        cursor.execute("UPDATE loans SET status='CLOSED' WHERE id=%s", (loan_id,))
        flash("Loan fully closed!", "success")
    else:
        new_emi = calculate_emi(new_principal, rate, 12)

        cursor.execute("""
            UPDATE loans SET loan_amount=%s, emi_amount=%s
            WHERE id=%s
        """, (new_principal, new_emi, loan_id))

        flash("Partial prepayment successful", "success")

    return redirect(url_for("emi_detail", loan_id=loan_id))

@app.route("/refinance")
def refinance():

    if "user_id" not in session:
        return redirect(url_for("login"))

    # get ext loan
    cursor.execute("""
        SELECT e.bank_name, e.loan_type,
               e.principal, e.interest_rate,
               e.remaining_months, e.paperwork_cost
        FROM customers c
        JOIN extloans e ON c.ext_id = e.id
        WHERE c.id = %s
    """, (session["user_id"],))

    loan = cursor.fetchone()

    if not loan:
        flash("No external loan found", "error")
        return redirect(url_for("dashboard"))

    bank, loan_type, principal, old_rate, months, paperwork = loan

    principal = float(principal)
    old_rate = float(old_rate)
    paperwork = float(paperwork)

    # Tick Bank refinance rate
    rate_map = {
        "Home Loan": 8.5,
        "Car Loan": 9,
        "Personal Loan": 12,
        "Gold Loan": 7
    }

    new_rate = rate_map.get(loan_type, 9)

    old_emi = calculate_emi(principal, old_rate, months)
    new_emi = calculate_emi(principal, new_rate, months)

    total_old = old_emi * months
    total_new = new_emi * months + paperwork

    saving = round(total_old - total_new, 2)

    quotes = {
        "Home Loan": "Own your dream home smarter with Tick Bank.",
        "Car Loan": "Drive your future with lower EMI.",
        "Personal Loan": "Freedom from high interest starts here.",
        "Gold Loan": "Your gold deserves better returns."
    }

    offer = {
        "rate": f"{new_rate}%",
        "saving": f"₹{saving}",
        "quote": quotes.get(loan_type, "Switch and save more.")
    }

    return render_template(
        "refinance.html",
        loan_type=loan_type,
        offer=offer
    )
@app.route("/refinance/approve", methods=["POST"])
def refinance_approve():

    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # Get account + ext loan
    cursor.execute("""
        SELECT c.account_id, e.loan_type,
               e.principal, e.remaining_months
        FROM customers c
        JOIN extloans e ON c.ext_id = e.id
        WHERE c.id = %s
    """, (user_id,))
    data = cursor.fetchone()

    if not data:
        flash("No refinance data found", "error")
        return redirect(url_for("dashboard"))

    account_id, loan_type, principal, months = data

    # Tick Bank rates
    rate_map = {
        "Home Loan": 8.5,
        "Vehicle Loan": 9,
        "Personal Loan": 12,
        "Gold Loan": 7
    }

    rate = rate_map[loan_type]

    emi = calculate_emi(float(principal), rate, months)

    # Create new internal loan
    cursor.execute("""
        INSERT INTO loans
        (account_id, loan_type, loan_amount,
         interest_rate, tenure_months,
         emi_amount, status, start_date)
        VALUES (%s,%s,%s,%s,%s,%s,'ACTIVE',CURDATE())
    """, (
        account_id,
        loan_type,
        principal,
        rate,
        months,
        emi
    ))

    con.commit()

    new_loan_id = cursor.lastrowid


    flash("Loan successfully transferred to Tick Bank!", "success")

    cursor.execute("""
        UPDATE customers
        SET ext_loans='NO'
        WHERE id=%s""",(user_id,))

    return redirect(url_for("emi_detail", loan_id=new_loan_id))

from datetime import date, timedelta
import yagmail


from datetime import date, timedelta

def send_emi_reminders():

    yag = yagmail.SMTP("tickbanksup@gmail.com", "suoh plmj dhan ncwt")

    cursor.execute("""
        SELECT 
            c.name,
            c.email,
            l.id,
            l.loan_type,
            l.loan_amount,
            l.emi_amount,
            IFNULL(SUM(e.paid_amount),0)
        FROM loans l
        JOIN customers c ON l.account_id = c.account_id
        LEFT JOIN emi_payments e ON l.id = e.loan_id
        WHERE l.status='ACTIVE'
        GROUP BY l.id, c.name, c.email, l.loan_type, l.loan_amount, l.emi_amount
    """)

    rows = cursor.fetchall()

    for name, email, loan_id, loan_type, loan_amount, emi, total_paid in rows:

        outstanding = float(loan_amount) - float(total_paid)

        deadline = date.today() + timedelta(days=5)
        deadline_str = deadline.strftime("%d %b %Y")

        subject = "EMI Payment Reminder – Tick Bank"

        body = f"""
Dear {name},

This is a friendly reminder from Tick Bank regarding your active loan account.

Your upcoming EMI payment of ₹{float(emi):.2f} is due on {deadline_str}.
Please ensure sufficient balance to avoid late fees.

Loan Details:
• Loan Type: {loan_type}
• Outstanding Amount: ₹{outstanding:.2f}
• EMI Due Date: {deadline_str}

You can pay your EMI instantly by logging into your Tick Bank dashboard.

If you already paid, please ignore this message.

Warm regards,
Tick Bank Support Team
support@tickbank.com
"""

        yag.send(email, subject, body)



@app.route("/send-reminders")
def send_reminders():

    send_emi_reminders()

    return "EMI reminder emails sent!"




@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ===================== RUN =====================


from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(send_emi_reminders, 'cron', hour=9)

if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    scheduler.start()



if __name__ == "__main__":
    app.run(debug=True)

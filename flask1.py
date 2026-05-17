from flask import Flask, render_template, request, redirect, url_for, flash
import mysql.connector as mycon
import hashlib

app = Flask(__name__)
app.secret_key = "supersecretkey"  # for flash messages

# ✅ Connect to MySQL
con = mycon.connect(host="localhost", user="root", password="123456")
cursor = con.cursor()
con.autocommit = True

# ✅ Create database and table if not exist
cursor.execute("CREATE DATABASE IF NOT EXISTS banking")
cursor.execute("USE banking")
cursor.execute('''
    CREATE TABLE IF NOT EXISTS customers (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name CHAR(100),
        username VARCHAR(100) UNIQUE,
        phno BIGINT,
        age INT,
        gender CHAR(2),
        password_hash VARCHAR(64)
    )
''')

# ✅ Hash function for password
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ✅ Home route (index.html)
@app.route("/")
def home():
    return render_template("index.html")

# ✅ Signup route
@app.route("/signup.html", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["name"]
        username = request.form["username"]
        phno = request.form["phno"]
        age = request.form["age"]
        gender = request.form["gender"]
        password = request.form["password"]

        # check if username already exists
        cursor.execute("SELECT * FROM customers WHERE username = %s", (username,))
        if cursor.fetchone():
            flash("❌ Username already exists!")
            return redirect(url_for("signup"))

        # phone validation
        if len(phno) != 10 or not phno.isdigit():
            flash("❌ Phone number must be exactly 10 digits.") 
            return redirect(url_for("signup"))

        # password validation
        if not any(c in "!@#$%^&*" for c in password):
            flash("❌ Password must contain at least one special character.")
            return redirect(url_for("signup"))
        if not any(c.isupper() for c in password):
            flash("❌ Password must contain at least one uppercase letter.")
            return redirect(url_for("signup"))

        # insert into database
        cursor.execute(
            "INSERT INTO customers (name, username, phno, age, gender, password_hash) VALUES (%s, %s, %s, %s, %s, %s)",
            (name, username, phno, age, gender, hash_password(password))
        )
        con.commit()

        flash("✅ Account created successfully!")
        return redirect(url_for("login"))

    return render_template("signup.html")

# ✅ Login route
@app.route("/login.html", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        cursor.execute("SELECT password_hash FROM customers WHERE username = %s", (username,))
        result = cursor.fetchone()

        if not result:
            flash("❌ Username not found!")
            return redirect(url_for("login"))

        if hash_password(password) == result[0]:
            flash("✅ Login successful!")
            return redirect(url_for("home"))  # ✅ fixed (was 'index' before)
        else:
            flash("❌ Incorrect password!")
            return redirect(url_for("login"))

    return render_template("login.html")

if __name__ == "__main__":
    app.run(debug=True)

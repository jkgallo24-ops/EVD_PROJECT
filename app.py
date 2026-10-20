import os

import mysql.connector
from mysql.connector import errors
from flask import Flask, request, jsonify, session, send_from_directory, abort, g
from werkzeug.security import generate_password_hash, check_password_hash

FOLDER = os.path.dirname(os.path.abspath(__file__))
DB_SETTINGS = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", 3306)),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "craveco"),
}
PUBLIC_FILES = {
    "index.html",
    "register.html",
    "dashboard.html",
    "cart.html",
    "order_success.html",
    "main.py",
    "logo.png",
    "promo.mp4",
}

PAYMENT_METHODS = {"COD", "GCash", "Card"}

app = Flask(__name__, static_folder=None)

app.secret_key = os.environ.get("SECRET_KEY", "change-this-to-a-long-random-text")


def get_db():
    """Open a MySQL connection the first time it is needed during a request."""
    if "db" not in g:
        g.db = mysql.connector.connect(**DB_SETTINGS)
    return g.db


@app.teardown_appcontext
def close_db(_error):
    """Flask calls this after every request, so connections never pile up."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def fail(message, status):
    """Send an error message back to the web page. main.py shows it to the user."""
    return jsonify(error=message), status


def clean(text, max_length):
    """Trim spaces and cut text that is too long."""
    return (text or "").strip()[:max_length]



@app.route("/")
def home():
    """http://localhost:5000  ->  the sign-in page."""
    return send_from_directory(FOLDER, "index.html")


@app.route("/<path:filename>")
def website_file(filename):
    """http://localhost:5000/cart.html  ->  cart.html (only if it is in PUBLIC_FILES)."""
    if filename not in PUBLIC_FILES:
        abort(404)
    return send_from_directory(FOLDER, filename)


@app.post("/api/register")
def register():
    """Create a new account.  Called by main.py -> _register()."""
    data = request.get_json(force=True, silent=True) or {}
    name = clean(data.get("name"), 100)
    email = clean(data.get("email"), 150).lower()
    password = data.get("password") or ""

    if not name or "@" not in email or len(password) < 6:
        return fail("Enter your name, a valid email, and a password of at least 6 characters.", 400)

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
            (name, email, generate_password_hash(password)),
        )
        db.commit()
    except errors.IntegrityError:
        return fail("That email is already registered. Try signing in instead.", 409)

    session["user_id"] = cursor.lastrowid  
    return jsonify(name=name)


@app.post("/api/login")
def login():
    """Check email + password.  Called by main.py -> _login()."""
    data = request.get_json(force=True, silent=True) or {}
    email = clean(data.get("email"), 150).lower()
    password = data.get("password") or ""

    cursor = get_db().cursor(dictionary=True)
    cursor.execute("SELECT id, name, password_hash FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        return fail("Wrong email or password. Check both and try again.", 401)

    session["user_id"] = user["id"]  
    return jsonify(name=user["name"])


@app.get("/api/me")
def who_am_i():
    """Is someone signed in?  Called by main.py -> init_page() on every page."""
    if "user_id" not in session:
        return fail("Not signed in.", 401)

    cursor = get_db().cursor(dictionary=True)
    cursor.execute("SELECT name FROM users WHERE id = %s", (session["user_id"],))
    user = cursor.fetchone()

    if not user:
        session.clear()
        return fail("Not signed in.", 401)
    return jsonify(name=user["name"])


@app.post("/api/logout")
def logout():
    """Sign out.  Called by main.py -> _logout()."""
    session.clear()
    return jsonify(ok=True)



@app.post("/api/orders")
def place_order():
    """
    Save an order.  Called by main.py -> place_order().

    The browser only sends WHAT was ordered (item names and quantities).
    The server looks up the prices itself, so nobody can change a price in the browser.
    """
    if "user_id" not in session:
        return fail("Please sign in to place an order.", 401)

    data = request.get_json(force=True, silent=True) or {}
    payment = data.get("payment", "COD")
    phone = clean(data.get("phone"), 30)
    address = clean(data.get("address"), 255)
    notes = clean(data.get("notes"), 255)

    if payment not in PAYMENT_METHODS:
        return fail("Choose a valid payment method.", 400)
    if sum(ch.isdigit() for ch in phone) < 7 or len(address) < 5:
        return fail("Enter a contact number and a delivery address.", 400)
    quantity_of = {} 
    for item in data.get("items") or []:
        try:
            name = str(item["name"])
            quantity = int(item["qty"])
        except (KeyError, TypeError, ValueError):
            return fail("Some items in your order are invalid.", 400)
        if not 1 <= quantity <= 50:
            return fail("Quantity must be between 1 and 50.", 400)
        quantity_of[name] = quantity_of.get(name, 0) + quantity

    if not quantity_of:
        return fail("Your cart is empty.", 400)

    db = get_db()
    cursor = db.cursor(dictionary=True)
    slots = ",".join(["%s"] * len(quantity_of))
    cursor.execute(
        f"SELECT name, price FROM menu_items WHERE is_available = 1 AND name IN ({slots})",
        tuple(quantity_of),
    )
    price_of = {row["name"]: row["price"] for row in cursor.fetchall()}

    missing = [name for name in quantity_of if name not in price_of]
    if missing:
        return fail("No longer available: " + ", ".join(missing), 400)

    lines = [{"name": n, "price": price_of[n], "qty": q} for n, q in quantity_of.items()]
    total = sum(line["price"] * line["qty"] for line in lines)

    try:
        writer = db.cursor()
        writer.execute(
            "INSERT INTO orders (user_id, payment_method, phone, address, notes, total) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (session["user_id"], payment, phone, address, notes, total),
        )
        order_id = writer.lastrowid
        writer.executemany(
            "INSERT INTO order_items (order_id, item_name, price, qty) VALUES (%s, %s, %s, %s)",
            [(order_id, line["name"], line["price"], line["qty"]) for line in lines],
        )
        db.commit()
    except Exception:
        db.rollback()
        return fail("We couldn't save your order. Please try again.", 500)
    return jsonify(order_id=order_id, total=total, items=lines)


@app.get("/api/orders")
def my_orders():
    """List the signed-in user's past orders (newest first)."""
    if "user_id" not in session:
        return fail("Please sign in first.", 401)

    cursor = get_db().cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM orders WHERE user_id = %s ORDER BY id DESC", (session["user_id"],)
    )
    orders = cursor.fetchall()

    for order in orders:
        cursor.execute(
            "SELECT item_name, price, qty FROM order_items WHERE order_id = %s", (order["id"],)
        )
        order["items"] = cursor.fetchall()
        order["created_at"] = str(order["created_at"])  # dates must be text to send as JSON

    return jsonify(orders)


if __name__ == "__main__":
    app.run(debug=True, port=5000)

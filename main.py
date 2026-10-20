import asyncio
import json
from html import escape

from js import document, lucide, window
from pyodide.http import pyfetch

CART_KEY = "craveco_cart"
USER_KEY = "craveco_user"
ORDER_KEY = "craveco_last_order"
REMEMBER_KEY = "craveco_remember_email"

PROTECTED_PAGES = ("dashboard.html", "cart.html", "order_success.html")
GUEST_PAGES = ("index.html", "register.html")


def current_page():
    name = str(window.location.pathname).split("/")[-1]
    return name or "index.html"


async def api(path, method="GET", payload=None):
    """Call the Flask backend. Returns (status_code, data_dict). Status 0 = server unreachable."""
    options = {"method": method, "headers": {"Content-Type": "application/json"}}
    if payload is not None:
        options["body"] = json.dumps(payload)
    try:
        resp = await pyfetch(path, **options)
        try:
            data = await resp.json()
        except Exception:
            data = {}
        return resp.status, data
    except Exception:
        return 0, {"error": "Can't reach the CraveCo server. Make sure app.py is running."}


def show_status(box_id, message, kind="error"):
    box = document.getElementById(box_id)
    if box:
        box.className = f"status-box {kind}"
        box.textContent = message


def clear_status(box_id):
    box = document.getElementById(box_id)
    if box:
        box.className = "status-box"
        box.textContent = ""


def field_value(element_id, strip=True):
    el = document.getElementById(element_id)
    if not el:
        return ""
    value = str(el.value)
    return value.strip() if strip else value


def get_cart():
    try:
        cart_json = window.localStorage.getItem(CART_KEY)
        if cart_json:
            return json.loads(str(cart_json))
    except Exception:
        pass
    return {}


def save_cart(cart):
    try:
        window.localStorage.setItem(CART_KEY, json.dumps(cart))
    except Exception:
        pass


def handle_login(event):
    asyncio.ensure_future(_login())


async def _login():
    email = field_value("login-email")
    password = field_value("login-pass", strip=False)

    if not email or not password:
        show_status("status-output", "Fill in your email and password to sign in.")
        return

    status, data = await api("/api/login", "POST", {"email": email, "password": password})
    if status == 200:
        window.localStorage.setItem(USER_KEY, data["name"])
        remember = document.getElementById("remember-me")
        if remember and remember.checked:
            window.localStorage.setItem(REMEMBER_KEY, email)
        else:
            window.localStorage.removeItem(REMEMBER_KEY)
        window.location.href = "dashboard.html"
    else:
        show_status("status-output", data.get("error", "Sign in failed. Please try again."))


def handle_register(event):
    asyncio.ensure_future(_register())


async def _register():
    name = field_value("reg-name")
    email = field_value("reg-email")
    password = field_value("reg-pass", strip=False)

    if not name or not email or not password:
        show_status("reg-status-output", "Fill in your name, email, and password.")
        return
    if len(password) < 6:
        show_status("reg-status-output", "Use a password with at least 6 characters.")
        return

    status, data = await api("/api/register", "POST", {"name": name, "email": email, "password": password})
    if status == 200:
        window.localStorage.setItem(USER_KEY, data["name"])
        window.location.href = "dashboard.html"
    else:
        show_status("reg-status-output", data.get("error", "Couldn't create your account. Please try again."))


def handle_logout(event):
    event.preventDefault()
    asyncio.ensure_future(_logout())


async def _logout():
    await api("/api/logout", "POST", {})
    for key in (CART_KEY, USER_KEY, ORDER_KEY):
        window.localStorage.removeItem(key)
    window.location.href = "index.html"


def toggle_password(event):
    pass_input = document.getElementById("login-pass")
    icon = document.getElementById("toggle-pass-icon")

    if pass_input and icon:
        if pass_input.type == "password":
            pass_input.type = "text"
            icon.setAttribute("data-lucide", "eye-off")
        else:
            pass_input.type = "password"
            icon.setAttribute("data-lucide", "eye")
        lucide.createIcons()


def handle_forgot_password(event):
    event.preventDefault()
    show_status(
        "status-output",
        "Password reset isn't available yet. Contact CraveCo support to get back into your account.",
        "error",
    )

async def place_order(items, payment, phone, address, notes, status_box_id):
    """Send the order to the server. Returns True when it was saved."""
    status, data = await api("/api/orders", "POST", {
        "items": items,
        "payment": payment,
        "phone": phone,
        "address": address,
        "notes": notes,
    })

    if status == 200:
        window.localStorage.setItem(ORDER_KEY, json.dumps({
            "order_id": data["order_id"],
            "items": data["items"],
            "total": data["total"],
            "payment": payment,
            "address": address,
            "notes": notes or "None",
        }))
        return True

    if status == 401:
        window.location.href = "index.html"
        return False

    show_status(status_box_id, data.get("error", "We couldn't place your order. Please try again."))
    return False


def has_delivery_details(phone, address):
    return sum(ch.isdigit() for ch in phone) >= 7 and len(address) >= 5



def open_card_options(event):
    card_id = event.currentTarget.getAttribute("data-id")
    btn_container = document.getElementById(f"btn-container-{card_id}")
    options_container = document.getElementById(f"options-container-{card_id}")

    if btn_container and options_container:
        btn_container.classList.add("hidden")
        options_container.classList.remove("hidden")


def cancel_card_options(event):
    card_id = event.currentTarget.getAttribute("data-id")
    btn_container = document.getElementById(f"btn-container-{card_id}")
    options_container = document.getElementById(f"options-container-{card_id}")

    if btn_container and options_container:
        options_container.classList.add("hidden")
        btn_container.classList.remove("hidden")
    clear_status("dash-status")


def confirm_card_order(event):
    btn = event.currentTarget
    card_id = btn.getAttribute("data-id")
    item_name = btn.getAttribute("data-item")
    asyncio.ensure_future(_card_order(btn, card_id, item_name))


async def _card_order(btn, card_id, item_name):
    payment = field_value(f"pay-{card_id}") or "COD"
    phone = field_value(f"phone-{card_id}")
    address = field_value(f"address-{card_id}")
    notes = field_value(f"note-{card_id}")

    if not has_delivery_details(phone, address):
        show_status("dash-status", f"Add a contact number and delivery address to order {item_name}.")
        return

    clear_status("dash-status")
    btn.disabled = True
    saved = await place_order([{"name": item_name, "qty": 1}], payment, phone, address, notes, "dash-status")
    if saved:
        window.location.href = "order_success.html"
    else:
        btn.disabled = False



def confirm_cart_checkout(event):
    btn = event.currentTarget
    asyncio.ensure_future(_cart_checkout(btn))


async def _cart_checkout(btn):
    cart = get_cart()
    selected = {name: data for name, data in cart.items() if data.get("selected", True)}

    if not selected:
        show_status("cart-status", "Select at least one item in your cart to check out.")
        return

    payment = field_value("cart-payment-method") or "COD"
    phone = field_value("cart-phone")
    address = field_value("cart-address")
    notes = field_value("cart-notes")

    if not has_delivery_details(phone, address):
        show_status("cart-status", "Add a contact number and delivery address before checking out.")
        return

    clear_status("cart-status")
    btn.disabled = True
    items = [{"name": name, "qty": data["qty"]} for name, data in selected.items()]
    saved = await place_order(items, payment, phone, address, notes, "cart-status")

    if saved:
        for name in selected:
            del cart[name]
        save_cart(cart)
        update_cart_badge()
        window.location.href = "order_success.html"
    else:
        btn.disabled = False


def add_to_cart(event):
    btn = event.currentTarget
    item_name = btn.getAttribute("data-item")
    price_attr = btn.getAttribute("data-price")
    item_price = int(price_attr) if price_attr else 199 

    cart = get_cart()
    if item_name in cart:
        cart[item_name]["qty"] += 1
    else:
        cart[item_name] = {"price": item_price, "qty": 1, "selected": True}

    save_cart(cart)
    update_cart_badge()
    render_cart_items()


def increase_qty(event):
    item_name = event.currentTarget.getAttribute("data-item")
    cart = get_cart()
    if item_name in cart:
        cart[item_name]["qty"] += 1

    save_cart(cart)
    update_cart_badge()
    render_cart_items()


def decrease_qty(event):
    item_name = event.currentTarget.getAttribute("data-item")
    cart = get_cart()
    if item_name in cart:
        if cart[item_name]["qty"] > 1:
            cart[item_name]["qty"] -= 1
        else:
            del cart[item_name]

    save_cart(cart)
    update_cart_badge()
    render_cart_items()


def remove_from_cart(event):
    item_name = event.currentTarget.getAttribute("data-item")
    cart = get_cart()
    if item_name in cart:
        del cart[item_name]

    save_cart(cart)
    update_cart_badge()
    render_cart_items()


def toggle_item_selection(event):
    checkbox = event.currentTarget
    item_name = checkbox.getAttribute("data-item")
    is_checked = checkbox.checked

    cart = get_cart()
    if item_name in cart:
        cart[item_name]["selected"] = is_checked

    save_cart(cart)
    update_total_price(cart)


def update_cart_badge():
    cart = get_cart()
    total_qty = sum(item["qty"] for item in cart.values())
    badge = document.getElementById("cart-badge-count")
    if badge:
        badge.innerHTML = str(total_qty)


def update_total_price(cart):
    total_price = 0
    for data in cart.values():
        if data.get("selected", True):
            total_price += data["price"] * data["qty"]

    total_price_el = document.getElementById("cart-total-price")
    if total_price_el:
        total_price_el.innerHTML = f"₱{total_price}"


def render_cart_items():
    container = document.getElementById("cart-items-list")
    if not container:
        return

    cart = get_cart()
    if not cart:
        container.innerHTML = "<p style='color: var(--text-muted); font-size: 13px; text-align: center; padding: 15px;'>Your cart is empty. Add something from the menu.</p>"
        total_price_el = document.getElementById("cart-total-price")
        if total_price_el:
            total_price_el.innerHTML = "₱0"
        return

    html_content = ""
    for name, data in cart.items():
        safe_name = escape(name, quote=True)
        subtotal = data["price"] * data["qty"]
        is_selected = "checked" if data.get("selected", True) else ""
        html_content += f"""
            <div style="background: var(--input-bg); border: 1px solid var(--border-color); border-radius: 10px; padding: 8px 10px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <input type="checkbox" {is_selected} py-change="toggle_item_selection" data-item="{safe_name}" style="accent-color: var(--brand-orange); width: 16px; height: 16px; cursor: pointer;">
                    <div>
                        <div style="font-size: 12px; font-weight: 700;">{safe_name}</div>
                        <div style="font-size: 10px; color: var(--text-muted);">₱{data['price']} x {data['qty']} = <span style="color: var(--brand-orange);">₱{subtotal}</span></div>
                    </div>
                </div>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <div style="display: flex; align-items: center; gap: 4px;">
                        <button class="qty-btn" py-click="decrease_qty" data-item="{safe_name}">-</button>
                        <span style="font-size: 12px; font-weight: 700; color: var(--brand-white); width: 16px; text-align: center;">{data['qty']}</span>
                        <button class="qty-btn" py-click="increase_qty" data-item="{safe_name}">+</button>
                    </div>
                    <button class="delete-btn" py-click="remove_from_cart" data-item="{safe_name}">Delete</button>
                </div>
            </div>
        """

    container.innerHTML = html_content
    update_total_price(cart)



def render_success():
    name_el = document.getElementById("success-item-name")
    if not name_el:
        return  # not the success page

    raw = window.localStorage.getItem(ORDER_KEY)
    if not raw:
        window.location.href = "dashboard.html" 
        return

    order = json.loads(str(raw))
    name_el.textContent = ", ".join(f"{i['name']} (x{i['qty']})" for i in order["items"])

    price_el = document.getElementById("success-item-price")
    if price_el:
        price_el.textContent = f"₱{order['total']}"

    payment_el = document.getElementById("success-payment")
    if payment_el:
        payment_el.textContent = order.get("payment", "COD")

    notes_el = document.getElementById("success-notes")
    if notes_el:
        notes_el.textContent = order.get("notes") or "None"

    subtitle = document.getElementById("success-subtitle")
    if subtitle:
        subtitle.textContent = f"Order #{order['order_id']}. Your delicious meal is being prepared."


async def init_page():
    page = current_page()
    status, data = await api("/api/me")
    logged_in = status == 200

    if page in PROTECTED_PAGES and status == 401:
        window.location.href = "index.html"
        return

    if page in GUEST_PAGES and logged_in:
        window.location.href = "dashboard.html"
        return

    if logged_in:
        window.localStorage.setItem(USER_KEY, data["name"])
        subtitle = document.getElementById("welcome-user-subtitle")
        if subtitle:
            subtitle.textContent = f"Hi {data['name']}, ready for your meal?"

    if page == "index.html":
        remembered = window.localStorage.getItem(REMEMBER_KEY)
        email_input = document.getElementById("login-email")
        remember_box = document.getElementById("remember-me")
        if remembered and email_input:
            email_input.value = str(remembered)
            if remember_box:
                remember_box.checked = True


update_cart_badge()
render_cart_items()
render_success()
asyncio.ensure_future(init_page())

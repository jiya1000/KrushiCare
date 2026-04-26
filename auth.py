import re, jwt, bcrypt, datetime, sib_api_v3_sdk
import os
from functools import wraps
from flask import Blueprint, request, jsonify, current_app
from database import get_db
from sib_api_v3_sdk.rest import ApiException
from itsdangerous import URLSafeTimedSerializer

auth_bp = Blueprint("auth", __name__)

# --- CONFIGURATION (Inhe Flask config mein bhi daal sakte hain) ---
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
SENDER_EMAIL = "factzit444@gmail.com"
BASE_URL = "https://web-production-29bb2.up.railway.app" # Localhost ke liye

# Brevo SDK Setup
configuration = sib_api_v3_sdk.Configuration()
configuration.api_key['api-key'] = BREVO_API_KEY
api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

def _get_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])

# ── Helper: Send Verification Email ──────────────────────────────────────────

def send_verification_email(user_email, first_name):
    serializer = _get_serializer()
    token = serializer.dumps(user_email, salt='email-confirm')
    confirm_url = f"{BASE_URL}/api/auth/confirm/{token}"

    subject = "Verify your Krushicare Account"
    html_content = f"""
        <div style="font-family: Arial, sans-serif; border: 1px solid #ddd; padding: 20px; border-radius: 10px;">
            <h2 style="color: #28a745;">Namaste {first_name}!</h2>
            <p>Krushicare mein signup karne ke liye shukriya. Apna account activate karne ke liye niche diye gaye button par click karein:</p>
            <a href="{confirm_url}" style="display: inline-block; background: #28a745; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; margin: 20px 0;">Verify Account</a>
            <p style="font-size: 12px; color: #777;">Agar aapne ye request nahi ki hai, toh is email ko ignore karein. Yeh link 1 ghante mein expire ho jayega.</p>
        </div>
    """
    
    sender = {"name": "Krushicare Support", "email": SENDER_EMAIL}
    to = [{"email": user_email}]
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(to=to, html_content=html_content, sender=sender, subject=subject)

    try:
        api_instance.send_transac_email(send_smtp_email)
        return True
    except ApiException as e:
        print(f"Brevo API Error: {e}")
        return False

# ── Helper: JWT banana ────────────────────────────────────────────────────────

def _make_token(user_id, email):
    payload = {
        "user_id": user_id,
        "email":   email,
        "exp":     datetime.datetime.utcnow() + datetime.timedelta(days=7),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")

# ── Decorator: protected routes ───────────────────────────────────────────────

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

        if not token:
            return jsonify({"success": False, "message": "Login required"}), 401

        try:
            data = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
            current_user = {"user_id": data["user_id"], "email": data["email"]}
        except:
            return jsonify({"success": False, "message": "Invalid or expired token"}), 401

        return f(current_user, *args, **kwargs)
    return decorated

# ── POST /api/auth/signup ─────────────────────────────────────────────────────

@auth_bp.route("/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}

    required_fields = ["first_name", "last_name", "email", "password", "phone"]
    for field in required_fields:
        if not data.get(field, "").strip():
            return jsonify({"success": False, "message": f"'{field}' bharna zaroori hai"}), 400

    email = data["email"].strip().lower()
    phone = data["phone"].strip()

    # --- VALIDATIONS START ---

    # 1. Email Validation
    if not re.match(r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$', email):
        return jsonify({"success": False, "message": "Email format sahi nahi hai"}), 400

    # 2. Phone Number Validation (Strict Regex merged here)
    # Check karega: 10 digits aur 6-9 se shuru hone wala Indian number
    if not re.match(r'^[6-9]\d{9}$', phone):
        return jsonify({"success": False, "message": "Invalid phone number! 10 digits ka valid Indian number daalein (6-9 se shuru hone wala)."}), 400

    # 3. Password Length Check
    if len(data["password"]) < 8:
        return jsonify({"success": False, "message": "Password kam se kam 8 chars ka hona chahiye"}), 400

    # --- VALIDATIONS END ---

    hashed = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()).decode()
    
    conn = get_db()
    try:
        c = conn.cursor()
        # is_verified default 0 rahega
        c.execute("""
            INSERT INTO users (first_name, last_name, email, phone, state, password, is_verified)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        """, (data["first_name"].strip(), data["last_name"].strip(), email, phone, data.get("state", "").strip(), hashed))
        
        # Email bhejte hain
        if send_verification_email(email, data["first_name"]):
            conn.commit()
            return jsonify({"success": True, "message": "Verification link email par bhej diya gaya hai!"}), 201
        else:
            return jsonify({"success": False, "message": "Email nahi bheja ja saka, details check karein"}), 500

    except Exception as e:
        if "UNIQUE" in str(e):
            return jsonify({"success": False, "message": "Email ya Phone pehle se registered hai"}), 409
        print(f"Error: {e}") # Debugging ke liye terminal mein error dikhega
        return jsonify({"success": False, "message": "Server error"}), 500
    finally:
        conn.close()

# ── GET /api/auth/confirm/<token> ─────────────────────────────────────────────

@auth_bp.route("/confirm/<token>")
def confirm_email(token):
    serializer = _get_serializer()
    try:
        # 1 hour validity check
        email = serializer.loads(token, salt='email-confirm', max_age=3600) 
    except Exception:
        # Error Page (Agar link expire ho jaye)
        return """
        <div style="text-align:center; margin-top:100px; font-family: 'Segoe UI', sans-serif;">
            <h1 style="color:#d9534f;">Link Expired! ❌</h1>
            <p style="color:#666;">Yeh link purana ho gaya hai ya galat hai. Kripya dobara signup karein ya naya link mangwayein.</p>
            <a href="/" style="color:#5cb85c; text-decoration:none; font-weight:bold;">Wapas Home Par Jayein</a>
        </div>
        """, 400

    # Database Update
    conn = get_db()
    conn.execute("UPDATE users SET is_verified = 1 WHERE email = ?", (email,))
    conn.commit()
    conn.close()

    # Sundar Success Page (Verification ke baad)
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Account Verified | KrushiCare</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f0fdf4; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
            .card { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 15px 35px rgba(0,0,0,0.1); text-align: center; max-width: 450px; width: 90%; border-top: 8px solid #22c55e; }
            .icon-circle { background-color: #dcfce7; width: 80px; height: 80px; border-radius: 50%; display: flex; justify-content: center; align-items: center; margin: 0 auto 20px; }
            .icon { font-size: 40px; color: #22c55e; }
            h1 { color: #166534; margin-bottom: 10px; font-size: 24px; }
            p { color: #4b5563; margin-bottom: 30px; line-height: 1.6; font-size: 16px; }
            .btn { background-color: #22c55e; color: white; padding: 14px 30px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block; transition: all 0.3s ease; box-shadow: 0 4px 6px rgba(34, 197, 94, 0.2); }
            .btn:hover { background-color: #16a34a; transform: translateY(-2px); box-shadow: 0 6px 12px rgba(34, 197, 94, 0.3); }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="icon-circle">
                <span class="icon">✔</span>
            </div>
            <h1>Account Verified!</h1>
            <p>Mubarak ho! Aapka email successfully verify ho gaya hai. Ab aap KrushiCare ke sabhi features ka upyog kar sakte hain.</p>
            <a href="http://127.0.0.1:5000/login" class="btn">Login Karein</a>
        </div>
    </body>
    </html>
    """

# ── POST /api/auth/login ──────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    identifier = (data.get("email_or_phone") or data.get("email") or data.get("phone") or "").strip().lower()
    pwd = data.get("password", "")

    if not identifier or not pwd:
        return jsonify({"success": False, "message": "Details fill karein"}), 400

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ? OR phone = ?", (identifier, identifier)).fetchone()
    conn.close()

    if not user or not bcrypt.checkpw(pwd.encode(), user["password"].encode()):
        return jsonify({"success": False, "message": "Galat email/phone ya password"}), 401

    if user["is_verified"] == 0:
        return jsonify({"success": False, "message": "Pehle apna email verify karein!"}), 403

    return jsonify({
        "success": True,
        "token": _make_token(user["id"], user["email"]),
        "user": {"id": user["id"], "first_name": user["first_name"], "email": user["email"]}
    })

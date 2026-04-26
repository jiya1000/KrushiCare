"""
KrushiCare — Flask Backend
"""
from flask import Flask, send_file
from flask_cors import CORS
from database import init_db
from auth import auth_bp
from routes import api_bp
import os

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "krushicare-secret-2025")

CORS(app, resources={r"/api/*": {"origins": "*"}})

app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(api_bp, url_prefix="/api")

@app.route("/")
def index():
    return send_file("frontend.html")

with app.app_context():
    init_db()

if __name__ == "__main__":
    print("\n✅ KrushiCare backend chal raha hai → http://localhost:5000\n")
    app.run(debug=True, port=5000)

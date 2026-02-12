from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_mail import Mail
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- CONFIGURATION ---
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- EMAIL CONFIGURATION ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')

# --- INITIALIZE EXTENSIONS ---

# 1. DATABASE & MIGRATIONS
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# 2. CORS (UPDATED FOR VERCEL)
# This allows: Localhost, Your Main Domain, and ANY Vercel Preview URL
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "http://localhost:3000",
            "https://frn-nigeria.vercel.app",
            "https://food-rescue-network.vercel.app"
        ],
        # The line below allows your partner's long preview URLs to work automatically
        "origin_regex": r"https://.*\.vercel\.app.*",
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# 3. AUTH & MAIL
jwt = JWTManager(app)
mail = Mail(app)

# --- IMPORT ROUTES ---
# We import routes at the bottom to avoid circular import errors
from routes import *

if __name__ == "__main__":
    app.run(debug=True)
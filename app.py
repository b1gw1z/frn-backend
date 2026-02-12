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
db = SQLAlchemy(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)
mail = Mail(app)

# --- CORS CONFIGURATION (THE FIX) ---
# We changed "/api/*" to "/*" to match ALL routes.
CORS(app, resources={
    r"/*": {
        "origins": [
            "http://localhost:3000",              # Local Development
            "https://frn-nigeria.vercel.app",     # Main Production Domain
            "https://food-rescue-network.vercel.app" # Old Domain (Optional)
        ],
        # ---------------------------------------------------------
        # THE FIX: Allow any Vercel Preview URL using Regex
        # This matches https://ANYTHING.vercel.app
        # ---------------------------------------------------------
        "origin_regex": r"https://.*\.vercel\.app.*", 
        
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
        "supports_credentials": True
    }
})

# --- IMPORT ROUTES ---
from routes import *

if __name__ == "__main__":
    app.run(debug=True)
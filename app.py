from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_mail import Mail
import os
from dotenv import load_dotenv
import re  
from flask_socketio import SocketIO
from datetime import timedelta

load_dotenv()

app = Flask(__name__)

# --- CONFIGURATION ---
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback-secret-key')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(minutes=25)

# --- EMAIL CONFIGURATION ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')

socketio = SocketIO(app, cors_allowed_origins="*")

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
            "http://localhost:3000",
            "https://frn-nigeria.vercel.app",
            "https://food-rescue-network.vercel.app",
            
            # THE FIX: This allows ANY Vercel Preview URL securely
            re.compile(r"^https://.*\.vercel\.app$") 
        ],
        "methods": ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
        "supports_credentials": True
    }
})

# --- IMPORT ROUTES ---
from routes import *

if __name__ == "__main__":
    socketio.run(app, debug=True)
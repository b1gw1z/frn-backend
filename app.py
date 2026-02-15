from flask import Flask
from flask_cors import CORS
import os
from dotenv import load_dotenv
import re
from datetime import timedelta

# 1. IMPORT EXTENSIONS (From your new extensions.py file)
from extensions import db, migrate, jwt, mail, socketio, scheduler
from scheduler import init_scheduler 

load_dotenv()

def create_app():
    """
    The Application Factory.
    Creates and configures the app, but does not run it.
    """
    app = Flask(__name__)

    # --- CONFIGURATION ---
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')
    # Fix Postgres URL for SQLAlchemy
    database_url = os.getenv('DATABASE_URL')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://")
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    
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

    # --- INITIALIZE EXTENSIONS ---
    # We attach the tools to this specific app instance
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    mail.init_app(app)
    socketio.init_app(app)
    # Note: We init scheduler here, but start it in __main__
    scheduler.init_app(app) 

    # --- CORS CONFIGURATION ---
    CORS(app, resources={
        r"/*": {
            "origins": [
                "http://localhost:3000",
                "https://frn-nigeria.vercel.app",
                "https://food-rescue-network.vercel.app",
                re.compile(r"^https://.*\.vercel\.app$") 
            ],
            "methods": ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
            "supports_credentials": True
        }
    })

    # --- REGISTER BLUEPRINTS ---
    # Import inside the function to avoid circular imports
    from routes.auth import auth_bp
    from routes.donations import donations_bp
    from routes.admin import admin_bp
    from routes.user import user_bp
    from routes.messaging import messaging_bp
    from routes.moderation import moderation_bp
    from routes.tickets import tickets_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(donations_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(messaging_bp)
    app.register_blueprint(moderation_bp)
    app.register_blueprint(tickets_bp)

    return app

# --- ENTRY POINT ---
# This only runs if you type 'python app.py'
if __name__ == "__main__":
    app = create_app()
    
    # Start the Scheduler only when running the server (not during tests)
    # We call the function from scheduler.py which starts the job
    scheduler.start()
    print("⏰ Scheduler Started...")
    
    socketio.run(app, debug=True)
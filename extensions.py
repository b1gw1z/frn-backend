from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_mail import Mail
from flask_socketio import SocketIO
from flask_apscheduler import APScheduler

# Initialize them WITHOUT the 'app' variable
db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
mail = Mail()
socketio = SocketIO(cors_allowed_origins="*")
scheduler = APScheduler()
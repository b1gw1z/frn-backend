from flask import Flask
from config import Config
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager 
from models import db, User, Donation, Claim

app = Flask(__name__)
app.config.from_object(Config)

jwt = JWTManager(app)

db.init_app(app)
migrate = Migrate(app, db)

from routes import *

if __name__ == '__main__':
    app.run(debug=True)
import sys
import os
import pytest

# 1. Add the parent directory to Python's path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 2. NOW import from app
# NOTE: If your app.py does not have a 'create_app' function, change this to:
# from app import app as flask_app 
from app import create_app 
from extensions import db

@pytest.fixture
def app():
    """Create and configure a new app instance for each test."""
    app = create_app()
    
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "JWT_SECRET_KEY": "test-secret"
    })

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()
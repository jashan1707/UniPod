# Entry point for your Flask app
from flask import Flask
from routes.auth_routes import auth_bp
from routes.upload_routes import upload_bp
from routes.podcast_routes import podcast_bp
from flask_login import LoginManager
import os

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "your-dev-secret")

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(upload_bp)
app.register_blueprint(podcast_bp)

# Login setup
login_manager = LoginManager()
login_manager.login_view = 'auth_bp.login'
login_manager.init_app(app)

from utils.auth_utils import load_user
login_manager.user_loader(load_user)

@app.route('/')
def home():
    return '<h1>Welcome to UniPod</h1><p><a href="/login">Login</a> or <a href="/register">Register</a></p>'

if __name__ == '__main__':
    app.run(debug=True)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

users = {}  # Placeholder for a DB

class User(UserMixin):
    def __init__(self, id, email, password_hash):
        self.id = id
        self.email = email
        self.password_hash = password_hash

def get_user_by_email(email):
    return users.get(email)

def create_user(email, password):
    if email in users:
        return None
    users[email] = User(email, email, generate_password_hash(password))
    return users[email]

def check_password(user, password):
    return check_password_hash(user.password_hash, password)

def load_user(user_id):
    for user in users.values():
        if user.id == user_id:
            return user
    return None

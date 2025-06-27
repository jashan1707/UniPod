from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from utils.auth_utils import get_user_by_email, create_user, check_password

auth_bp = Blueprint('auth_bp', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = get_user_by_email(request.form['email'])
        if user and check_password(user, request.form['password']):
            login_user(user)
            return redirect(url_for('upload_bp.upload'))
        flash("Invalid login")
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if create_user(request.form['email'], request.form['password']):
            return redirect(url_for('auth_bp.login'))
        flash("User already exists")
    return render_template('register.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth_bp.login'))

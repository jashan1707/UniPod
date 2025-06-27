from flask import Blueprint, render_template
from flask_login import login_required, current_user

podcast_bp = Blueprint('podcast_bp', __name__)

@podcast_bp.route('/my-podcasts')
@login_required
def my_podcasts():
    # Placeholder until DB is hooked up
    return render_template('my_podcasts.html', podcasts=[])

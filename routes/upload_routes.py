from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_required, current_user
from services.ocr_service import extract_text_from_pdf
from services.llm_service import generate_script
from services.audio_service import generate_audio
from services.s3_service import upload_to_s3

upload_bp = Blueprint('upload_bp', __name__)

@upload_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        pdf = request.files['pdf']
        playlist = request.form.get('playlist')
        text = extract_text_from_pdf(pdf)
        script = generate_script(text)
        audio_path = generate_audio(script)
        s3_url = upload_to_s3(audio_path, current_user.id, playlist)
        return redirect(url_for('podcast_bp.my_podcasts'))
    return render_template('upload.html')

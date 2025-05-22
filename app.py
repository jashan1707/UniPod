import os
import re
import uuid
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv
from datetime import datetime
from pytz import timezone
from babel.dates import format_datetime
from pdf2image import convert_from_bytes
import pytesseract
import requests
from TTS.api import TTS
from pydub import AudioSegment
import boto3

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SECRET_KEY'] = os.getenv("FLASK_SECRET_KEY", "dev-secret")
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

uk = timezone("Europe/London")
def format_uk_time(dt):
    return format_datetime(dt.astimezone(uk), format='short')
app.jinja_env.filters['format_uk_time'] = format_uk_time

xtts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2")

def generate_script_with_ollama(prompt):
    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "llama3",
            "stream": False,
            "messages": [
                {"role": "system", "content": "You are a podcast scriptwriter. Your job is to turn content into a fun and engaging conversation between two hosts. Keep it casual, clear, and podcast-style. The first host usually starts."},
                {"role": "user", "content": prompt}
            ]
        }
    )
    return response.json()['message']['content']

def split_script_by_speaker(script_text, host1_name, host2_name):
    lines = script_text.strip().split("\n")
    dialogue = []
    for line in lines:
        match = re.match(rf"^({re.escape(host1_name)}|{re.escape(host2_name)}):\s*(.*)", line.strip())
        if match:
            speaker = match.group(1)
            text = match.group(2)
            dialogue.append({"speaker": speaker, "text": text})
    return dialogue

def upload_to_s3(file_path, filename):
    s3 = boto3.client(
        's3',
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION")
    )
    bucket_name = os.getenv("AWS_S3_BUCKET")
    with open(file_path, "rb") as f:
        s3.upload_fileobj(f, bucket_name, filename, ExtraArgs={"ContentType": "audio/mpeg"})
    s3_url = f"https://{bucket_name}.s3.{os.getenv('AWS_REGION')}.amazonaws.com/{filename}"
    return s3_url

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class Podcast(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200))
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlist.id'))
    script = db.Column(db.Text)
    audio_file = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Playlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    podcasts = db.relationship('Podcast', backref='playlist', lazy=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        new_user = User(
            username=request.form['username'],
            password=request.form['password']
        )
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)  # Automatically log in after registration
        return redirect(url_for('upload'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.password == request.form['password']:
            login_user(user)
            return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        selected_playlist_id = request.form.get('playlist')
        new_playlist_name = request.form.get('new_playlist', '').strip()

        playlist_id = None
        if new_playlist_name:
            # Check if this playlist already exists for the user
            existing = Playlist.query.filter_by(name=new_playlist_name, user_id=current_user.id).first()
            if existing:
                playlist_id = existing.id
            else:
                new_playlist = Playlist(name=new_playlist_name, user_id=current_user.id)
                db.session.add(new_playlist)
                db.session.commit()
                playlist_id = new_playlist.id
        elif selected_playlist_id:
            playlist_id = int(selected_playlist_id)

        file = request.files.get('pdf')
        host1_name = request.form.get('host1_name', 'Jordan').strip()
        host2_name = request.form.get('host2_name', 'Taylor').strip()
        jordan_voice_file = request.form.get('jordan_voice')
        taylor_voice_file = request.form.get('taylor_voice')

        jordan_upload = request.files.get('jordan_custom_wav')
        taylor_upload = request.files.get('taylor_custom_wav')

        temp_dir = "temp"
        os.makedirs(temp_dir, exist_ok=True)

        jordan_voice_path = os.path.join("voices", jordan_voice_file)
        taylor_voice_path = os.path.join("voices", taylor_voice_file)

        if jordan_upload and jordan_upload.filename.lower().endswith(".wav"):
            jordan_voice_path = os.path.join(temp_dir, "jordan_custom.wav")
            jordan_upload.save(jordan_voice_path)

        if taylor_upload and taylor_upload.filename.lower().endswith(".wav"):
            taylor_voice_path = os.path.join(temp_dir, "taylor_custom.wav")
            taylor_upload.save(taylor_voice_path)

        if file and file.filename.endswith('.pdf'):
            images = convert_from_bytes(file.read())
            extracted_text = ""
            for img in images:
                extracted_text += pytesseract.image_to_string(img)

            prompt = f"Turn this extracted text into a casual, engaging podcast dialogue between two hosts named {host1_name} and {host2_name}. Alternate their lines. Avoid technical jargon unless it's explained simply.\n\n{extracted_text}"
            try:
                script = generate_script_with_ollama(prompt)
                segments = split_script_by_speaker(script, host1_name, host2_name)
            except Exception as e:
                return f"Script generation error: {str(e)}", 500

            final_audio = AudioSegment.empty()
            os.makedirs(temp_dir, exist_ok=True)
            try:
                for i, seg in enumerate(segments):
                    speaker_file = jordan_voice_path if seg['speaker'] == host1_name else taylor_voice_path
                    temp_path = os.path.join(temp_dir, f"chunk_{i}.wav")
                    xtts.tts_to_file(text=seg['text'], file_path=temp_path, speaker_wav=speaker_file, language="en")
                    final_audio += AudioSegment.from_wav(temp_path)
                    os.remove(temp_path)

                final_filename = f"audio_{uuid.uuid4().hex}.mp3"
                final_path = os.path.join(temp_dir, final_filename)
                final_audio.export(final_path, format="mp3")
                audio_url = upload_to_s3(final_path, final_filename)
                os.remove(final_path)

                if os.path.exists(os.path.join(temp_dir, "jordan_custom.wav")):
                    os.remove(os.path.join(temp_dir, "jordan_custom.wav"))
                if os.path.exists(os.path.join(temp_dir, "taylor_custom.wav")):
                    os.remove(os.path.join(temp_dir, "taylor_custom.wav"))
            except Exception as e:
                return f"Audio generation error: {str(e)}", 500

            podcast = Podcast(
            user_id=current_user.id,
            title="AI Generated Podcast",
            script=script,
            audio_file=audio_url,
            playlist_id=playlist_id  # Link to the playlist if any
        )

            db.session.add(podcast)
            db.session.commit()

            return render_template('display.html', text=script, audio_file=audio_url)

    playlists = Playlist.query.filter_by(user_id=current_user.id).all()
    return render_template('upload.html', playlists=playlists)


@app.route('/my-podcasts')
@login_required
def my_podcasts():
    podcasts = Podcast.query.filter_by(user_id=current_user.id).order_by(Podcast.created_at.desc()).all()
    return render_template('my_podcasts.html', podcasts=podcasts)

@app.route('/delete_podcast/<int:id>', methods=['POST'])
@login_required
def delete_podcast(id):
    podcast = Podcast.query.get_or_404(id)
    if podcast.user_id != current_user.id:
        return "Unauthorized", 403
    try:
        audio_path = os.path.join("static", podcast.audio_file)
        if os.path.exists(audio_path):
            os.remove(audio_path)
    except Exception as e:
        print(f"Warning: failed to delete audio file: {e}")
    db.session.delete(podcast)
    db.session.commit()
    return redirect(url_for('my_podcasts'))

@app.route('/rename_podcast/<int:id>', methods=['POST'])
@login_required
def rename_podcast(id):
    podcast = Podcast.query.get_or_404(id)
    if podcast.user_id != current_user.id:
        return "Unauthorized", 403
    new_title = request.form.get('new_title')
    if new_title:
        podcast.title = new_title
        db.session.commit()
    return redirect(url_for('my_podcasts'))

@app.route('/playlists')
@login_required
def playlists():
    user_playlists = Playlist.query.filter_by(user_id=current_user.id).all()
    return render_template('playlists.html', playlists=user_playlists)

@app.route('/rename_playlist/<int:id>', methods=['POST'])
@login_required
def rename_playlist(id):
    playlist = Playlist.query.get_or_404(id)
    if playlist.user_id != current_user.id:
        return "Unauthorized", 403

    new_name = request.form.get('new_name')
    if new_name:
        playlist.name = new_name
        db.session.commit()

    return redirect(url_for('playlists'))

@app.route('/delete_playlist/<int:id>', methods=['POST'])
@login_required
def delete_playlist(id):
    playlist = Playlist.query.get_or_404(id)
    if playlist.user_id != current_user.id:
        return "Unauthorized", 403

    if playlist.podcasts:
        return "Cannot delete a playlist that still has podcasts.", 400

    db.session.delete(playlist)
    db.session.commit()
    return redirect(url_for('playlists'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

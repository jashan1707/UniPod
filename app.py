import os
import re
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv
from pytz import timezone
from babel.dates import format_datetime
from pdf2image import convert_from_bytes
import pytesseract
import requests
from pydub import AudioSegment
import boto3

from TTS.api import TTS
xtts = TTS(
    model_name="tts_models/multilingual/multi-dataset/xtts_v2",
    gpu=False
).to("cpu")

# Setup Flask
load_dotenv()
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SECRET_KEY'] = os.getenv("FLASK_SECRET_KEY", "dev-secret")

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

uk = timezone("Europe/London")
app.jinja_env.filters['format_uk_time'] = lambda dt: format_datetime(dt.astimezone(uk), format='short')

# === MODELS ===

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class Playlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    podcasts = db.relationship('Podcast', backref='playlist', lazy=True)

class Podcast(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200))
    script = db.Column(db.Text)
    audio_file = db.Column(db.String(200))
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlist.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# === HELPERS ===

def generate_script(prompt):
    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "llama3",
            "stream": False,
            "messages": [
                {"role": "system", "content": "You are a podcast scriptwriter. Make this a friendly chat between two hosts."},
                {"role": "user", "content": prompt}
            ]
        }
    )
    return response.json()['message']['content']

def split_script(script, host1, host2):
    lines = script.strip().split("\n")
    result = []
    for line in lines:
        match = re.match(rf"^({re.escape(host1)}|{re.escape(host2)}):\s*(.*)", line)
        if match:
            result.append({"speaker": match.group(1), "text": match.group(2)})
    return result

def upload_to_s3(file_path, filename):
    s3 = boto3.client(
        's3',
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION")
    )
    bucket = os.getenv("AWS_S3_BUCKET")
    with open(file_path, "rb") as f:
        s3.upload_fileobj(f, bucket, filename, ExtraArgs={"ContentType": "audio/mpeg"})
    return f"https://{bucket}.s3.{os.getenv('AWS_REGION')}.amazonaws.com/{filename}"

# === ROUTES ===

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        new_user = User(username=request.form['username'], password=request.form['password'])
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
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
    if request.method == 'GET':
        playlists = Playlist.query.filter_by(user_id=current_user.id).all()
        return render_template('upload.html', playlists=playlists)

    # POST logic
    host1 = request.form.get('host1_name', 'Jordan').strip()
    host2 = request.form.get('host2_name', 'Taylor').strip()
    file = request.files.get('pdf')
    jordan_file = request.files.get('jordan_custom_wav')
    taylor_file = request.files.get('taylor_custom_wav')
    playlist_id = request.form.get("playlist")
    new_playlist_name = request.form.get("new_playlist", "").strip()

    # Create temp dir
    temp_dir = "temp"
    os.makedirs(temp_dir, exist_ok=True)

    # Determine voice paths (default or uploaded)
    jordan_voice_path = "voices/jordan.wav"
    taylor_voice_path = "voices/taylor.wav"

    if jordan_file and jordan_file.filename:
        jordan_voice_path = os.path.join(temp_dir, "jordan_custom.wav")
        jordan_file.save(jordan_voice_path)

    if taylor_file and taylor_file.filename:
        taylor_voice_path = os.path.join(temp_dir, "taylor_custom.wav")
        taylor_file.save(taylor_voice_path)

    # OCR from PDF
    images = convert_from_bytes(file.read())
    text = "".join([pytesseract.image_to_string(img) for img in images])

    # Prompt and script
    prompt = f"Create a podcast dialogue between {host1} and {host2}:\n\n{text}"
    script = generate_script(prompt)
    segments = split_script(script, host1, host2)

    # TTS synthesis
    audio = AudioSegment.empty()
    for i, seg in enumerate(segments):
        speaker_path = jordan_voice_path if seg['speaker'] == host1 else taylor_voice_path
        chunk_path = os.path.join(temp_dir, f"chunk_{i}.wav")
        xtts.tts_to_file(
            text=seg['text'],
            speaker_wav=speaker_path,
            language="en",
            file_path=chunk_path
        )
        audio += AudioSegment.from_wav(chunk_path)
        os.remove(chunk_path)

    # Export MP3
    mp3_name = f"podcast_{uuid.uuid4().hex}.mp3"
    mp3_path = os.path.join(temp_dir, mp3_name)
    audio.export(mp3_path, format="mp3")
    url = upload_to_s3(mp3_path, mp3_name)
    os.remove(mp3_path)

    # Remove temp voices if used
    if os.path.exists(jordan_voice_path) and jordan_voice_path.startswith(temp_dir):
        os.remove(jordan_voice_path)
    if os.path.exists(taylor_voice_path) and taylor_voice_path.startswith(temp_dir):
        os.remove(taylor_voice_path)

    # Playlist handling
    if new_playlist_name:
        new_playlist = Playlist(name=new_playlist_name, user_id=current_user.id)
        db.session.add(new_playlist)
        db.session.commit()
        playlist_id = new_playlist.id

    # Save podcast
    podcast = Podcast(
        user_id=current_user.id,
        title="AI Podcast",
        script=script,
        audio_file=url,
        playlist_id=playlist_id if playlist_id else None
    )
    db.session.add(podcast)
    db.session.commit()

    return render_template('display.html', text=script, audio_file=url)


@app.route('/my-podcasts')
@login_required
def my_podcasts():
    podcasts = Podcast.query.filter_by(user_id=current_user.id).order_by(Podcast.created_at.desc()).all()
    return render_template('my_podcasts.html', podcasts=podcasts)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

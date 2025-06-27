import os
import uuid
from datetime import datetime

def generate_unique_filename(extension=".mp3"):
    return f"{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex}{extension}"

def get_user_upload_path(user_id, filename):
    base_dir = "user_uploads"
    path = os.path.join(base_dir, str(user_id))
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, filename)

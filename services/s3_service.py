import boto3
import os
from datetime import datetime

s3 = boto3.client('s3')

def upload_to_s3(file_path, user_id, playlist):
    bucket = os.environ['AWS_BUCKET']
    filename = f"{user_id}/{playlist}/{datetime.utcnow().isoformat()}.mp3"
    s3.upload_file(file_path, bucket, filename)
    return f"s3://{bucket}/{filename}"

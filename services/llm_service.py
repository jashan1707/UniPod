import requests
import json

def generate_script(content):
    response = requests.post("http://localhost:11434/api/chat", json={
        "model": "llama3",
        "messages": [
            {"role": "user", "content": f"Create a podcast-style conversation between Jordan and Taylor about:\n{content}"}
        ]
    })
    result = response.json()
    return result.get("message", {}).get("content", "")

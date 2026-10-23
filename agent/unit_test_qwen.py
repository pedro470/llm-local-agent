import requests
from tools import TOOLS_SCHEMA, AVAILABLE_TOOLS

request = requests.post("http://localhost:11434/api/chat", json={"model": "qwen3.5:9b", "messages": [{"role": "user", "content": "Olá! Como você está?"}], 'stream': False, 'tools': TOOLS_SCHEMA, 'tools_choice': 'auto'})
print(request.json())
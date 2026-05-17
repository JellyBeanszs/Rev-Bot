import os
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Project Rev RP Bot is Alive and Running 24/7!"

def run():
    # FIXED: Automatically uses Render's assigned port (defaulting to 10000)
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

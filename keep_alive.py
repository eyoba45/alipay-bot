import os
import logging
from flask import Flask
from threading import Thread

# Suppress all Flask logging
logging.getLogger('werkzeug').disabled = True

app = Flask('keep_alive')

@app.route('/')
def home():
    return "Bot is alive"

@app.route('/ping')
def ping():
    return "pong"

def run():
    app.run(host='0.0.0.0', port=5000)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
    return True

if __name__ == "__main__":
    keep_alive()
    while True:
        import time
        time.sleep(3600)

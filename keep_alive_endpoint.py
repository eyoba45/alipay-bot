from flask import Flask
import threading
import logging
import os

# Configure Flask app
app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/ping')
def ping():
    return "pong"

def run():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def keep_alive():
    server = threading.Thread(target=run)
    server.daemon = True
    server.start()

if __name__ == "__main__":
    import os
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
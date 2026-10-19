# c:/Users/Kacper/Desktop/skrypt/wsgi.py
# WSGI entry point for Cloud Deployment (Render.com, Railway.app, PythonAnywhere, etc.)
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app_dir = os.path.join(BASE_DIR, "app")
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

from app.admin_server import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

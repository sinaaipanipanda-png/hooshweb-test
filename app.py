from flask import Flask
import os
from datetime import datetime

app = Flask(__name__)

@app.route("/")
def home():
    return """
    <html>
    <head>
        <meta charset="UTF-8">
        <title>HUSHWEB TEST</title>
    </head>
    <body style="background:#101827;color:white;text-align:center;padding:60px;font-family:Arial">
        <h1>🚀 HUSHWEB TEST</h1>
        <h2>Render is ONLINE!</h2>
        <p>ربات هوش وب یار آماده میزبانی است 💙</p>
        <p>وضعیت: فعال ✅</p>
    </body>
    </html>
    """

@app.route("/health")
def health():
    return {
        "status": "online",
        "project": "HUSHWEB TEST",
        "time": datetime.now().isoformat()
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

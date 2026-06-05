import requests
import threading
import time
import re
from flask import Flask, request

BOARD = "pol"
REFRESH_SECONDS = 300 
app = Flask(__name__)

stats = {"last_update": "Never", "threads": []}

def clean_text(text):
    if not text: return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
    text = text.replace("&#039;", "'").replace("&quot;", '"')
    return " ".join(text.split())

def analyze():
    global stats
    while True:
        try:
            catalog = requests.get(f"https://a.4cdn.org/{BOARD}/catalog.json", timeout=30).json()
            thread_list = []
            for page in catalog:
                for t in page["threads"]:
                    sub = clean_text(t.get("sub", ""))
                    com = clean_text(t.get("com", ""))
                    thread_list.append({
                        "id": t["no"],
                        "summary": sub if sub else (com[:100] + "..."),
                        "replies": t.get("replies", 0)
                    })
            thread_list.sort(key=lambda x: x["replies"], reverse=True)
            stats = {"last_update": time.strftime("%Y-%m-%d %H:%M:%S"), "threads": thread_list[:50]}
        except Exception as e: print(e)
        time.sleep(REFRESH_SECONDS)

@app.route("/")
def home():
    rows = ""
    for idx, t in enumerate(stats["threads"], 1):
        rows += f"""
        <div style="background:#f0e0d6; border:1px solid #d9bfb7; margin:5px; padding:5px;">
            <b>{idx}.</b> 
            <a href="https://boards.4chan.org/{BOARD}/thread/{t['id']}" target="_blank" style="color:#0f0c5d; text-decoration:none;">
                {t['summary']}
            </a> 
            <span style="color:#af0a0f;">({t['replies']} replies)</span>
        </div>"""
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>/{BOARD}/ Catalog</title>
        <style>
            body {{ font-family: arial,helvetica,sans-serif; font-size: 13px; background:#d6daf0; }}
            h1 {{ color:#af0a0f; font-size: 20px; margin: 10px; }}
        </style>
    </head>
    <body>
        <h1>/{BOARD}/ - Active Threads</h1>
        <p>Last Update: {stats['last_update']}</p>
        {rows}
    </body>
    </html>
    """

if __name__ == "__main__":
    threading.Thread(target=analyze, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
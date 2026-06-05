import requests
import threading
import time
import re
from collections import Counter

from flask import Flask

import spacy

# ----------------------------
# Configuration
# ----------------------------

BOARD = "pol"
REFRESH_SECONDS = 300  # 5 minutes

# ----------------------------
# Flask
# ----------------------------

app = Flask(__name__)

# ----------------------------
# NLP
# ----------------------------

print("[*] Loading spaCy...")
nlp = spacy.load("en_core_web_sm")

# ----------------------------
# Shared State
# ----------------------------

stats = {
    "last_update": "Never",
    "threads": 0,
    "posts": 0,
    "topics": [],
    "top_posts": []
}

# ----------------------------
# Utilities
# ----------------------------

TAG_RE = re.compile(r"<[^>]+>")
URL_RE = re.compile(r"https?://\S+")

def clean_text(text):
    if not text:
        return ""

    text = TAG_RE.sub(" ", text)
    text = URL_RE.sub(" ", text)

    text = (
        text.replace("&gt;", " ")
            .replace("&lt;", " ")
            .replace("&amp;", " ")
            .replace("&#039;", "'")
            .replace("&quot;", '"')
    )

    text = re.sub(r"\s+", " ", text)

    return text.strip()

# ----------------------------
# 4chan Fetching
# ----------------------------

def fetch_catalog():
    url = f"https://a.4cdn.org/{BOARD}/catalog.json"
    return requests.get(url, timeout=30).json()

def fetch_thread(thread_id):
    url = f"https://a.4cdn.org/{BOARD}/thread/{thread_id}.json"

    try:
        return requests.get(url, timeout=30).json()
    except Exception:
        return None

# ----------------------------
# Topic Extraction
# ----------------------------

def extract_topics(posts):
    counter = Counter()

    # nlp.pipe processes a collection of texts efficiently without creating one massive string
    # disable=["parser", "ner"] speeds up processing dramatically since you only need POS tags
    docs = nlp.pipe(posts, disable=["parser", "ner"], batch_size=256)

    for doc in docs:
        for token in doc:
            if (
                token.pos_ in ("NOUN", "PROPN")
                and not token.is_stop
                and token.is_alpha
                and len(token.text) > 2
            ):
                counter[token.lemma_.lower()] += 1

    return counter.most_common(50)

# ----------------------------
# Analyzer Loop
# ----------------------------

def analyze():
    global stats

    while True:
        try:
            print("[*] Loading catalog...")

            catalog = fetch_catalog()

            thread_ids = []

            for page in catalog:
                for thread in page["threads"]:
                    thread_ids.append(thread["no"])

            all_posts = []
            sample_posts = []

            total_posts = 0

            print(f"[*] Found {len(thread_ids)} threads")

            for i, thread_id in enumerate(thread_ids):

                if i % 25 == 0:
                    print(
                        f"[*] Thread {i}/{len(thread_ids)}"
                    )

                data = fetch_thread(thread_id)

                if not data:
                    continue

                for post in data.get("posts", []):
                    text = clean_text(
                        post.get("com", "")
                    )

                    if not text:
                        continue

                    all_posts.append(text)

                    if len(sample_posts) < 25:
                        sample_posts.append(text[:300])

                    total_posts += 1

            print(
                f"[*] Processing {total_posts} posts..."
            )

            topics = extract_topics(all_posts)

            stats = {
                "last_update": time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "threads": len(thread_ids),
                "posts": total_posts,
                "topics": topics,
                "top_posts": sample_posts,
            }

            print("[+] Update complete")

        except Exception as e:
            print("[!] Error:", e)

        time.sleep(REFRESH_SECONDS)

# ----------------------------
# Dashboard
# ----------------------------

@app.route("/")
def home():

    rows = ""

    for topic, count in stats["topics"]:
        rows += f"""
        <tr>
            <td>{topic}</td>
            <td>{count}</td>
        </tr>
        """

    post_html = ""

    for post in stats["top_posts"]:
        post_html += f"""
        <div class="post">
            {post}
        </div>
        """

    return f"""
<!DOCTYPE html>
<html>
<head>
<title>/pol/ Analyzer</title>

<meta http-equiv="refresh" content="60">

<style>
body {{
    background:#111;
    color:#ddd;
    font-family:Arial;
    margin:30px;
}}

h1 {{
    color:#ffcc00;
}}

.card {{
    background:#1c1c1c;
    padding:15px;
    margin-bottom:20px;
    border-radius:8px;
}}

table {{
    width:100%;
    border-collapse:collapse;
}}

td,th {{
    border-bottom:1px solid #333;
    padding:8px;
}}

.post {{
    padding:8px;
    margin-bottom:8px;
    background:#222;
    border-left:4px solid #ffcc00;
}}
</style>

</head>

<body>

<h1>/pol/ Trending Topics</h1>

<div class="card">
<b>Last Update:</b> {stats["last_update"]}<br>
<b>Threads:</b> {stats["threads"]}<br>
<b>Posts:</b> {stats["posts"]}
</div>

<div class="card">
<h2>Top Topics</h2>

<table>
<tr>
<th>Topic</th>
<th>Count</th>
</tr>

{rows}

</table>
</div>

<div class="card">
<h2>Sample Posts</h2>
{post_html}
</div>

</body>
</html>
"""

# ----------------------------
# Main
# ----------------------------

if __name__ == "__main__":

    thread = threading.Thread(
        target=analyze,
        daemon=True
    )

    thread.start()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
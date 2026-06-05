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
REFRESH_SECONDS = 300 

# ----------------------------
# Flask & NLP Setup
# ----------------------------

app = Flask(__name__)

print("[*] Loading spaCy...")
nlp = spacy.load("en_core_web_sm", disable=["ner"])

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
        time.sleep(0.2) 
        return requests.get(url, timeout=30).json()
    except Exception:
        return None

# ----------------------------
# Topic Ranker & Metric Engine
# ----------------------------

def extract_topics(posts):
    phrase_counter = Counter()
    
    docs = nlp.pipe(posts, batch_size=256)
    
    GENERIC_SINGLE_WORDS = {
        "people", "shit", "thing", "year", "time", "way", "guy", "day", 
        "life", "lot", "point", "job", "reason", "problem", "thread", 
        "post", "anon", "kek", "lol", "something", "anything", "nothing",
        "man", "woman", "kid", "child", "someone", "everyone", "fuck", "retard"
    }

    # Step 1: Discover structural noun phrase clusters
    for doc in docs:
        for chunk in doc.noun_chunks:
            words = []
            for t in chunk:
                if t.is_stop:
                    continue
                lemma = t.lemma_.lower().strip()
                if lemma:
                    words.append(lemma)
            
            clean_phrase = " ".join(words).strip()
            
            if not clean_phrase or not all(w.isalpha() for w in words):
                continue
                
            if clean_phrase in GENERIC_SINGLE_WORDS:
                continue
                
            if len(words) > 3:
                continue

            phrase_counter[clean_phrase] += 1

    # Extract the top 50 topics based on context structure rank
    top_phrases = phrase_counter.most_common(50)
    
    # Step 2: Extract raw corpus string and calculate the total literal mention volume
    full_corpus = " " + " ".join(posts).lower() + " "
    final_topics_data = []
    
    for phrase, context_count in top_phrases:
        if " " in phrase:
            literal_count = full_corpus.count(f" {phrase} ")
        else:
            # Drop trailing 's' if the token string already arrived pluralized from spaCy.
            # This keeps the regex clean as '\bjews?\b' instead of creating double-s bugs like '\bjewss?\b'
            base_word = phrase[:-1] if phrase.endswith('s') and len(phrase) > 3 else phrase
            pattern = re.compile(rf"\b{base_word}s?\b") 
            literal_count = len(pattern.findall(full_corpus))
            
        # Hard boundary fallbacks
        if literal_count < context_count:
            literal_count = context_count
            
        final_topics_data.append((phrase, literal_count))

    return final_topics_data

# ----------------------------
# Analyzer Loop
# ----------------------------

def analyze():
    global stats

    while True:
        try:
            print("[*] Loading catalog...")
            catalog = fetch_catalog()
            thread_ids = [thread["no"] for page in catalog for thread in page["threads"]]

            all_posts = []
            sample_posts = []
            total_posts = 0

            print(f"[*] Found {len(thread_ids)} threads")

            for i, thread_id in enumerate(thread_ids):
                if i % 25 == 0:
                    print(f"[*] Thread {i}/{len(thread_ids)}")

                data = fetch_thread(thread_id)
                if not data:
                    continue

                for post in data.get("posts", []):
                    text = clean_text(post.get("com", ""))
                    if not text:
                        continue

                    all_posts.append(text)
                    if len(sample_posts) < 25:
                        sample_posts.append(text[:300])
                    total_posts += 1

            print(f"[*] Extracting structural lists and literal counts across {total_posts} posts...")
            topics = extract_topics(all_posts)

            local_stats = {
                "last_update": time.strftime("%Y-%m-%d %H:%M:%S"),
                "threads": len(thread_ids),
                "posts": total_posts,
                "topics": topics,
                "top_posts": sample_posts,
            }

            stats = local_stats
            print("[+] Update complete. Clean dataset pushed to dashboard interface!")

        except Exception as e:
            print("[!] Error:", e)

        time.sleep(REFRESH_SECONDS)

# ----------------------------
# Dashboard Route
# ----------------------------

@app.route("/")
def home():
    if stats["last_update"] == "Never":
        return """
<!DOCTYPE html>
<html>
<head>
    <title>/pol/ Analyzer - Updating Metrics</title>
    <meta http-equiv="refresh" content="5">
    <style>body { background:#111; color:#ffcc00; font-family:Arial; margin:50px; text-align:center; }</style>
</head>
<body>
    <h1>/pol/ Analyzer</h1>
    <p>Ranking topics contextually and aggregating absolute text mention analytics... (takes ~60s)</p>
</body>
</html>
"""

    rows = ""
    for topic, literal_count in stats["topics"]:
        rows += f"""
        <tr>
            <td><b>{topic}</b></td>
            <td style="color: #ffcc00; font-weight: bold;">{literal_count}</td>
        </tr>
        """
        
    post_html = "".join(f'<div class="post">{post}</div>' for post in stats["top_posts"])

    return f"""
<!DOCTYPE html>
<html>
<head>
<title>/pol/ Analyzer</title>
<meta http-equiv="refresh" content="60">
<style>
body {{ background:#111; color:#ddd; font-family:Arial; margin:30px; }}
h1 {{ color:#ffcc00; }}
.card {{ background:#1c1c1c; padding:15px; margin-bottom:20px; border-radius:8px; }}
table {{ width:100%; border-collapse:collapse; }}
td,th {{ border-bottom:1px solid #333; padding:10px; text-align:left; }}
th {{ color:#ffcc00; }}
.post {{ padding:8px; margin-bottom:8px; background:#222; border-left:4px solid #ffcc00; }}
</style>
</head>
<body>
<h1>/pol/ Trending Topics</h1>
<div class="card">
<b>Last Update:</b> {stats["last_update"]}<br>
<b>Active Threads Checked:</b> {stats["threads"]}<br>
<b>Total Posts Analyzed:</b> {stats["posts"]}
</div>
<div class="card">
<h2>Top Trending Subject Parameters</h2>
<table>
<tr>
    <th>Topic / Phrase</th>
    <th style="color: #ffcc00;">Total Word Mentions</th>
</tr>
{rows}
</table>
</div>
<div class="card">
<h2>Sample Feed</h2>
{post_html}
</div>
</body>
</html>
"""

if __name__ == "__main__":
    thread = threading.Thread(target=analyze, daemon=True)
    thread.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
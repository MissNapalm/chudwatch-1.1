import requests
import threading
import time
import re
from collections import Counter

from flask import Flask, request
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
    "top_posts": [],
    "raw_posts_pool": []
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

def get_singular_root(word):
    """Returns a standardized singular base string to catch edge-case plurals."""
    if word.endswith('ies') and len(word) > 5:
        return word[:-3] + 'y'
    if word.endswith('s') and not word.endswith('ss') and len(word) > 3:
        return word[:-1]
    return word

def extract_topics(posts):
    phrase_counter = Counter()
    
    docs = nlp.pipe(posts, batch_size=256)
    
    GENERIC_SINGLE_WORDS = {
        "people", "shit", "thing", "year", "time", "way", "guy", "day", 
        "life", "lot", "point", "job", "reason", "problem", "thread", 
        "post", "anon", "kek", "lol", "something", "anything", "nothing",
        "man", "woman", "kid", "child", "someone", "everyone", "fuck", "retard",
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"
    }

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

    top_phrases = phrase_counter.most_common(150)
    full_corpus = " " + " ".join(posts).lower() + " "
    
    seen_normalized_roots = set()
    final_topics_data = []
    
    for phrase, context_count in top_phrases:
        if " " in phrase:
            literal_count = full_corpus.count(f" {phrase} ")
            norm_key = phrase
        else:
            norm_key = get_singular_root(phrase)
            
            if norm_key in seen_normalized_roots:
                continue
                
            pattern = re.compile(rf"\b{norm_key}s?\b") 
            literal_count = len(pattern.findall(full_corpus))
            
        if literal_count < context_count:
            literal_count = context_count
            
        seen_normalized_roots.add(norm_key)
        final_topics_data.append((norm_key, literal_count))

    final_topics_data.sort(key=lambda x: x[1], reverse=True)
    return final_topics_data[:50]

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
                "raw_posts_pool": all_posts 
            }

            stats = local_stats
            print("[+] Update complete. Clean sorted dataset pushed to dashboard interface!")

        except Exception as e:
            print("[!] Error:", e)

        time.sleep(REFRESH_SECONDS)

# ----------------------------
# Dashboard Route
# ----------------------------

@app.route("/")
def home():
    if stats["last_update"] == "Never":
        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>/{BOARD}/ Analyzer - Updating Metrics</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body {{ background: #f0e0d6; color: #800000; font-family: arial,helvetica,sans-serif; margin: 50px; text-align: center; }}
        h1 {{ color: #af0a0f; font-size: 24px; letter-spacing: -2px; margin-bottom: 5px; }}
        p {{ font-size: 13px; color: #000; }}
    </style>
</head>
<body>
    <h1>/{BOARD}/ Trend Analysis Engine</h1>
    <p>Ranking structural concepts and executing raw token parsing patterns... (takes ~60s)</p>
</body>
</html>
"""

    query = request.args.get("q", "").strip()
    active_tab = "search" if query else "trends"

    rows = ""
    for idx, (topic, literal_count) in enumerate(stats["topics"], 1):
        rows += f"""
        <tr>
            <td style="color: #444; font-size: 12px; text-align: center;">{idx}</td>
            <td><span class="subject">{topic}</span></td>
            <td style="color: #af0a0f; font-weight: bold; font-family: monospace; font-size: 14px;">{literal_count}</td>
        </tr>
        """
        
    post_html = ""
    for idx, post in enumerate(stats["top_posts"], 1):
        post_html += f"""
        <div class="post-container">
            <div class="post-meta">
                <span class="poster-name">Anonymous</span> 
                <span class="post-date">{stats["last_update"]}</span> 
                <span class="post-id">No.{100000000 + idx}</span>
            </div>
            <div class="post-body">{post}</div>
        </div>
        """

    search_results_html = ""
    match_count = 0
    if query:
        matching_posts = []
        
        # Check if query is a single word to run singular/plural regex logic
        if " " not in query:
            root_term = get_singular_root(query.lower())
            search_pattern = re.compile(rf"\b{root_term}s?\b", flags=re.IGNORECASE)
        else:
            # Multi-word phrase matches directly matching boundaries
            search_pattern = re.compile(rf"\b{re.escape(query.lower())}\b", flags=re.IGNORECASE)
        
        for post in stats["raw_posts_pool"]:
            matches = search_pattern.findall(post)
            if matches:
                # Increment match count by the total frequency inside this post
                match_count += len(matches)
                
                if len(matching_posts) < 100:
                    # Highlight words matched cleanly by the regex pattern boundaries
                    highlighted_text = search_pattern.sub(
                        r"<mark style='background: #ffeb3b; color: #000; padding: 1px 3px; font-weight: bold;'>\g<0></mark>", 
                        post
                    )
                    matching_posts.append(highlighted_text)

        if matching_posts:
            search_results_html += f"""
            <div class="search-meta-summary">
                Found <b>{match_count}</b> total historical mentions of "<b>{query}</b>" matching root plural variants. 
                <i>(Displaying first 100 entries below)</i>
            </div>
            """
            for idx, post in enumerate(matching_posts, 1):
                search_results_html += f"""
                <div class="post-container" style="border-left: 3px solid #af0a0f;">
                    <div class="post-meta">
                        <span class="poster-name">Match #{idx}</span>
                        <span class="post-id">Result Pool</span>
                    </div>
                    <div class="post-body">{post}</div>
                </div>
                """
        else:
            search_results_html = f"<p style='color: #af0a0f; font-weight: bold; margin-top: 20px;'>No direct historical matches found for '{query}' inside the active scraper cache.</p>"

    trends_display = "block" if active_tab == "trends" else "none"
    search_display = "block" if active_tab == "search" else "none"
    trends_active_class = "active" if active_tab == "trends" else ""
    search_active_class = "active" if active_tab == "search" else ""

    return f"""
<!DOCTYPE html>
<html>
<head>
<title>/{BOARD}/ Imageboard Tracker</title>
<style>
body {{ 
    background: #f0e0d6; 
    color: #000000; 
    font-family: arial,helvetica,sans-serif; 
    font-size: 13px;
    margin: 20px; 
    padding-bottom: 50px;
}}
h1 {{ 
    color: #af0a0f; 
    font-size: 28px; 
    text-align: center; 
    margin-top: 0;
    margin-bottom: 2px;
    letter-spacing: -2px;
}}
.subtitle {{
    text-align: center;
    font-size: 12px;
    color: #444;
    margin-bottom: 25px;
}}
.board-title {{
    font-weight: bold;
    font-size: 14px;
    color: #af0a0f;
    border-bottom: 1px solid #d9bfb7;
    padding-bottom: 4px;
    margin-top: 20px;
    margin-bottom: 12px;
}}
.stats-box {{ 
    background: #d6daf0; 
    border: 1px solid #b7c5d9;
    padding: 10px; 
    margin-bottom: 25px; 
    font-size: 12px;
    display: inline-block;
    min-width: 280px;
}}
.stats-box b {{
    color: #0f0c5d;
}}

.tabs-nav {{
    border-bottom: 2px solid #b7c5d9;
    margin-bottom: 20px;
}}
.tab-btn {{
    background: #e0e4f6;
    color: #0f0c5d;
    border: 1px solid #b7c5d9;
    border-bottom: none;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: bold;
    cursor: pointer;
    display: inline-block;
    margin-right: 4px;
    text-decoration: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}
.tab-btn.active {{
    background: #d6daf0;
    border-bottom: 2px solid #d6daf0;
    margin-bottom: -2px;
}}

.search-form-panel {{
    background: #d6daf0;
    border: 1px solid #b7c5d9;
    padding: 15px;
    max-width: 670px;
    margin-bottom: 20px;
}}
.search-input {{
    width: 75%;
    padding: 6px;
    font-size: 14px;
    border: 1px solid #b7c5d9;
}}
.search-submit-btn {{
    padding: 6px 15px;
    background: #af0a0f;
    color: #fff;
    font-weight: bold;
    border: 1px solid #800000;
    cursor: pointer;
}}
.search-meta-summary {{
    background: #e0e4f6;
    padding: 8px 12px;
    margin-bottom: 15px;
    max-width: 775px;
    border: 1px solid #b7c5d9;
    font-size: 13px;
}}

table {{ 
    width: 100%; 
    max-width: 700px;
    border-collapse: collapse; 
    background: #d6daf0;
    border: 1px solid #b7c5d9;
    margin-bottom: 20px;
}}
td, th {{ 
    border: 1px solid #b7c5d9; 
    padding: 6px 10px; 
    text-align: left; 
}}
th {{ 
    background: #e0e4f6; 
    color: #0f0c5d; 
    font-size: 12px;
}}
.subject {{ 
    color: #0f0c5d; 
    font-weight: bold; 
}}
.post-container {{ 
    background: #d6daf0; 
    border: 1px solid #b7c5d9;
    padding: 8px 12px; 
    margin-bottom: 8px; 
    max-width: 800px;
    display: table;
}}
.post-meta {{ 
    font-size: 11px; 
    color: #444; 
    margin-bottom: 5px;
    font-family: sans-serif;
}}
.poster-name {{ 
    color: #117743; 
    font-weight: bold; 
}}
.post-date {{
    color: #444;
}}
.post-id {{
    color: #444;
    font-family: monospace;
}}
.post-body {{ 
    color: #000;
    font-size: 13px;
    line-height: 15px;
    word-break: break-word;
}}
</style>
</head>
<body>

<h1>/{BOARD}/ Tracker</h1>
<div class="subtitle">An NLP Contextual Trend & Word Metric Monitor</div>

<div class="stats-box">
    <b>Active Context Scan:</b> {stats["last_update"]}<br>
    <b>Catalog Threads Checked:</b> {stats["threads"]}<br>
    <b>Aggregated Posts Scanned:</b> {stats["posts"]}
</div>

<div class="tabs-nav">
    <a href="/" class="tab-btn {trends_active_class}">Trending Subject Volumes</a>
    <a href="/?q=white" class="tab-btn {search_active_class}">Keyword Search Deck</a>
</div>

<div id="trends-tab-view" style="display: {trends_display};">
    <div class="board-title">Top Trending Subject Volumes</div>
    <table>
        <thead>
            <tr>
                <th style="width: 45px; text-align: center;">Rank</th>
                <th>Topic / Phrase</th>
                <th style="width: 150px;">Total Word Mentions</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>

    <div class="board-title">Sample Raw Processing Feed</div>
    {post_html}
</div>

<div id="search-tab-view" style="display: {search_display};">
    <div class="board-title">Realtime Corpus Phrase Search</div>
    <div class="search-form-panel">
        <form method="GET" action="/">
            <input type="text" name="q" class="search-input" placeholder="Type a keyword, phrase or concept phrase here..." value="{query}">
            <button type="submit" class="search-submit-btn">Search Pool</button>
        </form>
    </div>
    
    {search_results_html}
</div>

</body>
</html>
"""

if __name__ == "__main__":
    thread = threading.Thread(target=analyze, daemon=True)
    thread.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
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
    "concepts": [],       # The common words/phrases across ALL comments
    "thread_topics": [],  # NEW: Clean concept parsing of just thread OPs
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

def extract_phrases(text_list):
    phrase_counter = Counter()
    docs = nlp.pipe(text_list, batch_size=256)
    
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
            if not clean_phrase or not all(w.isalpha() for w in words) or clean_phrase in GENERIC_SINGLE_WORDS or len(words) > 3:
                continue
            phrase_counter[clean_phrase] += 1

    top_phrases = phrase_counter.most_common(150)
    full_corpus = " " + " ".join(text_list).lower() + " "
    
    seen_normalized_roots = set()
    final_data = []
    
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
        final_data.append((norm_key, literal_count))

    final_data.sort(key=lambda x: x[1], reverse=True)
    return final_data[:50]

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
            op_texts = []
            thread_meta_map = {}

            # Parse catalog to isolate thread OPs for "Top Threads"
            for page in catalog:
                for thread_obj in page["threads"]:
                    tid = thread_obj["no"]
                    thread_ids.append(tid)
                    
                    sub = thread_obj.get("sub", "")
                    com = thread_obj.get("com", "")
                    clean_op = clean_text(f"{sub} {com}")
                    if clean_op:
                        op_texts.append(clean_op)
                    
                    thread_meta_map[tid] = {
                        "replies": thread_obj.get("replies", 0),
                        "op_snippet": clean_op[:120] if clean_op else "No text content"
                    }

            all_posts_text = []
            raw_posts_pool = []
            sample_posts = []
            total_posts = 0

            print(f"[*] Found {len(thread_ids)} threads. Crawling detailed logs...")

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

                    all_posts_text.append(text)
                    raw_posts_pool.append((text, thread_id))
                    
                    if len(sample_posts) < 25:
                        sample_posts.append((text[:300], thread_id))
                    total_posts += 1

            print("[*] Performing parallel text corpus evaluation...")
            concepts = extract_phrases(all_posts_text)
            thread_topics = extract_phrases(op_texts)

            stats = {
                "last_update": time.strftime("%Y-%m-%d %H:%M:%S"),
                "threads": len(thread_ids),
                "posts": total_posts,
                "concepts": concepts,
                "thread_topics": thread_topics,
                "top_posts": sample_posts,
                "raw_posts_pool": raw_posts_pool 
            }
            print("[+] Update complete. Dashboard dataset pushed live!")

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
    <h1>/{BOARD}/ Corpus Engine</h1>
    <p>Loading catalog, sorting raw concepts and parsing original topics... (takes ~60s)</p>
</body>
</html>
"""

    tab = request.args.get("tab", "concepts")
    query = request.args.get("q", "").strip()
    
    if query:
        tab = "search"

    # Generate Concept Rows (Total Words in Posts)
    concept_rows = ""
    for idx, (concept, count) in enumerate(stats["concepts"], 1):
        concept_rows += f"""
        <tr>
            <td style="color: #444; font-size: 12px; text-align: center;">{idx}</td>
            <td><span class="subject">{concept}</span></td>
            <td style="color: #af0a0f; font-weight: bold; font-family: monospace; font-size: 14px;">{count} occurrences</td>
        </tr>
        """

    # Generate Thread Topic Rows (What Threads Are About)
    topic_rows = ""
    for idx, (topic, count) in enumerate(stats["thread_topics"], 1):
        topic_rows += f"""
        <tr>
            <td style="color: #444; font-size: 12px; text-align: center;">{idx}</td>
            <td><span class="subject" style="color: #0f0c5d;">{topic}</span></td>
            <td style="color: #117743; font-weight: bold; font-family: monospace; font-size: 14px;">{count} active threads</td>
        </tr>
        """
        
    post_html = ""
    for idx, (post, thread_id) in enumerate(stats["top_posts"], 1):
        post_html += f"""
        <a href="https://boards.4chan.org/{BOARD}/thread/{thread_id}" target="_blank" class="post-link-wrapper">
            <div class="post-container">
                <div class="post-meta">
                    <span class="poster-name">Anonymous</span> 
                    <span class="post-date">{stats["last_update"]}</span> 
                    <span class="post-id">Thread No.{thread_id}</span>
                </div>
                <div class="post-body">{post}... <span style="color: #af0a0f; font-size: 11px;">[Open Thread]</span></div>
            </div>
        </a>
        """

    search_results_html = ""
    match_count = 0
    if query:
        matching_posts = []
        if " " not in query:
            root_term = get_singular_root(query.lower())
            search_pattern = re.compile(rf"\b{root_term}s?\b", flags=re.IGNORECASE)
        else:
            search_pattern = re.compile(rf"\b{re.escape(query.lower())}\b", flags=re.IGNORECASE)
        
        for post, thread_id in stats["raw_posts_pool"]:
            matches = search_pattern.findall(post)
            if matches:
                match_count += len(matches)
                if len(matching_posts) < 100:
                    highlighted_text = search_pattern.sub(
                        r"<mark style='background: #ffeb3b; color: #000; padding: 1px 3px; font-weight: bold;'>\g<0></mark>", 
                        post
                    )
                    matching_posts.append((highlighted_text, thread_id))

        if matching_posts:
            search_results_html += f"""
            <div class="search-meta-summary">
                Found <b>{match_count}</b> total historical mentions of "<b>{query}</b>".
                <i>(Displaying first 100 entries below)</i>
            </div>
            """
            for idx, (post, thread_id) in enumerate(matching_posts, 1):
                search_results_html += f"""
                <a href="https://boards.4chan.org/{BOARD}/thread/{thread_id}" target="_blank" class="post-link-wrapper">
                    <div class="post-container" style="border-left: 3px solid #af0a0f;">
                        <div class="post-meta">
                            <span class="poster-name">Match #{idx}</span>
                            <span class="post-id">Thread No.{thread_id}</span>
                        </div>
                        <div class="post-body">{post}</div>
                    </div>
                </a>
                """
        else:
            search_results_html = f"<p style='color: #af0a0f; font-weight: bold; margin-top: 20px;'>No matches found for '{query}' in active cache.</p>"

    return f"""
<!DOCTYPE html>
<html>
<head>
<title>/{BOARD}/ Analytics Engine</title>
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
.centered-search-header {{ text-align: center !important; }}
.search-form-panel {{
    background: #d6daf0; border: 1px solid #b7c5d9; padding: 15px; max-width: 670px; margin: 0 auto 20px auto; text-align: center;
}}
.search-input {{ width: 70%; padding: 6px; font-size: 14px; border: 1px solid #b7c5d9; }}
.search-submit-btn {{ padding: 6px 15px; background: #af0a0f; color: #fff; font-weight: bold; border: 1px solid #800000; cursor: pointer; }}
.search-meta-summary {{ background: #e0e4f6; padding: 8px 12px; margin-bottom: 15px; max-width: 775px; border: 1px solid #b7c5d9; }}

table {{ 
    width: 100%; max-width: 700px; border-collapse: collapse; background: #d6daf0; border: 1px solid #b7c5d9; margin-bottom: 20px;
}}
td, th {{ border: 1px solid #b7c5d9; padding: 6px 10px; text-align: left; }}
th {{ background: #e0e4f6; color: #0f0c5d; font-size: 12px; }}
.subject {{ font-weight: bold; color: #0f0c5d; }}

.post-link-wrapper {{ text-decoration: none; color: inherit; display: table; margin-bottom: 8px; }}
.post-link-wrapper:hover .post-container {{ background: #e0e4f6; border-color: #af0a0f; }}
.post-container {{ 
    background: #d6daf0; border: 1px solid #b7c5d9; padding: 8px 12px; max-width: 800px; display: table; transition: background 0.1s ease, border-color 0.1s ease;
}}
.post-meta {{ font-size: 11px; color: #444; margin-bottom: 5px; }}
.poster-name {{ color: #117743; font-weight: bold; }}
.post-body {{ color: #000; font-size: 13px; line-height: 15px; word-break: break-word; }}
</style>
</head>
<body>

<h1>/{BOARD}/ Analytics Engine</h1>
<div class="subtitle">Natural Language Parsing & Core Index Mapping</div>

<div class="stats-box">
    <b>Active Context Scan:</b> {stats["last_update"]}<br>
    <b>Catalog Threads Checked:</b> {stats["threads"]}<br>
    <b>Aggregated Posts Scanned:</b> {stats["posts"]}
</div>

<div class="tabs-nav">
    <a href="/?tab=concepts" class="tab-btn {'active' if tab == 'concepts' else ''}">Dominant Corpus Concepts</a>
    <a href="/?tab=topics" class="tab-btn {'active' if tab == 'topics' else ''}">Top Threads Analytics</a>
    <a href="/?tab=search" class="tab-btn {'active' if tab == 'search' else ''}">Keyword Search Deck</a>
</div>

<div style="display: {'block' if tab == 'concepts' else 'none'};">
    <div class="board-title">Dominant Corpus Concepts (Raw Comment Frequencies)</div>
    <table>
        <thead>
            <tr>
                <th style="width: 45px; text-align: center;">Rank</th>
                <th>Extracted Phrase / Word</th>
                <th style="width: 170px;">Global Comment Frequency</th>
            </tr>
        </thead>
        <tbody>
            {concept_rows}
        </tbody>
    </table>

    <div class="board-title">Sample Raw Processing Feed</div>
    {post_html}
</div>

<div style="display: {'block' if tab == 'topics' else 'none'};">
    <div class="board-title">Top Thread Topics (What Threads are Created About)</div>
    <table>
        <thead>
            <tr>
                <th style="width: 45px; text-align: center;">Rank</th>
                <th>Core Thread Subject Theme</th>
                <th style="width: 200px;">Active Thread Base Count</th>
            </tr>
        </thead>
        <tbody>
            {topic_rows}
        </tbody>
    </table>
</div>

<div style="display: {'block' if tab == 'search' else 'none'};">
    <div class="board-title centered-search-header">Realtime Corpus Phrase Search</div>
    <div class="search-form-panel">
        <form method="GET" action="/">
            <input type="hidden" name="tab" value="search">
            <input type="text" name="q" class="search-input" placeholder="Type a keyword or concept here..." value="{query}">
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
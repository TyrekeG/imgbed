#!/usr/bin/env python3
"""Generate featured stories via PPIO vision — runs via cron, writes cache files."""

import json, os, sys, time, urllib.request

UPLOAD_DIR = "/opt/imgbed/uploads"
CACHE_DIR = "/opt/imgbed/.story_cache"
PPIO_ENV = "/opt/ppio-proxy/.env"

def load_config():
    key = ""
    api = "https://api.ppinfra.com/v3/openai"
    if os.path.exists(PPIO_ENV):
        with open(PPIO_ENV) as f:
            for line in f:
                line = line.strip()
                if line.startswith("PPIO_API_KEYS="):
                    key = line.split("=", 1)[1].split(",")[0].strip()
                elif line.startswith("PPIO_BASE_URL="):
                    api = line.split("=", 1)[1].strip()
    return key, api

def get_categories():
    """List category dirs with at least one image."""
    base = os.path.join(UPLOAD_DIR, time.strftime("%Y-%m"))
    cats = []
    if os.path.isdir(base):
        for d in os.listdir(base):
            dp = os.path.join(base, d)
            if not os.path.isdir(dp):
                continue
            imgs = [f for f in os.listdir(dp) if not f.startswith('.') and '_thumb' not in f]
            if imgs:
                cats.append(d)
    return cats

def get_sample_image(category):
    """Get one image URL from category."""
    base = os.path.join(UPLOAD_DIR, time.strftime("%Y-%m"), category)
    for fn in os.listdir(base):
        if fn.startswith('.') or '_thumb' in fn:
            continue
        return f"https://i.juho.uk/{time.strftime('%Y-%m')}/{category}/{fn}"
    return None

def gen_story(category, image_url, key, api):
    today = time.strftime("%Y-%m-%d")
    cache_file = os.path.join(CACHE_DIR, f"{today}_{category}.json")
    if os.path.exists(cache_file):
        return  # already done
    
    prompt = "Describe this photo in one poetic line (under 12 words). Then on a new line, Chinese translation (12 chars max).\n"
    data = {
        "model": "qwen/qwen3-vl-30b-a3b-instruct",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": prompt}
        ]}],
        "max_tokens": 50
    }
    
    try:
        req = urllib.request.Request(
            f"{api}/chat/completions",
            data=json.dumps(data).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        raw = result["choices"][0]["message"].get("content", "").strip()
        lines = [l.strip() for l in raw.split(chr(10)) if l.strip()]
        
        story = {"story_en": lines[0] if lines else "", "story": lines[1] if len(lines) > 1 else ""}
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(story, f)
        print(f"Generated story for {category}: {story['story_en'][:50]}")
    except Exception as e:
        print(f"FAIL {category}: {e}", file=sys.stderr)

def main():
    key, api = load_config()
    if not key:
        print("No PPIO key found", file=sys.stderr)
        sys.exit(1)
    
    categories = get_categories()
    for cat in categories:
        img_url = get_sample_image(cat)
        if img_url:
            gen_story(cat, img_url, key, api)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate story for today's featured image via PPIO vision."""
import json, os, time, urllib.request, sys

CACHE_DIR = "/opt/imgbed/.story_cache"
PPIO_ENV = "/opt/ppio-proxy/.env"

def load_config():
    key = ""; api = "https://api.ppinfra.com/v3/openai"
    if os.path.exists(PPIO_ENV):
        env = {}
        with open(PPIO_ENV) as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
        keys = env.get("PPIO_API_KEYS", "").split(",")
        if keys: key = keys[0].strip()
        api = env.get("PPIO_BASE_URL", api)
    return key, api

def get_featured():
    """Get today's featured image from the API."""
    try:
        r = urllib.request.urlopen("http://localhost:3003/api/featured", timeout=30)
        return json.loads(r.read())
    except Exception as e:
        print(f"Featured API fail: {e}", file=sys.stderr)
        return None

def gen_story(key, api, data):
    fn = os.path.splitext(data["url"].split("/")[-1])[0]
    cache_file = os.path.join(CACHE_DIR, f"{fn}.json")
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    if os.path.exists(cache_file):
        mtime = os.path.getmtime(cache_file)
        if time.strftime("%Y-%m-%d") == time.strftime("%Y-%m-%d", time.localtime(mtime)):
            print(f"Story cached today: {fn}")
            with open(cache_file) as f:
                s = json.load(f)
            print(f"  EN: {s.get('story_en','')}")
            return

    prompt = "Write a poetic, witty one-liner about this photo (under 10 words). Then Chinese (under 10 chars)."
    body = {
        "model": "qwen/qwen3-vl-30b-a3b-instruct",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data["url"]}},
            {"type": "text", "text": prompt}
        ]}],
        "max_tokens": 40
    }
    try:
        req = urllib.request.Request(
            f"{api}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        )
        r = urllib.request.urlopen(req, timeout=30)
        result = json.loads(r.read())
        raw = result["choices"][0]["message"]["content"].strip()
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        story = {"story_en": lines[0] if lines else "", "story": lines[1] if len(lines) > 1 else ""}
        with open(cache_file, "w") as f:
            json.dump(story, f)
        print(f"Generated: {fn}")
        print(f"  EN: {story['story_en']}")
        print(f"  ZH: {story['story']}")
    except Exception as e:
        print(f"Gen fail: {e}", file=sys.stderr)

def main():
    key, api = load_config()
    if not key:
        print("No PPIO key", file=sys.stderr)
        sys.exit(1)
    data = get_featured()
    if data and data.get("url"):
        gen_story(key, api, data)
    else:
        print("No featured image", file=sys.stderr)

if __name__ == "__main__":
    main()

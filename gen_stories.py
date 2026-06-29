#!/usr/bin/env python3
import json, os, time, urllib.request, sys
UPLOAD_DIR = "/opt/imgbed/uploads"
CACHE_DIR = "/opt/imgbed/.story_cache"
PPIO_ENV = "/opt/ppio-proxy/.env"

def load_config():
    key = ""
    api = "https://api.ppinfra.com/v3/openai"
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

def main():
    key, api = load_config()
    if not key:
        print("No PPIO key", file=sys.stderr)
        sys.exit(1)
    os.makedirs(CACHE_DIR, exist_ok=True)
    base = os.path.join(UPLOAD_DIR, time.strftime("%Y-%m"))
    if not os.path.isdir(base):
        print(f"No upload dir: {base}")
        return
    for cat in sorted(os.listdir(base)):
        dp = os.path.join(base, cat)
        if not os.path.isdir(dp): continue
        imgs = [f for f in os.listdir(dp) if not f.startswith('.') and '_thumb' not in f]
        if not imgs: continue
        cache_file = os.path.join(CACHE_DIR, f"{cat}.json")
        # Skip if generated today
        if os.path.exists(cache_file):
            mtime = os.path.getmtime(cache_file)
            if time.strftime("%Y-%m-%d") == time.strftime("%Y-%m-%d", time.localtime(mtime)):
                print(f"{cat}: cached (today)")
                continue
        url = f"https://i.juho.uk/{time.strftime('%Y-%m')}/{cat}/{imgs[0]}"
        prompt = "Line 1: describe this photo in English (under 10 words). Line 2: Chinese translation (under 10 chars). No labels."
        data = {
            "model": "qwen/qwen3-vl-30b-a3b-instruct",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": url}},
                {"type": "text", "text": prompt}
            ]}],
            "max_tokens": 40
        }
        try:
            req = urllib.request.Request(
                f"{api}/chat/completions",
                data=json.dumps(data).encode(),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            )
            r = urllib.request.urlopen(req, timeout=30)
            result = json.loads(r.read())
            raw = result["choices"][0]["message"]["content"].strip()
            lines = [l.strip() for l in raw.split("\n") if l.strip()]
            story = {"story_en": lines[0] if lines else "", "story": lines[1] if len(lines) > 1 else ""}
            with open(cache_file, "w") as f:
                json.dump(story, f)
            print(f"{cat}: {story['story_en'][:50]} | {story['story']}")
        except Exception as e:
            print(f"{cat} FAIL: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()

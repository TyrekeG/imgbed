#!/usr/bin/env python3
"""i.juho.uk v3 — R2-backed Smart Image Hosting with safety limits.
- Auto WebP conversion (Pillow)
- R2 cloud storage via Cloudflare API
- Daily upload cap: 500
- Storage cap: 7GB warn / 8GB auto-purge oldest
- Local cache fallback
"""
import os, json, uuid, time, io, hashlib
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from PIL import Image
import urllib.request, urllib.error


# ── Load .env ──
import os as _os
_env_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".env")
if _os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                _os.environ.setdefault(_key.strip(), _val.strip())

# ── Config ──
UPLOAD_DIR = os.environ.get("IMGBED_DIR", "/opt/imgbed/uploads")
CACHE_DIR = os.environ.get("IMGBED_CACHE", "/opt/imgbed/cache")
HOST = os.environ.get("IMGBED_HOST", "0.0.0.0")
PORT = int(os.environ.get("IMGBED_PORT", "3003"))
BASE_URL = "https://i.juho.uk"
MAX_SIZE = 20 * 1024 * 1024
WEBP_QUALITY = 80
MAX_DIMENSION = 2400
THUMB_SIZE = (600, 600)

# ── R2 Config ──
CF_ACCOUNT = "b4f2dd73bb0804bc199769c4fa4644df"
CF_TOKEN = os.environ.get("CF_R2_TOKEN", "")
R2_BUCKET = "juho-images"
R2_API = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/r2/buckets/{R2_BUCKET}/objects"


# ── PIN Protection ──
ACCESS_PIN = "gordona"

# ── Safety Limits ──
DAILY_UPLOAD_LIMIT = 20000
STORAGE_WARN_GB = 45
STORAGE_MAX_GB = 50

# ── Tracking ──
TRACK_FILE = "/opt/imgbed/.tracking.json"

def load_tracking():
    if os.path.exists(TRACK_FILE):
        with open(TRACK_FILE) as f:
            return json.load(f)
    return {"daily": {}, "total_bytes": 0, "objects": {}}

def save_tracking(t):
    with open(TRACK_FILE, "w") as f:
        json.dump(t, f)

def today_key():
    return time.strftime("%Y-%m-%d")

def check_limits(tracking):
    today = today_key()
    daily_count = len(tracking["daily"].get(today, {}))
    total_gb = tracking["total_bytes"] / (1024**3)
    
    if daily_count >= DAILY_UPLOAD_LIMIT:
        return False, f"Daily limit reached ({DAILY_UPLOAD_LIMIT} uploads)"
    if total_gb >= STORAGE_MAX_GB:
        return False, f"Storage full ({total_gb:.1f}GB/{STORAGE_MAX_GB}GB)"
    return True, f"OK ({daily_count}/{DAILY_UPLOAD_LIMIT} today, {total_gb:.1f}GB total)"

def upload_to_r2(key, data, content_type):
    """Upload object to R2 via Cloudflare REST API."""
    url = f"{R2_API}/{urllib.request.quote(key, safe='')}"
    req = urllib.request.Request(url, method="PUT", data=data)
    req.add_header("Authorization", f"Bearer {CF_TOKEN}")
    req.add_header("Content-Type", content_type)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        return result.get("success", False), result
    except Exception as e:
        return False, str(e)

def delete_from_r2(key):
    """Delete object from R2."""
    url = f"{R2_API}/{urllib.request.quote(key, safe='')}"
    req = urllib.request.Request(url, method="DELETE")
    req.add_header("Authorization", f"Bearer {CF_TOKEN}")
    try:
        urllib.request.urlopen(req, timeout=30)
        return True
    except:
        return False

def list_r2_objects(prefix=""):
    """List objects in R2 bucket."""
    url = f"{R2_API}?prefix={prefix}&limit=1000"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {CF_TOKEN}")
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        return result.get("result", [])
    except:
        return []

def auto_purge_if_needed(tracking):
    """Auto-delete oldest objects if storage exceeds max."""
    total_gb = tracking["total_bytes"] / (1024**3)
    if total_gb < STORAGE_MAX_GB:
        return
    
    # Sort objects by upload time, delete oldest until under limit
    sorted_objs = sorted(tracking["objects"].items(), key=lambda x: x[1].get("ts", 0))
    target_bytes = STORAGE_WARN_GB * 1024**3
    
    for key, info in sorted_objs:
        if tracking["total_bytes"] <= target_bytes:
            break
        if delete_from_r2(key):
            tracking["total_bytes"] -= info.get("size", 0)
            # Clean local cache
            cache_path = os.path.join(CACHE_DIR, key)
            if os.path.exists(cache_path):
                os.remove(cache_path)
            del tracking["objects"][key]

# ── HTML ──
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Juho 视界 · 图床</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:system-ui,-apple-system,sans-serif;background:linear-gradient(135deg,#0d0d18,#16162a,#10101e);color:#e8e6f0;min-height:100vh}
  .container{max-width:960px;margin:0 auto;padding:40px 24px}
  h1{font-size:4rem;font-weight:900;letter-spacing:-0.06em;line-height:1;margin-bottom:4px;
    background:linear-gradient(135deg, #0d9488 0%, #10b981 50%, #6366f1 100%);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
  .sub{color:#9b95a8;font-size:0.85rem;font-weight:500;margin-bottom:12px}
  .feature-badges{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:28px}
  .badge{font-size:0.7rem;padding:5px 14px;border-radius:20px;background:rgba(255,255,255,.06);color:#9b95a8;font-weight:500;border:1px solid rgba(255,255,255,.08)}
  .badge.on{background:rgba(13,148,136,.1);color:#2dd4bf;border-color:rgba(13,148,136,.2)}
  .stats{display:flex;gap:24px;margin-bottom:20px;font-size:0.8rem;color:#9b95a8;font-weight:500}
  .stats span{padding:6px 14px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px}
  .options{margin-bottom:16px;font-size:0.85rem;color:#888}
  .options label{cursor:pointer;font-weight:500;color:#9b95a8}
  .options input{margin-right:6px;accent-color:#0d9488}
  select{background:rgba(255,255,255,.08)!important;color:#e8e6f0!important;border:1px solid rgba(255,255,255,.15)!important}
  select option{background:#1a1a2e;color:#e8e6f0}
  .dropzone{border:2px dashed rgba(255,255,255,.1);border-radius:16px;padding:56px 24px;text-align:center;background:rgba(255,255,255,.03);cursor:pointer;transition:all 0.2s}
  .dropzone:hover,.dropzone.drag{border-color:#0d9488;background:rgba(13,148,136,.06)}
  .dropzone.denied{border-color:#fca5a5;background:#fef2f2;cursor:not-allowed}
  .dropzone .big{font-size:3rem;display:block;margin-bottom:12px}
  .dropzone p{color:#9b95a8;font-size:0.95rem;font-weight:500}
  #status{display:none;text-align:center;padding:16px;color:#0d9488;font-weight:600;font-size:0.9rem}
  #result{margin-top:24px}
  .card{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:16px;margin-bottom:10px;transition:all 0.2s}
  .card:hover{border-color:#0d9488;transform:translateY(-2px);box-shadow:0 8px 30px rgba(13,148,136,0.06)}
  .card img{width:100%;max-height:300px;object-fit:cover;border-radius:8px;margin-bottom:10px}
  .card .info{margin-bottom:8px}
  .card .url{font-size:0.8rem;color:#0d9488;word-break:break-all;font-weight:600;margin-bottom:4px}
  .card .meta{font-size:0.75rem;color:#9b95a8}
  .card .meta .saved{color:#10b981;font-weight:700;margin-left:8px}
  .card .actions{display:flex;gap:8px;flex-wrap:wrap}
  .card .actions button{padding:6px 14px;border:2px solid #e5e7eb;border-radius:8px;background:#fff;color:#9b95a8;font-size:0.78rem;font-weight:600;cursor:pointer;transition:all 0.2s}
  .card .actions button:hover{border-color:#0d9488;color:#0d9488;background:rgba(13,148,136,.1)}
  #file-input{display:none}
  @media(max-width:500px){h1{font-size:2.5rem}.dropzone{padding:32px 16px}}
</style>
</head>
<body>
<div class="container">
  <h1>Juho · 视界</h1>
  <p class="sub">拖入图片 · 自动优化 · 云端储存</p>
  <div class="feature-badges">
    <span class="badge on">☁️ R2 Cloud</span>
    <span class="badge on">🔄 Auto WebP</span>
    <span class="badge">⚡ Quality 80%</span>
    <span class="badge">📂 Date Sorted</span>
    <span class="badge">🛡️ Limit Protected</span>
  </div>
  <div class="stats" id="stats">Loading stats...</div>
  <div class="options">
    <label><input type="checkbox" id="keepOrig"> Keep original format</label>
  </div>
  <div class="options" style="margin-bottom:16px">
    <label style="font-weight:600;color:#9b95a8;font-size:0.85rem">Category:</label>
    <select id="category" style="margin-left:8px;padding:6px 12px;border:1px solid rgba(255,255,255,.15);border-radius:8px;font-size:0.85rem;background:rgba(255,255,255,.08);color:#e8e6f0;cursor:pointer">
      <option value="viewfinder">取景器内</option>
      <option value="sartorial">Sartorial 切片</option>
      <option value="misc">杂物 Misc</option>
      <option value="custom" id="customOpt">自定义…</option>
    </select>
    <input type="text" id="customCat" placeholder="输入分类名" style="display:none;margin-left:8px;padding:6px 12px;border:2px solid #e5e7eb;border-radius:8px;font-size:0.85rem;background:#fff;color:#333;width:160px">
  </div>
<div class="dropzone" id="dropzone">
    <span class="big">📤</span>
    <p>Drop images here or click</p>
  </div>
  <div id="status">Processing...</div>
  <input type="file" id="fileInput" multiple accept="image/*" style="display:none">
  <div id="result"></div>
</div>
<script>
let keepOrig=false;
let category='viewfinder';
document.getElementById('category').onchange=function(){
  category=this.value;
  let showCustom = (category==='custom');
  document.getElementById('customCat').style.display=showCustom?'inline-block':'none';
  if(!showCustom) document.getElementById('customCat').value='';
};
document.getElementById('customCat').oninput=function(){
  if(this.value) category=this.value;
};

document.getElementById('keepOrig').onchange=function(){keepOrig=this.checked};
const dz=document.getElementById('dropzone'),inp=document.getElementById('fileInput'),res=document.getElementById('result'),st=document.getElementById('status');
['dragenter','dragover'].forEach(e=>dz.addEventListener(e,ev=>{ev.preventDefault();dz.classList.add('drag')}));
['dragleave','drop'].forEach(e=>dz.addEventListener(e,ev=>{ev.preventDefault();dz.classList.remove('drag')}));
dz.addEventListener('drop',e=>uploadFiles(e.dataTransfer.files));
dz.addEventListener('click',()=>inp.click());
inp.addEventListener('change',()=>uploadFiles(inp.files));

async function loadStats(){
  try{
    const r=await fetch('/stats');
    const d=await r.json();
    document.getElementById('stats').innerHTML=`<span>📤 ${d.daily_count}/${d.daily_limit} today</span><span>💾 ${d.storage_used} / ${d.storage_max}</span><span>☁️ R2: ${d.r2_status}</span>`;
    if(d.denied){
      dz.classList.add('denied');
      dz.querySelector('p').textContent='⚠️ Upload limit reached. Try again tomorrow.';
    }
  }catch(e){}
}
loadStats();
loadCategories();
loadFolders();

async function loadCategories(){
  try{
    const r=await fetch('/api/categories');
    const cats=await r.json();
    const sel=document.getElementById('category');
    const marker=document.getElementById('customOpt');
    // Remove old dynamic options
    sel.querySelectorAll('.dyn-cat').forEach(o=>o.remove());
    cats.forEach(c=>{
      const opt=document.createElement('option');
      opt.className='dyn-cat';
      opt.value=c.value;
      opt.textContent=c.label;
      sel.insertBefore(opt,marker);
    });
  }catch(e){}
}
async function loadFolders(){
  try{
    const r=await fetch('/api/images');
    const imgs=await r.json();
    // Group by category
    const folders={};
    imgs.forEach(d=>{
      const key=d.category||'uncategorized';
      if(!folders[key]) folders[key]={category:key,label:d.categoryLabel||key,cover:d.thumb||d.url,images:[],description:d.description||''};
      folders[key].images.push(d);
      // Use most recent as cover
      if(d.mtime > (folders[key]._maxMtime||0)){
        folders[key].cover = d.thumb||d.url;
        folders[key]._maxMtime = d.mtime;
      }
    });
    const sorted=Object.values(folders).sort((a,b)=>b.label.localeCompare(a.label));
    const frag=document.createDocumentFragment();
    sorted.forEach(f=>{
      if(f.category==='uncategorized') return;
      const div=document.createElement('div');div.className='card folder-card';
      div.style.cursor='pointer';
      div.innerHTML=`<img src="${f.cover}" loading="lazy"><div class="info"><div class="url">📁 ${f.label}</div><div class="meta">${f.images.length} images</div></div>`;
      div.onclick=()=>showFolder(f);
      frag.appendChild(div);
    });
    res.innerHTML='';
    res.appendChild(frag);
  }catch(e){}
}

function showFolder(folder){
  const cat=folder.category;
  res.innerHTML=`
    <div style="margin-bottom:12px;display:flex;align-items:center;flex-wrap:wrap;gap:8px">
      <button onclick="loadFolders()" style="padding:6px 14px;border:2px solid #e5e7eb;border-radius:8px;background:#fff;color:#9b95a8;font-size:0.85rem;font-weight:600;cursor:pointer">← 返回</button>
      <span style="font-weight:700;color:#333">📁 ${folder.label} · ${folder.images.length} 张</span>
      <button onclick="editDesc('${cat}')" style="padding:4px 10px;border:1px solid #e5e7eb;border-radius:6px;background:#fff;color:#9b95a8;font-size:0.75rem;cursor:pointer">✏️ 简介</button>
    </div>
    <div id="descArea-${cat}" style="margin-bottom:12px;color:#9b95a8;font-size:0.8rem">${folder.description || ''}</div>`;
  folder.images.forEach(d=>{
    const div=document.createElement('div');div.className='card';
    const metaHTML=`${formatSize(d.size)}`;
    div.innerHTML=`<img src="${d.thumb||d.url}" loading="lazy"><div class="info"><div class="url">${d.url}</div><div class="meta">${metaHTML}</div></div><div class="actions"><button onclick="copyUrl('${d.url}')">Copy URL</button><button onclick="copyUrl('![](${d.url})')">Copy MD</button><button onclick="window.open('${d.url}')">Open</button><button onclick="setCover('${cat}','${d.thumb||d.url}')" style="background:#fef3c7;color:#92400e;border-color:#fcd34d">⭐ 封面</button></div>`;
    res.appendChild(div);
  });
}

async function setCover(cat, url){
  if(!confirm('设 ' + url.split('/').pop() + ' 为封面？')) return;
  try{
    const r=await fetch('/api/category-meta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:cat,cover:url})});
    if(r.ok){alert('封面已更新！');loadFolders();}
    else{alert('失败');}
  }catch(e){alert('错误');}
}

function editDesc(cat){
  const area=document.getElementById('descArea-'+cat);
  const old=area.textContent;
  area.innerHTML=`<textarea id="descInput-${cat}" style="width:100%;padding:8px;border:2px solid #0d9488;border-radius:8px;background:rgba(255,255,255,.08);color:#e8e6f0;font-size:0.8rem;resize:vertical" rows="2">${old}</textarea>
    <button onclick="saveDesc('${cat}')" style="margin-top:6px;padding:6px 16px;background:#0d9488;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:0.8rem">保存</button>
    <button onclick="loadFolders()" style="margin-top:6px;margin-left:6px;padding:6px 16px;background:#666;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:0.8rem">取消</button>`;
}

async function saveDesc(cat){
  const val=document.getElementById('descInput-'+cat).value;
  try{
    const r=await fetch('/api/category-meta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:cat,description:val})});
    if(r.ok){alert('简介已保存！');loadFolders();}
    else{alert('失败');}
  }catch(e){alert('错误');}
}

function formatSize(b){
  if(b<1024)return b+'B';
  if(b<1024*1024)return (b/1024).toFixed(0)+'KB';
  return (b/(1024*1024)).toFixed(1)+'MB';
}

async function uploadFiles(files){
  if(!files||!files.length)return;
  st.style.display='block';
  let done=0,total=files.length;
  for(const f of files){
    st.textContent=`Processing ${done+1}/${total}...`;
    if(f.size>20*1024*1024){st.textContent=f.name+' too large';done++;continue}
    const fd=new FormData();fd.append('file',f);fd.append('keep_orig',keepOrig?'1':'0');fd.append('category',category);
    st.textContent=`Uploading ${f.name} to R2...`;
    try{
      const r=await fetch('/',{method:'POST',body:fd});
      const d=await r.json();
      if(r.ok)addCard(d);
      else st.textContent=d.error||'Failed';
    }catch(ex){st.textContent='Network error'}
    done++;
  }
  st.style.display='none';
  loadStats();
}

function addCard(d){
  // After upload, reload the folder view
  setTimeout(()=>loadFolders(), 500);
}

function copyUrl(u){
  navigator.clipboard.writeText(u).then(()=>{
    const btns=document.querySelectorAll('.card:first-child .actions button');
    btns.forEach(b=>{if(b.textContent.startsWith('Copy'))b.textContent='✓'});  
    setTimeout(()=>{btns.forEach(b=>{if(b.textContent==='✓')b.textContent=b===btns[0]?'Copy URL':'Copy MD'})},1200);
  });
}
</script>
</body>
</html>"""

# ── Handler ──
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def do_GET(self):
        path = self.path.rstrip("/") or "/"
        # Strip query string for path matching
        path_only = path.split("?", 1)[0]
        
        # ── PIN gate ──
        if path_only in ("/", "/index.html") or path.startswith("/?"):
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            pin = None
            if qs:
                from urllib.parse import parse_qs
                try:
                    pin = parse_qs(qs).get("pin", [None])[0]
                except:
                    pass
            if pin != ACCESS_PIN:
                return self._serve_pin_gate()
        
        if path_only == "/api/images":
            return self._serve_image_list()
        if path_only == "/api/categories":
            return self._serve_categories()
        if path_only == "/" or path_only.startswith("/?"):
            return self._serve_html()
        if path_only == "/stats":
            return self._serve_stats()
        
        # Serve file: local cache first, then try R2
        rel = urllib.parse.unquote(path.lstrip("/"))
        if ".." in rel:
            return self._send_error(403)
        
        # Check local cache
        filepath = os.path.join(UPLOAD_DIR, rel)
        if os.path.isfile(filepath):
            return self._serve_file(filepath)
        
        # Try R2
        r2_url = f"https://pub-b4f2dd73bb0804bc199769c4fa4644df.r2.dev/{rel}"
        try:
            req = urllib.request.Request(r2_url)
            resp = urllib.request.urlopen(req, timeout=15)
            data = resp.read()
            # Cache locally
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            # Don't cache too much locally to save disk
            self.send_response(302)
            self.send_header("Location", r2_url)
            self.end_headers()
            return
        except:
            # Fallback to local upload dir
            filepath = os.path.join(UPLOAD_DIR, rel)
            if os.path.isfile(filepath):
                return self._serve_file(filepath)
        
        self._send_error(404)

    def do_HEAD(self):
        path = self.path.rstrip("/") or "/"
        # Strip query string for path matching
        path_only = path.split("?", 1)[0]
        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        rel = urllib.parse.unquote(path.lstrip("/"))
        filepath = os.path.join(UPLOAD_DIR, rel)
        if os.path.isfile(cache_path):
            self.send_response(200)
            self.send_header("Content-Length", str(os.path.getsize(cache_path)))
            self.send_header("Cache-Control", "public, max-age=31536000")
            self.end_headers()
            return
        # Check R2 via HEAD redirect
        r2_url = f"https://pub-b4f2dd73bb0804bc199769c4fa4644df.r2.dev/{rel}"
        self.send_response(302)
        self.send_header("Location", r2_url)
        self.end_headers()

    def do_POST(self):
        path = self.path.rstrip("/") or "/"
        # Strip query string for path matching
        path_only = path.split("?", 1)[0]
        
        # Category meta update (cover / description)
        if path == "/api/category-meta":
            return self._handle_category_meta()
        
        ct = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ct:
            return self._json(400, {"error": "multipart required"})
        
        tracking = load_tracking()
        ok, msg = check_limits(tracking)
        if not ok:
            return self._json(429, {"error": msg})
        
        boundary = ct.split("boundary=")[-1].strip()
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        
        parts = body.split(f"--{boundary}".encode())
        keep_orig = False
        
        for part in parts:
            if b"Content-Disposition" not in part: continue
            hdr_end = part.find(b"\r\n\r\n")
            headers_raw = part[:hdr_end].decode("utf-8", errors="replace")
            
            if 'name="keep_orig"' in headers_raw:
                val = part[hdr_end+4:].decode("utf-8", errors="replace").strip()
                keep_orig = (val == "1")
                continue
            if 'name="category"' in headers_raw:
                cat_val = part[hdr_end+4:].decode("utf-8", errors="replace").strip()
                if cat_val and cat_val not in ('custom',):
                    category = cat_val.replace(" ", "-").lower()
                continue
            
            if 'filename="' not in headers_raw: continue
            fn_start = headers_raw.find('filename="') + 10
            fn_end = headers_raw.find('"', fn_start)
            orig_name = headers_raw[fn_start:fn_end]
            
            file_data = part[hdr_end + 4:]
            if file_data.endswith(b"\r\n"): file_data = file_data[:-2]
            if not file_data: return self._json(400, {"error": "empty"})
            if len(file_data) > MAX_SIZE: return self._json(400, {"error": ">20MB"})
            
            original_size = len(file_data)
            category = "misc"  # default
            for part_init in parts:
                if b'name="category"' in part_init:
                    hdr_end = part_init.find(b"\r\n\r\n")
                    hdr_txt = part_init[:hdr_end].decode("utf-8", errors="replace")
                    val_start = part_init.find(b"\r\n\r\n") + 4
                    cat_val = part_init[val_start:].decode("utf-8", errors="replace").strip()
                    if cat_val and cat_val not in ('custom',):
                        category = cat_val.replace(" ", "-").lower()
                    break
            date_folder = time.strftime("%Y-%m") + "/" + category
            uid = uuid.uuid4().hex[:8]
            
            converted = False
            saved_pct = "0"
            thumb_data = None
            thumb_ext = ".webp"
            
            try:
                img = Image.open(io.BytesIO(file_data))
                fmt = img.format or "PNG"

                # Resize if too large (max 2400px)
                w, h = img.size
                if max(w, h) > MAX_DIMENSION:
                    ratio = MAX_DIMENSION / max(w, h)
                    img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
                
                if not keep_orig and fmt in ("PNG", "JPEG", "BMP", "TIFF"):
                    if img.mode in ("RGBA", "LA", "P"):
                        img = img.convert("RGBA")
                    else:
                        img = img.convert("RGB")
                    buf = io.BytesIO()
                    exif_data = img.info.get("exif")
                    save_kwargs = {"format": "WEBP", "quality": WEBP_QUALITY, "method": 6}
                    if exif_data:
                        save_kwargs["exif"] = exif_data
                    img.save(buf, **save_kwargs)
                    file_data = buf.getvalue()
                    converted = True
                    saved_pct = str(round((1 - len(file_data) / original_size) * 100))
                    fname = f"{uid}.webp"
                    content_type = "image/webp"
                elif not keep_orig and fmt == "GIF":
                    fname = f"{uid}.gif"
                    content_type = "image/gif"
                else:
                    ext = os.path.splitext(orig_name)[1].lower() or f".{fmt.lower()}"
                    fname = f"{uid}{ext}"
                    content_type = {
                        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"
                    }.get(ext, "application/octet-stream")
                
                # Generate thumbnail
                if fmt != "SVG":
                    thumb_img = img.copy()
                    thumb_img.thumbnail(THUMB_SIZE)
                    thumb_buf = io.BytesIO()
                    thumb_fmt = "WEBP" if converted else fmt
                    thumb_img.save(thumb_buf, format=thumb_fmt, quality=80)
                    thumb_data = thumb_buf.getvalue()
                    thumb_name = f"{uid}_thumb.webp"
                else:
                    thumb_name = None
            except Exception as e:
                ext = os.path.splitext(orig_name)[1].lower() or ".bin"
                fname = f"{uid}{ext}"
                content_type = "application/octet-stream"
                thumb_name = None
            
            r2_key = f"{date_folder}/{fname}"
            r2_thumb_key = f"{date_folder}/{thumb_name}" if thumb_name else None
            
            # Upload to R2
            success, result = upload_to_r2(r2_key, file_data, content_type)
            if not success:
                # Fallback: save locally
                local_folder = os.path.join(UPLOAD_DIR, date_folder)
                os.makedirs(local_folder, exist_ok=True)
                with open(os.path.join(local_folder, fname), "wb") as f:
                    f.write(file_data)
                url = f"{BASE_URL}/{date_folder}/{fname}"
                r2_status = "local fallback"
            else:
                # R2 public URL (using r2.dev for now, custom domain later)
                url = f"{BASE_URL}/{date_folder}/{fname}"
                r2_status = "R2"
                
                # Save to local serve directory (primary access path)
                serve_folder = os.path.join(UPLOAD_DIR, date_folder)
                os.makedirs(serve_folder, exist_ok=True)
                with open(os.path.join(serve_folder, fname), "wb") as f:
                    f.write(file_data)
                
                # Also cache thumb
                if thumb_data and thumb_name:
                    with open(os.path.join(serve_folder, thumb_name), "wb") as f:
                        f.write(thumb_data)
                
                # Upload thumbnail to R2
                if thumb_data and r2_thumb_key:
                    upload_to_r2(r2_thumb_key, thumb_data, content_type)
                    thumb_url = f"{BASE_URL}/{date_folder}/{thumb_name}"
                else:
                    thumb_url = None
            
            # Dedup check
            new_hash = hashlib.md5(file_data).hexdigest()
            for existing in os.listdir(serve_folder):
                if existing == fname or existing.startswith("."):
                    continue
                existing_path = os.path.join(serve_folder, existing)
                try:
                    with open(existing_path, "rb") as f:
                        if hashlib.md5(f.read()).hexdigest() == new_hash:
                            os.remove(os.path.join(serve_folder, fname))
                            if thumb_name:
                                try: os.remove(os.path.join(serve_folder, thumb_name))
                                except: pass
                            return self._json(200, {"ok": True, "deduped": True, "url": f"{BASE_URL}/{date_folder}/{existing}"})
                except:
                    pass

            # Update tracking
            today = today_key()
            if today not in tracking["daily"]:
                tracking["daily"][today] = {}
            tracking["daily"][today][uid] = True
            tracking["total_bytes"] += len(file_data)
            tracking["objects"][r2_key] = {"size": len(file_data), "ts": int(time.time())}
            
            # Clean old daily entries (keep last 7 days)
            cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7*86400))
            tracking["daily"] = {k: v for k, v in tracking["daily"].items() if k >= cutoff}
            
            # Auto-purge if over limit
            auto_purge_if_needed(tracking)
            save_tracking(tracking)
            
            size_kb = round(len(file_data) / 1024, 1)
            size_str = f"{size_kb}KB" if size_kb < 1024 else f"{round(size_kb/1024,1)}MB"
            
            resp = {
                "url": url,
                "name": orig_name,
                "size": size_str,
                "converted": converted,
                "saved_pct": saved_pct,
                "folder": date_folder,
                "r2": r2_status,
            }
            if thumb_url:
                resp["thumb"] = thumb_url
            
            return self._json(200, resp)
        
        self._json(400, {"error": "no file found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


    def _handle_category_meta(self):
        """POST /api/category-meta — update cover or description for a category."""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except:
            return self._json(400, {"error": "invalid json"})
        
        cat = data.get("category", "").strip()
        if not cat:
            return self._json(400, {"error": "category required"})
        
        desc_path = os.path.join(os.path.dirname(__file__), "category-descriptions.json")
        meta = {}
        if os.path.exists(desc_path):
            try:
                meta = json.load(open(desc_path))
            except:
                meta = {}
        
        if cat not in meta:
            meta[cat] = {}
        elif isinstance(meta[cat], str):
            meta[cat] = {"description": meta[cat]}
        
        if "cover" in data:
            meta[cat]["cover"] = data["cover"]
        if "description" in data:
            meta[cat]["description"] = data["description"]
        
        json.dump(meta, open(desc_path, "w"), indent=2, ensure_ascii=False)
        return self._json(200, {"ok": True, "category": cat})

    def _serve_pin_gate(self):
        html = '''<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Juho · 视界</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:linear-gradient(135deg,#0d0d18,#16162a);color:#e8e6f0;display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{text-align:center}
h1{font-size:3rem;font-weight:900;letter-spacing:-0.04em;background:linear-gradient(135deg,#0d9488,#6366f1);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}
p{color:#9b95a8;font-size:0.9rem;margin-bottom:24px}
input{padding:12px 20px;border:2px solid rgba(255,255,255,0.1);border-radius:12px;background:rgba(255,255,255,0.05);color:#e8e6f0;font-size:1.1rem;text-align:center;letter-spacing:0.3em;width:200px;outline:none;transition:border-color 0.2s}
input:focus{border-color:#0d9488}
button{display:block;margin:16px auto 0;padding:10px 32px;border:none;border-radius:10px;background:#0d9488;color:#fff;font-size:0.95rem;font-weight:600;cursor:pointer;transition:background 0.2s}
button:hover{background:#0f766e}
.error{color:#f87171;font-size:0.8rem;margin-top:8px;display:none}
</style></head>
<body><div class="box">
<h1>Juho · 视界</h1>
<p>Enter PIN to access</p>
<input type="password" id="pin" placeholder="····" maxlength="12" autofocus>
<button onclick="go()">进入</button>
<p class="error" id="err">PIN 不正确</p>
</div>
<script>
const p=document.getElementById('pin'),e=document.getElementById('err');
const saved=sessionStorage.getItem('imgbed_pin');
if(saved){window.location='?pin='+saved}
p.addEventListener('keydown',ev=>{if(ev.key==='Enter')go()});
function go(){if(p.value){sessionStorage.setItem('imgbed_pin',p.value);window.location='?pin='+p.value}else{e.style.display='block'}}
</script>
</body></html>'''
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _serve_html(self):
        data = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_stats(self):
        tracking = load_tracking()
        today = today_key()
        daily_count = len(tracking["daily"].get(today, {}))
        total_gb = tracking["total_bytes"] / (1024**3)
        self._json(200, {
            "daily_count": daily_count,
            "daily_limit": DAILY_UPLOAD_LIMIT,
            "storage_used": f"{total_gb:.2f}GB",
            "storage_max": f"{STORAGE_MAX_GB}GB",
            "r2_status": "connected" if True else "offline",
            "denied": daily_count >= DAILY_UPLOAD_LIMIT or total_gb >= STORAGE_MAX_GB,
        })

    def _format_label(self, cat):
        """Auto-format category names: thailand-tour → Thailand Tour, zoe → Zoe"""
        predef = {"viewfinder": "取景器内", "sartorial": "Sartorial 切片", "misc": "杂物"}
        if cat in predef:
            return predef[cat]
        return ' '.join(w.capitalize() for w in cat.replace('-', ' ').replace('_', ' ').split())

    def _load_descriptions(self):
        """Load category descriptions from JSON config"""
        desc_path = os.path.join(os.path.dirname(__file__), "category-descriptions.json")
        try:
            with open(desc_path) as f:
                return json.load(f)
        except:
            return {}

    def _serve_categories(self):
        """Return category metadata — light payload for gallery listing."""
        descriptions = self._load_descriptions()
        cats = []
        base = os.path.join(UPLOAD_DIR, time.strftime("%Y-%m"))
        if os.path.isdir(base):
            for d in sorted(os.listdir(base)):
                dp = os.path.join(base, d)
                if not os.path.isdir(dp):
                    continue
                # Count images
                imgs = [f for f in os.listdir(dp) if not f.startswith('.') and '_thumb' not in f]
                count = len(imgs)
                label = self._format_label(d)
                meta = descriptions.get(d, "")
                desc = meta.get("description", "") if isinstance(meta, dict) else (meta if isinstance(meta, str) else "")
                cover = meta.get("cover", "") if isinstance(meta, dict) else ""
                # Auto-cover if not set: use most recent thumb
                if not cover and imgs:
                    newest = max(imgs, key=lambda f: os.path.getmtime(os.path.join(dp, f)))
                    name_no_ext = os.path.splitext(newest)[0]
                    thumb_name = f"{name_no_ext}_thumb.webp"
                    if os.path.exists(os.path.join(dp, thumb_name)):
                        cover = f"{BASE_URL}/{time.strftime('%Y-%m')}/{d}/{thumb_name}"
                    else:
                        cover = f"{BASE_URL}/{time.strftime('%Y-%m')}/{d}/{newest}"
                cats.append({
                    "category": d,
                    "label": label,
                    "count": count,
                    "cover": cover,
                    "description": desc,
                    "description_en": (meta.get("description_en", "") if isinstance(meta, dict) else ""),
                    "value": d,  # for upload dropdown compat
                })
        self._json(200, cats)

    def _serve_image_list(self):
        """Return images, optionally filtered by category. Supports ?category=zoe"""
        filter_cat = None
        if '?' in self.path:
            for pair in self.path.split('?', 1)[1].split('&'):
                if pair.startswith('category='):
                    filter_cat = pair.split('=', 1)[1]
                    filter_cat = urllib.parse.unquote(filter_cat)
                    filter_cat = urllib.parse.unquote(filter_cat)
        descriptions = self._load_descriptions()
        result = []
        for root, dirs, files in os.walk(UPLOAD_DIR):
            for fn in sorted(files, reverse=True):
                if fn.startswith('.') or '_thumb' in fn:
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if ext not in ('.webp', '.jpg', '.jpeg', '.png', '.gif'):
                    continue
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, UPLOAD_DIR)
                size = os.path.getsize(full)
                mtime = os.path.getmtime(full)
                name_no_ext = os.path.splitext(fn)[0]
                thumb_name = f"{name_no_ext}_thumb{ext}"
                thumb_path = os.path.join(root, thumb_name)
                if not os.path.exists(thumb_path):
                    thumb_name_webp = f"{name_no_ext}_thumb.webp"
                    thumb_path = os.path.join(root, thumb_name_webp)
                    if os.path.exists(thumb_path):
                        thumb_name = thumb_name_webp
                thumb_rel = os.path.relpath(thumb_path, UPLOAD_DIR) if os.path.exists(thumb_path) else None
                # Extract category from path
                parts = rel.split('/')
                cat = parts[1] if len(parts) > 1 else 'uncategorized'
                # Apply category filter if specified
                if filter_cat and cat != filter_cat:
                    continue
                # Custom cover from descriptions
                cat_meta = descriptions.get(cat, "")
                if isinstance(cat_meta, dict):
                    custom_cover = cat_meta.get("cover", "")
                    cat_desc = cat_meta.get("description", "")
                else:
                    custom_cover = ""
                    cat_desc = cat_meta if isinstance(cat_meta, str) else ""
                result.append({
                    "url": f"{BASE_URL}/{urllib.request.quote(rel, safe='/')}",
                    "thumb": f"{BASE_URL}/{urllib.request.quote(thumb_rel, safe='/')}" if thumb_rel else f"{BASE_URL}/{urllib.request.quote(rel, safe='/')}",
                    "size": size,
                    "mtime": mtime,
                    "date": time.strftime("%Y-%m-%d", time.localtime(mtime)),
                    "category": cat,
                    "categoryLabel": self._format_label(cat),
                    "description": cat_desc,
                    "description_en": cat_meta.get("description_en", "") if isinstance(cat_meta, dict) else "",
                    "categoryCover": custom_cover,
                })
        body = json.dumps(result).encode()
        etag = '"' + hashlib.md5(body).hexdigest()[:12] + '"'
        # Check If-None-Match for 304 before sending 200
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=60")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=60")
        self.send_header("ETag", etag)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, filepath):
        ext = os.path.splitext(filepath)[1].lower()
        mime = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"
        }.get(ext, "application/octet-stream")
        size = os.path.getsize(filepath)
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def _send_error(self, code):
        self.send_response(code)
        self.end_headers()

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    # Test R2 connectivity on startup
    test_ok, _ = upload_to_r2("__test__/.ping", b"ok", "text/plain")
    print(f"i.juho.uk v3 R2: {'☁️ connected' if test_ok else '⚠️ local-only'}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Listening on :{PORT}")
    server.serve_forever()

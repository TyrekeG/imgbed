# i.juho.uk — 图床服务

## 架构
- **后端**: Python 3.12, `imgbed.py` (端口 3003)
- **存储**: Cloudflare R2 (juho-images bucket, 免费 10GB)
- **网关**: Caddy reverse_proxy (i.juho.uk → 172.18.0.1:3003)
- **CDN**: Cloudflare proxy

## 限制（2026-06-28 当前）
| 项目 | 值 | 说明 |
|------|-----|------|
| 每天上传 | 20000 | 单人使用，仅防滥用 |
| 存储预警 | 7 GB | 超过后 auto-purge 清理最老文件 |
| 存储硬上限 | 9 GB | 超过拒绝上传（R2 免费 10GB 留 1GB 余量） |
| 单文件上限 | 20 MB | |
| 图片最大尺寸 | 2400px | 自动缩放 |

## API
| 端点 | 用途 |
|------|------|
| `GET /api/categories` | 分类列表（含 description_en 双语） |
| `GET /api/images?category=xxx` | 分类下图片 |
| `GET /stats` | 用量统计 |
| `POST /api/category-meta` | 更新分类描述/封面 |
| `POST /` (multipart) | 上传图片 |

## 关键文件
- `imgbed.py` — 主程序
- `.env` — CF_R2_TOKEN（自动加载）
- `category-descriptions.json` — 分类双语描述（必须有 description + description_en）
- `.tracking.json` — 上传追踪（总大小、每日统计、对象列表）

## 管理命令
```bash
# 重启
kill $(lsof -ti :3003) && cd /opt/imgbed && nohup python3 imgbed.py > /tmp/imgbed.log 2>&1 &

# 看日志
tail -f /tmp/imgbed.log

# 查用量
curl http://localhost:3003/stats | python3 -m json.tool

# 同步本地到 R2（如需要）
cd /opt/imgbed && python3 -c "
import imgbed, os
for root,dirs,files in os.walk(imgbed.UPLOAD_DIR):
    for fn in files:
        if fn.startswith('.'): continue
        fp = os.path.join(root, fn)
        rel = os.path.relpath(fp, imgbed.UPLOAD_DIR)
        with open(fp,'rb') as f:
            imgbed.upload_to_r2(rel, f.read(), 'image/webp')
"
```

## 已修复的问题（2026-06-28）
1. ✅ URL decode: 分类名含空格的路径编码
2. ✅ 上传 sanitize: 空格→连字符，小写
3. ✅ API 双语: description_en 返回
4. ✅ 上传去重: MD5 检查，重复文件自动跳过
5. ✅ R2 token: .env 自动加载（之前一直 fallback 本地）
6. ✅ 缩略图: london-tour 批量生成 51 thumbnails
7. ✅ 存储限制: 恢复 R2 免费 tier 限制（7/9 GB）
8. ✅ R2 用量显示: i.juho.uk 首页显示实际存储量

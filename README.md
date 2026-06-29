# i.juho.uk — 图床服务

## 是什么
浩哥的图片托管后端。前端在 https://i.juho.uk 上传管理图片，API 供 juho.uk 画廊调用。

## 启动
```bash
cd /opt/imgbed && nohup python3 imgbed.py &
```
Caddy 将 `i.juho.uk` 反代到 `localhost:3003`。

## 关键文件
- `imgbed.py` — 主服务（端口 3003）
- `category-descriptions.json` — 分类描述（**必须同时有 description 和 description_en**）
- 图片存储：`/opt/imgbed/YYYY-MM/{category}/`

## API
| 端点 | 用途 |
|------|------|
| `GET /api/categories` | 分类列表（含 description, description_en, cover, count） |
| `GET /api/images?category=xxx` | 分类下图片 |
| `POST /api/category-meta` | 更新分类封面/描述 |

## 修改分类描述后
```bash
kill $(pgrep -f imgbed.py) && cd /opt/imgbed && nohup python3 imgbed.py &
```

## 禁止
- ❌ 手动改 /opt/imgbed/ 下图片文件（走网页上传）
- ❌ 分类描述只写中文不写英文

## CLI 上传
```bash
bash /opt/my-stack/www/www.juho.uk-react/scripts/imgbed-upload.sh <图片路径> [分类] [英文描述]
```

## API 端点（补充）
| 端点 | 方法 | 用途 |
|------|------|------|
| `POST /` | multipart | 上传图片（file, category, description, description_en） |
| `POST /api/category-meta` | JSON | 更新分类封面/描述 |

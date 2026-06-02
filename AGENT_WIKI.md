# Agent Wiki — tg-telegram-imagebed

> 面向 AI Agent / 新开发者快速理解项目的知识库。记录架构、约定、模块职责和常见任务的实现模式。

---

## 1. 项目定位

**tg-telegram-imagebed** 是单进程的图片托管 (image bed) 服务，后端 Python + Flask，前端 Nuxt 3 SPA。核心上传链路为：

```
用户浏览器 ──POST /api/upload──▶ Flask ──▶ file_service.py ──▶ storage/router.py ──▶ 存储后端 (Telegram/Local/S3/rclone)
                                                                          │
                                                                          ▼
                                                                     SQLite (file_storage 表)
```

Telegram 既是**存储后端**（Bot API 上传图片到频道）也是**交互方式**（Bot 接受聊天上传）。

---

## 2. 顶层文件结构

```
main.py                          # 入口。创建 Flask → 启动 Bot 线程 → 启动 CDN 监控 → 等待信号
migrate_encrypt.py               # 脱离式工具：将 DB 中明文敏感配置转为 AES-GCM 加密
requirements.txt                 # Python 依赖
VERSION                          # 纯文本版本号 (2.0.4)
.env.example                     # 仅基础设施环境变量，业务配置在 DB
Dockerfile / docker-compose.yml  # 容器化
```

---

## 3. Python 包结构 (tg_imagebed/)

### 3.1 模块分层 & 依赖方向

```
                    ┌──────────────┐
                    │   main.py    │ (入口)
                    └──────┬───────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼─────┐     ┌──────▼──────┐    ┌──────▼──────┐
   │  api/     │     │   bot/      │    │  services/   │
   │ (路由)   │     │ (TG Bot)   │    │ (业务逻辑)   │
   └────┬─────┘     └──────┬──────┘    └──────┬──────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼─────┐     ┌──────▼──────┐    ┌──────▼──────┐
   │ database/│     │  storage/   │    │admin_module │
   │ (数据库)│     │ (存储抽象) │    │ (管理认证)   │
   └──────────┘     └─────────────┘    └─────────────┘

工具层: config.py  utils.py  crypto_utils.py  settings_manager.py
        rate_limiter.py  bot_control.py  device_fingerprint.py
```

**依赖规则**: 上层可 import 下层，不可反向。

### 3.2 各模块速查

| 模块 | 职责 | 核心类/函数 |
|------|------|------------|
| `config.py` | 基础设施常量: 路径, 端口, SECRET_KEY, 日志, 锁文件 | `SECRET_KEY`, `DATABASE_PATH`, `PORT=18793` |
| `utils.py` | 通用工具: IP 解析, 文件签名, MIME 检测, 缓存头, 域名获取 | `get_client_ip()`, `sign_file_id()`, `add_cache_headers()`, `get_domain()` |
| `crypto_utils.py` | AES-256-GCM 加解密，前缀 `ENC:AESGCM:` | `encrypt_value()`, `decrypt_value()`, `is_encrypted()` |
| `settings_manager.py` | 配置管理器（单例），优先级 DB > env > 默认值 | `settings_manager.get_proxy_url()` |
| `rate_limiter.py` | 内存级 API 限流: 图片 100/min, 上传 10/min, API 30/min + 每日上传限额 | `check_rate_limit()`, `SimpleRateLimiter` |
| `bot_control.py` | Bot Token 获取 (DB 优先, env 回退), 热重启信号 | `get_effective_bot_token()`, `request_bot_restart()` |
| `admin_module.py` | 管理员认证, 会话管理 (max 3), CSRF, 渐进锁, 审计日志 | `login_required` 装饰器, 密码 hash (pbkdf2) |

### 3.3 api/ — 路由层

| 文件 | Blueprint URL 前缀 | 说明 |
|------|-------------------|------|
| `__init__.py` | — | 定义 5 个 Blueprint |
| `upload.py` | `/api/upload`, `/upload` | 公开/匿名文件上传 |
| `images.py` | `/` (catch-all) | 图片流式输出、访问计数 |
| `auth.py` | `/api/auth` | Token 认证 (生成/验证/删除) |
| `tg_auth.py` | `/api/auth/tg` | TG 登录认证 (OAuth 风格) |
| `galleries.py` | `/api/auth/galleries` | 画集 CRUD + 分享管理 |
| `gallery_site.py` | `/api/shared` | 公开画集站 API |
| `settings.py` | `/api` | 公开设置 API |
| `admin_*.py` | `/api/admin/*` | 管理后台全套 API |
| `admin_helpers.py` | — | Admin 工具函数 (CORS, token 校验) |

### 3.4 database/ — 数据访问层

| 文件 | 职责 |
|------|------|
| `connection.py` | SQLite 连接池 (threading.local), 表创建, 迁移 (ALTER TABLE), 索引 |
| `files.py` | file_storage 表 CRUD, 统计, 访问计数缓冲 (60s 批量 flush) |
| `settings.py` | system_settings 表，~80 个默认值，敏感字段自动加密 |
| `tokens.py` | auth_tokens 表 CRUD，支持搜索/排序/分页 |
| `tg_auth.py` | tg_users / tg_login_codes / tg_sessions 表 |
| `galleries.py` | galleries / gallery_images / share_all_links 表 |
| `gallery_home.py` | gallery_home_config / gallery_home_sections 表 |
| `admin_galleries.py` | 管理员侧画集管理查询 |
| `domains.py` | custom_domains 表 (图片域名/画集域名/默认域名) |
| `__init__.py` | 通过 `__all__` 重导出全部公开函数 |

### 3.5 storage/ — 存储抽象层

```
storage/
  router.py        StorageRouter: 场景路由 (guest/token/group/admin → 后端)
  base.py          StorageBackend ABC, PutResult, DownloadResult
  backends/
    telegram.py    Telegram Cloud 后端 (Bot API + Kurigram/MTProto)
    local.py       本地文件系统后端
    s3.py          S3 兼容后端 (boto3)
    rclone.py      rclone CLI 后端
```

**关键设计**: 每个后端实现 `put_bytes()`, `download()`, `delete()`, `healthcheck()` 四个抽象方法。

**场景路由流程**:
```python
router.resolve_upload_backend(
    scene="guest",       # guest / token / group / admin
    requested_backend=None,  # 管理员可选指定后端
    is_admin=False
)
# → 查询 storage_upload_policy_json → 解析 env: 引用 → 选择后端实例
```

### 3.6 services/ — 服务层

| 文件 | 核心函数 |
|------|----------|
| `file_service.py` | `process_upload()`: 编排上传 → 存储 → DB 记录 → CDN 监控 |
| `cdn_service.py` | Cloudflare CDN 缓存监控 (detached thread, 指数退避) |
| `token_service.py` | Token 级联删除 (token → 文件 → 画集 → 访问许可) |
| `update_service.py` | GitHub Release 热更新: 下载 → SHA256 → 解压 → 备份 → 覆盖 → pip → os.execv |

### 3.7 bot/ — Telegram Bot

| 文件 | 职责 |
|------|------|
| `runner.py` | Bot 主循环 (轮询/webhook), 重试, 优雅关闭 |
| `handlers.py` | 消息处理器 (photo/document/媒体组) |
| `commands.py` | 命令实现 (/start, /help, /id, /myuploads, /delete, /login, /mytokens, /settoken) |
| `media_batch.py` | 媒体组防抖批量处理 |
| `helpers.py` | Bot 工具函数 |
| `state.py` | Bot 全局状态管理 (running, token, webhook URL) |

---

## 4. 前端 (frontend/)

Nuxt 3 + Vue 3 + Nuxt UI + Pinia + Tailwind。

编译后产物输出到 `frontend/.output/public/`，由 Flask 作为静态文件服务（`STATIC_FOLDER` 指向此目录）。

**关键约定**:
- API 调用封装在 `composables/` 下
- 全局状态在 `stores/` (Pinia)
- Admin SPA 页面在 `pages/admin/`
- Token 客户端加密使用 Web Crypto API (AES-GCM)，存储于 localStorage

---

## 5. 数据库设计

### 5.1 核心表

```sql
file_storage           — 文件记录 (主表, ~20 列)
  ├── encrypted_id (PK)    — HMAC-SHA256 签名的文件 ID
  ├── file_id              — Telegram file_id
  ├── storage_backend      — 'telegram'/'local'/'s3'/'rclone'
  ├── storage_key          — 对应后端的存储 key
  ├── auth_token           — 关联的上传 token
  └── access_count         — 访问计数 (内存缓冲写入)

auth_tokens            — Token 表
  ├── token (PK)
  ├── tg_user_id        — TG 用户绑定 (可选)
  └── is_default_upload — 是否默认上传 Token

admin_config           — 键值对配置表 (settings, sessions, security_log)
  └── key TEXT, value TEXT

galleries              — 画集
gallery_images         — 画集↔图片关联 (FK cascade)
custom_domains         — 自定义域名 (image/gallery/default 类型)
tg_users / tg_sessions / tg_login_codes  — TG 认证
login_attempts         — 登录暴力破解防护
```

### 5.2 迁移模式

数据库迁移使用**增量 ALTER TABLE** + **崩溃恢复**模式：
- `connection.py` 中 `_migrate_*` 系列函数检查列是否存在，不存在则 ALTER TABLE ADD COLUMN
- `_cleanup_orphaned_migration_tables` 处理中断的原子迁移 (`_old`, `_new`, `_broken` 表)

---

## 6. 编码规范

### 6.1 Python 约定

- **类型注解**: 使用 Python 3.10+ 语法 (`str | None`, `dict[str, Any]`), 文件头有 `from __future__ import annotations`
- **字符串**: 统一使用双引号 `"`
- **f-string**: 日志消息使用 f-string
- **logger 级别**: 
  - `logger.info` — 正常业务流程
  - `logger.warning` — 可恢复异常
  - `logger.error` — 需要关注的错误
  - `logger.debug` — 调试信息（多处过度使用，审计中标记）
- **加密/签名**: 
  - 密码 → `werkzeug.security.generate_password_hash(method='pbkdf2:sha256')`
  - 敏感配置 → `encrypt_value()` (AES-256-GCM)
  - 文件 ID → `sign_file_id()` (HMAC-SHA256 + 随机盐)
- **线程安全**: 所有共享可变状态使用 `threading.Lock()`, 双重检查锁用于缓存

### 6.2 前端约定

- Vue 3 Composition API (`<script setup lang="ts">`)
- 组件: PascalCase 文件名
- Composables: `use` 前缀 (`useUpload`, `useGalleryApi`)
- Stores (Pinia): camelCase (`auth`, `adminUi`)

### 6.3 禁止事项

- ❌ 在代码中添加注释（除非用户明确要求）
- ❌ 在 .env 中存储敏感信息（业务配置走 DB）
- ❌ 绕过 `StorageRouter` 直接调用后端实例
- ❌ 在 API 路由中直接操作数据库（应通过 service 层）

---

## 7. 常见开发任务与模板

### 7.1 添加新的存储后端

1. 在 `storage/backends/` 新建 `myback.py`
2. 继承 `storage/base.py` 中的 `StorageBackend` ABC
3. 实现 `put_bytes()`, `download()`, `delete()`, `healthcheck()`
4. 在 `storage/router.py` 的 `_build_backend()` 添加注册
5. 在 `storage/backends/__init__.py` 导出新后端

### 7.2 添加新的管理员 API

1. 在 `api/` 新建 `admin_feature.py`
2. 使用 `from . import admin_bp` 获取 Blueprint
3. 路由示例:
```python
@admin_bp.route('/api/admin/my-feature', methods=['GET'])
@login_required
def my_feature():
    # 业务逻辑
    return jsonify(result)
```
4. 在 `api/__init__.py` 的 import 列表中添加（触发路由注册）
5. 在 `api/admin_helpers.py` 的相关函数中注册（如需要）

### 7.3 添加新的数据库设置项

1. 在 `database/settings.py` 的 `DEFAULT_SYSTEM_SETTINGS` 字典中添加默认值
2. 如果值敏感 (password/key/token)，在 `_SENSITIVE_KEYS` 集合中注册（自动加密）
3. 通过 `get_system_setting('key_name')` 读取, `update_system_setting('key_name', value)` 写入

### 7.4 添加新的 Bot 命令

1. 在 `bot/commands.py` 的 `_COMMANDS` 字典注册
2. 实现处理函数，返回 (text, reply_markup, parse_mode)
3. 如需特殊消息处理，在 `bot/handlers.py` 添加 handler

### 7.5 添加新的环境变量

1. 仅在 `config.py` 中的"基础设施常量"部分添加
2. 业务配置不通过环境变量，走 `settings_manager.py` → `system_settings`

---

## 8. 启动流程

```
1. main() → acquire_lock()           # 单实例锁
2.        → init_database()          # 创建表 + 索引 + 迁移
3.        → init_system_settings()   # 写入 ~80 个默认设置 (idempotent)
4.        → start_cdn_monitor()      # 后台线程 (如果 CDN 启用)
5.        → run_flask() 线程启动     # waitress HTTP 服务 0.0.0.0:18793
6.        → 健康检查轮询 (最多 10s)
7.        → start_telegram_bot_thread()  # 轮询或 webhook
8.        → shutdown_event.wait()    # 主线程等待信号
9.        → flush_all_access_counts() + stop_cdn_monitor() + release_lock()
```

---

## 9. 测试

**当前状态**: 项目无自动化测试。

**手动验证**:
- 启动: `python main.py`
- 上传测试: `curl -F "file=@test.png" http://127.0.0.1:18793/upload`
- 前端: `http://127.0.0.1:18793/`
- 管理后台: `http://127.0.0.1:18793/admin`
- API 文档: `http://127.0.0.1:18793/docs`

---

## 10. 环境变量速查

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | 18793 | 服务端口 |
| `ALLOWED_ORIGINS` | `*` | CORS 来源白名单, 逗号分隔 |
| `LOG_LEVEL` | INFO | 日志级别 |
| `HTTP_PROXY` / `http_proxy` | 空 | HTTP 代理地址 |
| `HTTPS_PROXY` / `https_proxy` | 空 | HTTPS 代理地址 |
| `RATE_LIMIT_IMAGE` | 100,60 | 图片访问限流 (次数,秒) |
| `RATE_LIMIT_UPLOAD` | 10,60 | 上传限流 (次数,秒) |
| `RATE_LIMIT_API` | 30,60 | API 限流 (次数,秒) |

---

## 11. 安全模型摘要

| 组件 | 保护机制 |
|------|----------|
| 管理员登录 | pbkdf2 哈希, 双重渐进锁 (IP + 用户名, 5次→300s→900s→1800s), SQLite 持久化 |
| 管理员会话 | Flask session (httponly cookie), 最大 3 并发, 活跃续期, 踢出旧会话 |
| CSRF | Double-Submit Cookie 模式, 蓝图级 `before_request` 校验 |
| API 限流 | 分类别 IP 级限流 (图片/上传/API), 每日上传配额 |
| 敏感数据 | AES-256-GCM (SECRET_KEY → SHA256 → 32-byte key), 加密失败抛异常 |
| Token 认证 | Bearer Token, 可绑定 TG 用户, 可使用次数限制 |
| 文件访问 | 签名文件 ID (HMAC-SHA256), 访问计数追踪 |
| 热更新 | 白名单仓库, SHA256 校验, 逐文件 `os.path.realpath` 路径穿越防御, 自动回滚 |
| XSS 防护 | 前端 HTML 用 DOMPurify 净化, CSP 头 + X-Content-Type-Options |
| SQL 注入 | 全程参数化查询 (`?` 占位符), 无拼接 SQL |

### 登录锁定机制详解

登录暴力破解防御使用 **双重维度锁定**：

1. **IP 维度** (`login_attempts` 表, key=IP): 追踪单个 IP 在 15 分钟窗口内的失败次数
2. **用户名维度** (`login_attempts` 表, key=`uname:<user>\t<IP>`): 跨 IP 追踪同一用户名的总失败次数

每次登录检查时取两个维度的**最小值**作为剩余尝试次数。任一维度达到阈值即触发锁定。成功登录后清除该用户名在所有 IP 上的失败记录。

---

## 12. 已知限制

1. **单进程**: waitress 4 线程，高并发时 WebSocket/长连接会阻塞
2. **SQLite**: 写并发受限, 不适合 >100 用户同时上传
3. **无 CDN 绕过**: 如果 Cloudflare 缓存未命中，每次 /image/* 请求都从原后端拉取
4. **Telegram Bot API 限制**: 文件 ≤20MB 走 Bot API, >20MB 走 Kurigram/MTProto (需 app api_id/hash)
5. **Windows 支持**: 锁机制用于测试/开发，生产建议 Docker/Linux

---

## 13. 版本历史与变更追踪

| 版本 | 关键变更 |
|------|----------|
| 2.0.4+ | 安全加固: 双重维度登录锁 (IP+用户名), Zip Slip 彻底防御, AES-GCM fail-close, 日志级别升级 |
| 2.0.4 | 多后端存储, 画集系统, TG 认证, 自定义域名, CDN 监控 |
| 1.x | 仅 Telegram 后端, 基础管理后台 |

---

> 最后更新: 2026-06-02 | 基于安全审计修复后更新

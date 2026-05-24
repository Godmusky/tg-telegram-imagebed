# Telegram 云图床 Pro - 前端

基于 Nuxt 3 + Vue 3 + Nuxt UI 构建的现代化图床前端应用。

## ✨ 特性

- 🎨 **现代化 UI** - Nuxt UI 组件库，深色模式支持
- 🚀 **高性能** - Nuxt 3 SPA 模式，客户端渲染
- 📱 **响应式设计** - 桌面端和移动端完美适配
- 🔐 **管理后台** - 完整的仪表盘、图片管理、Token 管理、存储配置
- 🖼️ **画集系统** - 公开/私有/Token/密码四种访问模式
- 🏠 **画集站点** - 独立的前端展示站，支持 SEO 配置
- 📚 **API 文档** - 内置 `/docs` 交互式 API 文档页
- 🔗 **TG 认证** - Telegram 登录绑定、身份管理、会话控制
- 🗄️ **多存储管理** - 可视化配置 Telegram/S3/Local/rclone

## 🛠️ 技术栈

- **框架**: Nuxt 3
- **UI 库**: Nuxt UI
- **状态管理**: Pinia
- **包管理**: npm / pnpm
- **语言**: TypeScript

## 📦 安装

### 前置要求

- Node.js >= 20
- npm 或 pnpm

### 安装依赖

```bash
cd frontend
npm install
# 或
pnpm install
```

## 🚀 开发

### 启动开发服务器

```bash
npm run dev
```

访问 http://localhost:3000 ，确保后端已在 `18793` 端口运行。

### API 地址配置

默认请求同域后端（生产模式由 Flask 同端口托管）。开发时可在 `.env` 中覆盖：

```env
NUXT_PUBLIC_API_BASE=http://localhost:18793
```

## 🏗️ 构建

```bash
# 生产构建
npm run build

# 生成静态站点（供后端托管）
npm run generate
```

产物在 `frontend/.output/public`，Docker 构建时自动由多阶段构建复制到 `/app/frontend/.output/public`。

## 📁 项目结构

```
frontend/
├── app.vue                    # 应用入口
├── nuxt.config.ts             # Nuxt 配置
├── app.config.ts              # 应用主题配置
├── assets/
│   └── css/main.scss          # 全局样式
├── components/
│   ├── admin/                 # 管理后台组件
│   │   ├── AdminShell.vue     # 后台主框架
│   │   ├── AdminSidebar.vue   # 侧边导航
│   │   ├── AdminTopbar.vue    # 顶栏
│   │   ├── dashboard/         # 仪表盘组件
│   │   ├── images/            # 图片管理（网格/列表/瀑布流）
│   │   ├── tokens/            # Token 管理
│   │   ├── storage/           # 存储配置
│   │   ├── settings/          # 系统设置
│   │   ├── seo/               # SEO 配置
│   │   ├── announcement/      # 公告管理
│   │   └── profile/           # 用户中心
│   ├── album/                 # 画集组件
│   │   ├── AlbumImageGrid.vue
│   │   ├── AlbumGalleryList.vue
│   │   ├── AlbumGalleryDetail.vue
│   │   └── ...
│   ├── gallery-share/         # 画集分享组件
│   ├── gallery-site/          # 画集展示站组件
│   ├── home/                  # 首页组件
│   │   ├── HomeUploadZone.vue       # 拖拽上传区
│   │   ├── HomeUploadResults.vue    # 上传结果
│   │   └── HomeUploadHistory.vue    # 上传历史
│   ├── MeConsoleShell.vue     # 个人控制台
│   ├── MeTokenPanel.vue       # Token 面板
│   ├── MeOverviewPanel.vue    # 概览面板
│   ├── MeTgBindPanel.vue      # TG 绑定
│   ├── MeTgIdentityPanel.vue  # TG 身份
│   ├── MeSessionPanel.vue     # 会话管理
│   ├── TgLoginModal.vue       # TG 登录弹窗
│   ├── AuthLoginModal.vue     # 管理员登录弹窗
│   ├── GalleryLightbox.vue    # 图片灯箱
│   └── MasonryGrid.vue        # 瀑布流布局
├── composables/               # 组合式函数
│   ├── useUpload.ts           # 上传逻辑
│   ├── useImageApi.ts         # 图片 API
│   ├── useGalleryApi.ts       # 画集 API
│   ├── useGallerySite.ts      # 画集站点
│   ├── useAdminImages.ts      # 后台图片管理
│   ├── useNotification.ts     # 通知系统
│   └── ...
├── layouts/
│   ├── default.vue            # 默认布局
│   ├── admin.vue              # 后台布局
│   ├── admin-login.vue        # 后台登录布局
│   ├── gallery-site.vue       # 画集站点布局
│   └── gallery-site-admin.vue # 画集站点管理布局
├── middleware/
│   ├── auth.ts                # 后台认证
│   └── gallery-site.global.ts # 画集站点全局中间件
├── pages/
│   ├── index.vue              # 首页（上传）
│   ├── album.vue              # 我的画集
│   ├── me.vue                 # 个人中心
│   ├── setup.vue              # 初始化向导
│   ├── guest.vue              # 游客页
│   ├── tg-login.vue           # TG 登录页
│   ├── docs.vue               # API 文档
│   ├── g/
│   │   └── [token].vue        # Token 画廊
│   ├── galleries/
│   │   └── [token]/
│   │       ├── index.vue      # 画集列表
│   │       └── [id].vue       # 画集详情
│   ├── admin/
│   │   ├── index.vue          # 后台首页/登录
│   │   ├── dashboard.vue      # 仪表盘
│   │   ├── images/index.vue   # 图片管理
│   │   ├── galleries/         # 画集管理
│   │   ├── tokens/            # Token 管理
│   │   ├── storage.vue        # 存储配置
│   │   ├── settings.vue       # 系统设置
│   │   ├── seo.vue            # SEO 配置
│   │   └── announcements/     # 公告管理
│   └── gallery-site/          # 画集独立站点
│       ├── index.vue          # 站点首页
│       ├── galleries/         # 画集浏览
│       └── admin/             # 站点管理后台
├── stores/                    # Pinia 状态管理
│   ├── auth.ts                # 认证状态
│   ├── adminUi.ts             # 后台 UI 状态
│   ├── tgAuth.ts              # TG 认证
│   ├── notification.ts        # 通知
│   └── token.ts               # Token 状态
├── types/                     # TypeScript 类型定义
├── utils/                     # 工具函数
└── public/
    └── favicon.ico
```

## 🎯 功能模块

### 首页 `/`
- 拖拽上传图片，批量上传
- 实时上传进度
- 多种链接格式（URL / Markdown / HTML / BBCode）
- 上传历史记录

### 个人中心 `/me`
- Token 创建与管理
- Telegram 账号绑定
- 身份信息与权限
- 会话管理

### 画集 `/album` · `/galleries/:token`
- 创建和管理个人画集
- 公开 / 私有 / Token / 密码四种访问模式
- 画集分享链接
- 瀑布流图片浏览

### 画集站点 `/gallery-site`
- 独立的公开展示站
- SEO 配置与元数据管理
- 独立的管理后台

### API 文档 `/docs`
- 交互式 API 文档
- 多语言代码示例

### 管理后台 `/admin`
- **仪表盘** — 运行统计与系统概览
- **图片管理** — 浏览、搜索、删除，支持网格/列表/瀑布流视图
- **画集管理** — 全局画集管理
- **Token 管理** — 创建、配置限制、查看使用统计
- **存储配置** — 多后端配置、场景路由、健康检查
- **系统设置** — 全局参数、TG Bot 配置
- **SEO 配置** — 站点元数据
- **公告管理** — 系统公告发布

## 🔐 认证流程

管理后台登录后 token 存储在 localStorage，`auth` 中间件拦截未认证访问。TG 认证通过 Telegram Login Widget 完成身份绑定。

## 📝 开发规范

- TypeScript + Vue 3 Composition API
- Nuxt UI 组件库
- Pinia 状态管理

## 🐛 调试

### Nuxt DevTools

开发模式下按 `Shift + Alt + D` 打开。

### 常见问题

**Q: API 请求失败？**
A: 确认后端在 `18793` 端口运行，或检查 `.env` 中 `NUXT_PUBLIC_API_BASE`。

**Q: 页面样式异常？**
A: 运行 `npm install` 确保依赖完整。

**Q: 构建失败？**
A: 清除缓存后重试：`rm -rf .nuxt node_modules && npm install`

## 📄 许可证

MIT License

# 快速开始指南

## 🚀 5 分钟快速启动

### 1. 安装依赖

```bash
cd frontend
npm install
```

### 2. 配置 API 地址（仅开发模式需要）

开发时前端独立运行在 `localhost:3000`，需要指向后端：

```bash
echo 'NUXT_PUBLIC_API_BASE=http://localhost:18793' > .env
```

生产环境由 Flask 同端口托管，无需此配置。

### 3. 启动

```bash
# 终端 1: 启动后端
cd ..
python main.py

# 终端 2: 启动前端
cd frontend
npm run dev
```

### 4. 访问应用

打开浏览器访问: http://localhost:3000

## 📝 首次初始化

首次启动后访问任意页面会自动跳转到 `/setup` 初始化向导，按提示完成管理员账号创建和基础配置。

## 🎯 主要功能

### 首页 `/`
- 拖拽上传图片
- 批量上传
- 获取多种格式链接

### 个人中心 `/me`
- 创建 Token
- TG 账号绑定
- 会话管理

### 画集 `/album`
- 创建和管理画集
- 分享链接

### API 文档 `/docs`
- 查看 API 使用说明
- 在线测试上传

### 管理后台 `/admin`
- 查看统计数据
- 管理图片和画集
- 系统配置

## 🔧 常用命令

```bash
# 开发
npm run dev

# 构建
npm run build

# 生成静态站点
npm run generate
```

## ❓ 遇到问题？

1. 确保 Node.js >= 20
2. 确保后端 API 正常运行（`python main.py`）
3. 检查 `.env` 配置是否正确
4. 查看浏览器控制台错误信息

祝您使用愉快！🎉

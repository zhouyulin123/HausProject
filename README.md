# 豪斯 AI 家装定制助手

当前项目由 React/Vite 前端、FastAPI 后端、MySQL 数据库和可选的 Blender/GPU Worker 组成。

## 本地运行基线

- Node.js 20–24，使用仓库内 `package-lock.json` 和 `npm ci`。
- Python 3.12 为 CI 基线；当前 Windows 开发环境的 Python 3.14 也纳入回归验证。
- MySQL 8，数据库结构必须通过 Alembic 迁移。
- Blender 和 Stable Diffusion 是可选 Worker，不应阻塞基础 API 启动。

复制 `.env.example` 为 `.env` 并填写数据库与模型配置。Windows 可执行：

```powershell
.\startHaus.bat --check
.\startHaus.bat
```

启动完成后访问 `http://127.0.0.1:8080`。项目统一使用 IPv4 回环地址，避免 Windows 下 `localhost` 在 IPv4/IPv6 之间命中不同开发进程。

前端独立运行：

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

后端基础依赖与测试：

```powershell
py -3.12 -m pip install -r backend/requirements-dev.txt
$env:PYTHONPATH="backend"
py -3.12 -m pytest backend/tests -p no:cacheprovider
```

需要本地 GPU 效果图能力时，额外安装 `backend/requirements-gpu.txt`，并按显卡和 CUDA 版本单独安装 PyTorch。

## 环境边界

- `APP_ENV=production` 时，应用会拒绝调试模式、默认 JWT 密钥、root/弱密码数据库账号和本地 CORS 地址。
- 前端 Mock 降级默认关闭。只有纯展示环境才在 `frontend/.env` 中设置 `VITE_DEMO_MODE=true`。
- `/health` 仅表示进程存活；`/ready` 会检查数据库与上传目录，启动器使用 `/ready` 决定是否打开页面。
- 登录使用 HttpOnly、SameSite Cookie；Bearer JWT 暂时保留用于旧客户端迁移和接口调试。

## 质量门禁

GitHub Actions 会执行后端依赖检查、编译和测试，以及前端类型检查、测试和生产构建。数据库结构修改必须附带 Alembic 迁移。

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

普通 `quality` 工作流只检测模型、Prompt、布局规则和商品数据契约变更，并明确输出是否需要真实回归证明；它没有私有案例和密钥，不会宣称真实案例门禁通过。相关变更发布前必须在目标提交上手工触发 `real-world-release-gate`，由带 `real-world-eval` 标签的 self-hosted runner 和受保护的 `real-world-evaluation` Environment 完整执行 development、regression、blind 三组。仓库分支保护还需把 `real-world-release-proof` 设置为发布必需检查。

受控门禁不接受合成案例、首次建基线或调用方填写指标；即使仓库路径检测未命中，它也会完整执行三组，以覆盖由部署配置引起的模型或商品版本变化。它会现场执行真实 HTTPS 跨用户检查、从数据库签发 trusted evidence 5.0、核对候选构建与四类运行版本，并从目标提交复算 Prompt/规则摘要、核对受控部署模型名，防止旧运行冒充当前候选；之后在同一真实案例集上比较已签名基线。缺案例、缺密钥、证据错配或质量下降均失败关闭。上传产物只包含聚合指标和匿名摘要，不包含会话、任务/运行主键或私有路径。

真实案例评测的跨用户安全指标只能来自 `evals.collect_security_access_evidence` 对受控 HTTPS 部署执行的 owner/foreign 会话检查。安全制品使用独立于普通评测证据的 HMAC key 签名，并绑定应用构建、模型/Prompt/规则/数据版本、split、数据集及匿名运行引用；缺失、过期、错配、零分母或验签失败均保持门禁关闭。详细流程见 `backend/evals/cases/real_world/README.md`。

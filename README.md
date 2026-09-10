# 豪斯 AI 家装定制助手

豪斯是一个面向家装设计场景的多模态 AI 应用。用户可以上传户型图或房间照片，通过自然语言补充空间、风格、预算和配送地区等要求；系统随后完成空间分析、需求确认、商品筛选、方案生成、确定性报价、3D 场景编辑与效果图渲染。

项目不是单一的 AI 生图演示。核心设计原则是：**模型负责理解与规划，受控工具负责执行，确定性规则负责校验，高风险结果交由人工审批。**

## 当前状态

- 用户主流程已统一到设计工作台，覆盖需求确认、Agent 执行、方案、场景、报价、渲染和反馈。
- 方案生成、效果图和 Blender 渲染使用数据库持久化 Worker，支持租约、心跳、取消、重试和死信。
- 工程回归、权限隔离和发布证据链已经建立。
- 真实业务质量仍待至少 20 个脱敏授权案例、人工标注和商业可用商品完成受控验收；当前不能宣称真实业务指标已经达标。

详细进度和已知边界见 [`PROJECT_STATUS.md`](./PROJECT_STATUS.md)。

## 核心能力

- **多模态需求理解**：通过 OpenAI 兼容接口接入文本模型和视觉模型，解析用户需求并从户型图或房间照片生成结构化 `RoomModel`。
- **可恢复设计智能体**：基于 LangGraph 编排事实校验、结构化追问、商品检索、工具执行、质量验证、有限重试和人工接管。
- **受控工具调用**：智能体只能调用已注册的商品检索、方案生成、场景编辑和定制家具工具，不能自由执行代码或直接写入业务数据。
- **确定性业务门禁**：商品、价格、预算、地区、库存、交期、尺寸和资产审核由服务端规则判定，方案与报价使用版本化快照。
- **空间设计与 3D 编辑**：支持自动布局、越界与碰撞检查、门洞净空校验、家具增删改移、场景版本恢复和 GLB 资产展示。
- **异步生成与渲染**：方案生成、Stable Diffusion 效果图和 Blender 渲染与 API 进程解耦，失败状态和执行成本可追踪。
- **质量与安全治理**：支持高风险施工意图拦截、人工审批、匿名质量指标、失败分诊、可信评测证据和发布门禁。

## 系统架构

```text
React / TypeScript / Three.js
             |
             v
        FastAPI 接口层
             |
     +-------+--------+
     |       |        |
 LangGraph  业务服务   版本化场景/报价
 设计智能体  与规则层   及资产快照
     +-------+--------+
             |
        MySQL / Alembic
             |
     +-------+----------------+
     |                        |
方案生成 Worker       效果图 / Blender Worker
```

设计智能体的主流程为：

```text
事实校验 -> 缺失信息追问 -> 商品检索 -> 工具执行
   -> 结果验证 -> 完成 / 重规划 / 人工审批 / 人工接管
```

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | React 18、TypeScript、Vite、React Router、Zustand、Tailwind CSS、Framer Motion |
| 3D | Three.js、React Three Fiber、Drei、GLB |
| 后端 | Python、FastAPI、Pydantic、SQLAlchemy、Alembic |
| 数据库 | MySQL 8；测试环境支持 SQLite 隔离验证 |
| AI | LangGraph、OpenAI 兼容接口、DeepSeek、Qwen-VL |
| 生成与渲染 | Stable Diffusion、Blender、独立持久化 Worker |
| 工程质量 | Pytest、Vitest、TypeScript、GitHub Actions、真实案例发布门禁 |

## 目录结构

```text
MyselfProject/
├── backend/
│   ├── app/
│   │   ├── agents/       # LangGraph 智能体工作流
│   │   ├── api/          # FastAPI 路由
│   │   ├── db/           # 数据模型与数据库连接
│   │   ├── services/     # 业务服务与确定性规则
│   │   └── workers/      # 方案、效果图和 Blender Worker
│   ├── evals/            # 离线评测、可信证据与失败分诊
│   └── migrations/       # Alembic 数据库迁移
├── tests/
│   ├── unit/             # 后端快速单元测试
│   └── integration/      # 后端接口、数据库与跨服务集成测试
├── frontend/
│   ├── public/           # 图片和 GLB 等静态资源
│   ├── src/              # 页面、组件、状态、接口和 3D 逻辑
│   └── build/            # Vite 构建配置及对应测试
├── case_image/           # 演示案例图片
├── outputs/              # 本地生成或运营草稿
└── startHaus.bat         # Windows 本地启动入口
```

## 测试组织

正式测试保留两种符合各自技术生态的组织方式：

- 后端测试集中在仓库根目录 `tests/`，按 `unit` 和 `integration` 分层，由根目录 `pytest.ini` 统一发现；`backend/` 只保留项目代码和运行配置。
- 前端 Vitest 测试与被测模块放在同一目录，使用 `*.test.ts` 或 `*.test.tsx` 命名，便于维护相对导入和同步修改。
- `.pytest-tmp-*`、`.test_artifacts`、覆盖率结果和缓存均为可再生测试产物，不属于正式测试源码，并通过 `.gitignore` 排除。

不要将全部测试合并为单个文件。按领域拆分可以隔离失败、支持定向执行，并降低多人修改时的冲突。

## 环境要求

- Node.js 20–24，使用仓库内 `package-lock.json` 和 `npm ci`。
- Python 3.12 为持续集成基线。
- MySQL 8，数据库结构必须通过 Alembic 迁移。
- Blender 与 Stable Diffusion 为可选运行层，不应阻塞基础 API 启动。

## 快速开始

### 1. 配置环境变量

将 `.env.example` 复制为 `.env`，至少配置数据库和模型连接信息。前端演示模式需要单独将 `frontend/.env.example` 复制为 `frontend/.env`。

重要配置分组：

- `DATABASE_URL`：MySQL 连接地址。
- `LLM_*`：文本模型地址、模型名和密钥。
- `VL_*`：视觉模型地址、模型名和密钥。
- `JWT_*`：登录态签发配置；生产环境必须替换默认密钥。
- `SD_*`、`BLENDER_*`：可选效果图与 Blender 渲染配置。
- `GENERATION_*`、`EFFECT_RENDER_*`：异步任务租约、重试和超时配置。

完整配置见 [`.env.example`](./.env.example)。不要提交真实密钥。

### 2. 安装依赖

```powershell
npm --prefix frontend ci
py -3.12 -m pip install -r backend/requirements-dev.txt
```

需要本地 GPU 效果图能力时，额外安装：

```powershell
py -3.12 -m pip install -r backend/requirements-gpu.txt
```

PyTorch 应根据显卡和 CUDA 版本单独安装。

### 3. 检查并启动

```powershell
.\startHaus.bat --check
.\startHaus.bat
```

启动器会执行数据库迁移并等待服务就绪：

- 前端：`http://127.0.0.1:8080`
- 后端：`http://127.0.0.1:8081`
- 存活检查：`http://127.0.0.1:8081/health`
- 就绪检查：`http://127.0.0.1:8081/ready`

项目统一使用 IPv4 回环地址，避免 Windows 下 `localhost` 命中不同的 IPv4/IPv6 开发进程。

## 独立启动

前端：

```powershell
npm --prefix frontend run dev
```

后端：

```powershell
Set-Location backend
python -m alembic upgrade head
python -m app.run_api --port 8081
```

按需要启动异步 Worker：

```powershell
Set-Location backend
python -m app.workers.generation_worker
python -m app.workers.effect_render_worker
python -m app.workers.blender_worker
```

生产环境应由进程管理器分别监管 API 和 Worker，不要依赖本地批处理脚本维持服务。

## 验证命令

后端快速测试：

```powershell
$env:APP_ENV = "test"
$env:PYTHONPATH = "backend"
python -m pytest tests/unit -p no:cacheprovider
```

后端全量测试：

```powershell
$env:APP_ENV = "test"
$env:PYTHONPATH = "backend"
python -m pytest -p no:cacheprovider
```

开放几何合成开发评测（只验证工程契约，不代表真实用户质量）：

```powershell
$env:PYTHONPATH = "backend"
python -m evals.run_open_geometry_eval --output .test_artifacts/open_geometry_eval.json
```

前端完整验证：

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
```

GitHub Actions 会执行 Python 依赖检查、开放几何工程契约评测、后端测试、前端类型检查、测试和生产构建。模型、提示词、布局规则、开放几何契约/渲染器或商品数据契约发生变化时，发布前还必须在受控环境运行真实案例门禁。

## 生产安全边界

- `APP_ENV=production` 时，应用会拒绝调试模式、默认 JWT 密钥、弱数据库凭据和本地 CORS 地址。
- 登录默认使用 HttpOnly、SameSite Cookie；Bearer JWT 仅用于旧客户端迁移和接口调试。
- `/health` 只表示进程存活；`/ready` 还会检查数据库版本和上传目录，部署系统应以 `/ready` 作为接流量依据。
- 未审核商品资产不能进入正式方案和 Blender 交付路径。
- 真实案例、评测证据和用户原始内容不得写入公开持续集成制品。

## 延伸文档

- [`AI家装智能体架构与接口契约.md`](./AI家装智能体架构与接口契约.md)：智能体状态与接口契约。
- [`AI家装智能体上线开发方案.md`](./AI家装智能体上线开发方案.md)：生产化路线和验收边界。
- [`backend/GENERATION_WORKER.md`](./backend/GENERATION_WORKER.md)：方案生成 Worker。
- [`backend/EFFECT_RENDER_WORKER.md`](./backend/EFFECT_RENDER_WORKER.md)：效果图 Worker。
- [`backend/BLENDER_WORKER.md`](./backend/BLENDER_WORKER.md)：Blender 渲染 Worker。
- [`backend/CATALOG_LIFECYCLE.md`](./backend/CATALOG_LIFECYCLE.md)：商品目录生命周期。

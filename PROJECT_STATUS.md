# 项目开发状态记录

## 2026-07-29 V2 项目接管与方向确认

- 当前第一产品目标调整为：**客户无需登录即可自行完成房屋定制的智能化应用**
- 服务端前期负责提供商品、材料、报价规则、模型和生成能力；员工销售端与用户登录后置
- 允许使用 `.env` 中已配置的 AI 模型，并以高质量模拟商品、材料、案例和图片先完成可用闭环
- GitHub 仓库：`zhouyulin123/HausProject`，接管时为空仓库
- 新增 `AI家装项目V2开发路线.md`，明确工程底座、客户自助闭环、LangGraph Agent、空间图像、提案后台和后续商业能力六个阶段
- 当前施工顺序：Git 安全基线 → 工程加固 → 匿名会话与方案版本 → LangGraph Agent V1

### 当前约束

- `.env`、用户上传、模型缓存和构建产物不得进入 Git
- 商品 SKU、材料单价和报价计算必须由数据库与确定性程序提供，AI 不得编造
- 模板或 Mock 降级必须明确标识，不得作为真实 AI 成功结果展示
- 数据库暂无真实业务数据，但结构变化仍通过迁移管理，避免形成不可维护的手工表结构

### 下一步

1. 初始化 Git 并连接 GitHub 空仓库
2. 补齐依赖、迁移、测试与运行说明
3. 修复任务失败状态、上传校验和前端静默降级
4. 设计并实现匿名客户会话与方案持久化

### 第一批工程加固结果

- 已初始化 Git，`main` 已同步至 `zhouyulin123/HausProject`
- 已配置仓库级 GitHub noreply 提交身份，不修改本机全局 Git 设置
- 已验证 `.env`、上传文件、Excel 临时文件、模型缓存、依赖和构建产物不会进入 Git
- 新增 pytest 测试底座和开发依赖文件
- 图片上传新增大小、MIME、文件签名和扩展名校验，使用检测到的可信格式保存
- 方案生成发生非预期异常时会回滚并持久化 `failed`、错误原因和归零进度
- 移除设计结果中的假 PDF 地址，真实 PDF 只由提案接口生成
- 补齐 `reportlab`、`openpyxl` 运行依赖及 `.env.example` 的模型和上传配置

### 验证

- `python -m pytest tests/integration/test_task_generation_failure.py tests/unit/test_upload_validation.py`：7 passed
- `python -m compileall -q app`：通过
- `python list_routes.py`：全部 API 路由正常注册
- GitHub `main` 已核对到提交 `0be6582`

### 第二批：匿名客户会话与刷新恢复

- 新增 `anonymous_sessions`：无需登录的客户会话，默认有效期 30 天
- 新增 `anonymous_session_images`、`anonymous_session_tasks`：明确图片和设计任务的会话所有权
- 新增 API：
  - `POST /api/sessions`
  - `GET /api/sessions/{session_id}`
  - `GET /api/sessions/{session_id}/tasks`
- 创建任务时验证上传图片归属，禁止另一个匿名会话复用图片
- 图片上传支持 `X-Session-ID` 并自动建立所有权关系
- 前端使用 localStorage 保存匿名会话、当前任务和上传图片编号
- 当前生成方案也会本地持久化，刷新结果页或详情页后不再直接丢失
- 新增 Vitest 前端测试入口
- 已在当前 MySQL 安全创建 3 张新增表，未删除或修改旧表数据

### 第二批验证

- 后端：`12 passed`
- 前端：`4 passed`
- 前端生产构建：通过
- MySQL 新增会话表存在性检查：通过
- 剩余风险：任务查询和生成接口还需强制校验 `X-Session-ID`；尚未引入 Alembic
- Vitest 已从 2 升级到 4.1.10，清除测试工具的 critical 告警；当前剩余 4 项（3 moderate、1 high），来自旧 Vite/esbuild 和 React Router，需通过受控主版本升级处理，不能直接执行破坏性 `npm audit fix --force`

### 第三批：匿名会话隔离与数据库迁移

- 所有设计任务读取、需求确认、方案生成和结果查询强制要求 `X-Session-ID`
- 聊天、效果图和提案 PDF 在携带 `task_id` 时强制验证任务归属
- 对“不存在的任务”和“其他会话的任务”统一返回 404，避免通过连续编号枚举客户数据
- 权限校验发生在 DeepSeek、SD 和 PDF 服务调用之前，越权请求不会消耗模型额度
- smoke test 已升级为：创建匿名会话 → 带会话上传 → 创建任务 → 生成与导出
- 新增客户主路由注册测试，避免路由模块语法错误漏过服务测试
- 引入 Alembic 1.18：
  - 全新数据库可直接 `python -m alembic upgrade head`
  - 当前 MySQL 已安全接管到 `3e9d6b1a7c42 (head)`
  - 统一 `design_tasks.customer_id` 索引并补齐客户外键
  - 应用启动不再隐式 `create_all`，一键启动会先迁移再启动

### 第三批验证

- 后端：`24 passed`
- 前端：`4 passed`
- 前端生产构建：通过
- 空 SQLite 从零迁移到 head：通过
- 当前 MySQL `alembic current`：`3e9d6b1a7c42 (head)`
- `alembic check`：`No new upgrade operations detected`

### 第四批：方案版本、报价快照与可信提案

- 新增 `design_revisions`、`design_plan_versions`、`quote_snapshots`：
  - 每次方案生成形成递增版本，保存当时的确认需求、图片分析上下文、生成器和完整方案
  - 每个方案保存独立报价快照，历史版本不随商品或报价规则变化而漂移
  - 数据库外键和唯一约束保证任务版本、方案编号与报价一一对应
- 方案生成在同一事务内同时写入旧结果兼容记录和新版快照，失败时整体回滚
- 新增客户会话内的版本查询：
  - `GET /api/design/tasks/{task_id}/versions`
  - `GET /api/design/tasks/{task_id}/versions/{version}`
- 原结果接口优先读取最新正式版本；旧任务没有版本快照时仍兼容旧结果
- 结果页刷新后优先从服务端恢复当前任务，不再依赖浏览器缓存中的完整方案
- 提案 PDF 改为只接收 `task_id + plan_id`：
  - 方案名称、家具明细和报价从服务端最新快照读取
  - 客户端提交的伪造方案内容不会进入 PDF
  - 导出文件名使用数据库方案版本 ID，不使用外部方案字符串拼接路径
- 当前 MySQL 已升级至 `6c4679cf9722 (head)`

### 第四批验证

- 后端：`29 passed`
- 前端：`5 passed`
- 前端 TypeScript 检查与生产构建：通过
- 空 SQLite 从零迁移到最新 head：通过
- 当前 MySQL `alembic current`：`6c4679cf9722 (head)`
- `alembic check`：`No new upgrade operations detected`

### 接下来

1. 为方案版本增加前端历史版本查看与“基于此版本继续优化”
2. 增加预算上限条件分支和确定性调整策略
3. 处理前端大包拆分和受控依赖升级（当前构建主包约 1.32 MB）

### 第五批：LangGraph Agent V1 首条生产工作流

- 移除原有只返回 `{"status": "mocked"}` 的单节点占位 Graph
- 引入 LangGraph 1.x 正式依赖，并建立类型化 `DesignAgentState`
- 生产方案生成接口已切换至四节点工作流：
  1. `prepare_context`：合并确认需求与真实图片分析上下文
  2. `generate_plans`：调用 DeepSeek；仅在明确不可用时进入模板降级，并记录原因
  3. `calculate_quote`：调用商品库校验与确定性报价，AI 不能决定 SKU 单价
  4. `validate_quality`：校验有效商品、报价结构和合计一致性，未通过时整次任务失败
- 所有节点记录状态、来源与耗时；模板降级额外记录 `fallback_reason`
- 工作流轨迹随方案版本写入 `workflow_trace_snapshot`，可通过版本详情接口查询
- 工作流使用依赖注入连接现有模型、模板和报价服务，测试不调用付费模型
- 当前 MySQL 已升级至 `c19eadef8b8b (head)`

### 第五批验证

- LangGraph 工作流单测覆盖真实生成、模板降级、报价门禁：`3 passed`
- 工作流、版本快照和生产生成接口组合测试：`9 passed`
- 后端完整回归：`33 passed`
- Python 编译检查：通过
- 空 SQLite 从零迁移到最新 head：通过
- 当前 MySQL `alembic current`：`c19eadef8b8b (head)`
- `alembic check`：`No new upgrade operations detected`

### LangGraph 下一步

1. 增加预算上限条件分支：超限时自动调整商品组合或明确提示
2. 增加“基于历史版本继续优化”的工作流入口

### 第六批：付费模型验收与持久化后台生成

- 使用当前 `.env` 配置执行一次真实 DeepSeek 付费冒烟：
  - 输入 96㎡三室两厅、儿童家庭、原木/现代简约需求和两条图片空间观察
  - 真实生成 3 套方案，每套 4 个经商品库校验的 SKU
  - 三套确定性商品报价分别为 ¥33,840、¥31,879、¥47,180
  - `generate_plans` 耗时约 24.95 秒，确定性报价耗时约 16ms
  - `generator=llm`，未进入模板降级
- 新增 `generation_runs` 和 `generation_run_events`：
  - 保存 attempt、queued/running/completed/failed、真实进度、当前节点与错误
  - 每个 LangGraph 节点完成后立即写入来源、耗时和详细信息
  - 活动任务自动复用，避免刷新或重复点击造成重复付费调用
  - 失败后创建递增 attempt，可查询历史失败依据并重新执行
- 新增后台生成接口：
  - `POST /api/design/tasks/{task_id}/generate-async`
  - `GET /api/design/tasks/{task_id}/generation`
- 后台执行器使用独立数据库会话，不复用请求结束后的 SQLAlchemy Session
- 前端生成流程改为入队、轮询持久化状态、完成后读取正式方案
- 保留原同步生成接口兼容已有内部调用
- 当前 MySQL 已升级至 `75fbc557e2ce (head)`

### 第六批验证

- 后端完整回归：`38 passed`
- 前端完整回归：`6 passed`
- 前端 TypeScript 检查与生产构建：通过
- 空 SQLite 从零迁移到最新 head：通过
- 当前 MySQL `alembic current`：`75fbc557e2ce (head)`
- `alembic check`：`No new upgrade operations detected`

### 后台任务边界

- 当前使用 FastAPI `BackgroundTasks`，适合现阶段单机、小范围客户试用和 I/O 型模型请求
- 数据状态已经持久化，但进程在模型调用中途退出时不会自动接管未完成任务
- 多进程或正式公网规模前需切换到 Redis + 独立 worker；现有 run/event 表可以直接作为任务状态层复用

### Windows 一键启动器修复

- 修复 `启动豪斯.bat` 使用 LF 换行时被 `cmd.exe` 拆坏命令的问题
- 新增 `.gitattributes`，强制所有 `.bat` 文件保持 Windows CRLF 换行
- 启动目录改为安全引用 `"%~dp0"`，兼容项目路径包含空格
- 新增 `启动豪斯.bat --check`，可在不启动服务窗口的情况下检查 Python、npm 和数据库迁移环境
- 当前机器启动器自检通过，数据库版本为 `75fbc557e2ce (head)`

## 2026-07-24 一键启动脚本 + 3D 布局（最小验证）

- 施工：Claude Code
- 当前状态：3D 布局 MVP 跑通（Three.js 参数化，规则式摆位）；Agent 化下一步做

### 已完成

- **一键启动脚本** `启动豪斯.bat`（项目根）：检测/装前端依赖 → 起后端 8081 + 前端 8080 → 5s 后自动开浏览器
- **3D 布局 MVP**（Three.js / react-three-fiber）：
  - 依赖：three@0.160 + @react-three/fiber@8 + @react-three/drei@9
  - `src/lib/roomLayout.ts`——规则式布局引擎：解析家具尺寸文本，按类别摆位（沙发靠后墙、茶几在前、柜子靠前墙、床靠侧墙、灯具落角、其余沿墙排布），输出场景坐标（米）
  - `src/components/design/RoomView3D.tsx`——渲染房间盒子（地面+两面墙+网格）+ 家具体块（悬停显示名称）+ OrbitControls（拖动旋转/滚轮缩放）
  - 方案详情页新增「3D 布局」Tab，聚焦用户主选空间
- **踩坑修复**：
  - r3f Canvas 在 framer-motion tab 动画中挂载时初次测量失败（卡 300×150）→ 挂载后触发一次 resize 兜底
  - 详情页 tab 的 AnimatePresence 已在早前移除，3D tab 才能正常挂载
  - Canvas 设 `frameloop="demand"` + `preserveDrawingBuffer`（降 CPU / 便于截图）

### 验证

- 布局引擎单测（Node 复刻逻辑跑真实家具数据）：客厅沙发 z=-1.8 靠后墙、茶几 z=-0.55 在沙发前、卧室床靠侧墙旋转 90°，坐标全部合理
- 浏览器：canvas 正确渲染 1654×688（WebGL 活跃）、信息条「客厅 · 4.6m×5.6m · N 件家具」正确、零控制台/服务端报错
- 注：WebGL 画布在当前工具环境下截图不稳定，未取到清晰像素图；需在浏览器实际查看（localhost:8080 → 任一方案详情 → 3D 布局）

### 下一步

1. **Agent 化**（用户已要求）：LangGraph / 工具调用，让 AI 能查商品库、算面积用料、按报价规则实算
2. 3D 可选增强：真实家具模型替换体块、拖动家具改布局、导出 3D 截图进提案

## 2026-07-23 (深夜) 店铺信息可配置：提案 PDF 品牌化

- 施工：Claude Code
- 当前状态：店名/电话/微信/地址/标语/logo 可在 /admin 网页配置，即时生效到提案 PDF

### 已完成

- **shop_settings 表**（单行 id=1）+ `shop_service`（首次访问用 .env 默认值播种，之后以库为准）
- **接口**：`GET/PUT /api/shop`、`POST /api/shop/logo`
- **PDF 品牌化**（`pdf_service.build_proposal_pdf` 接收 shop dict）：
  - 页头：有 logo 时展示 logo + 店名（Table 布局），否则纯店名
  - 页脚：标语 · 电话 · 微信 · 地址（按有值项拼接）
  - proposal 路由从 DB 读店铺信息并解析 logo 本地路径传入
- **前端**：`/admin` 新增「店铺设置」Tab（`ShopSettingsPanel`）——店名/标语/电话/微信/地址表单 + logo 上传预览，保存后提示「下次导出即生效」
- **config**：新增 `shop_name/shop_phone/shop_wechat/shop_address/shop_slogan` 默认值

### 验证

- API：默认播种「AI 家装定制助手」→ 改为「木言家居 · 全屋定制」+ 电话/微信/地址/标语 → 生成 PDF
- PDF 实测：页头显示「木言家居 · 全屋定制」，页脚完整拼出标语+电话+微信+地址
- 浏览器：设置页正确回显、网页改标语→保存→后端持久化确认；测试数据已重置为中性默认值
- 控制台零报错

### 后续可选

1. 前端站内页头/页脚也读 shop_name（目前仍是「AI 家装定制助手」占位；需 app 级加载店铺信息）
2. 客户详情页（点开看某客户全部方案与提案）
3. 权限/角色区分（客户端 vs 内部工具页）
4. 3D 布局（Three.js 参数化路线）

## 2026-07-23 (晚) 第三期（下）：商品库管理页 /admin

- 施工：Claude Code
- 当前状态：可在网页上直接维护商品库（不再只能靠 Excel），第三期完成

### 已完成

- **后端商品库写接口补齐**（`app/api/routes/products.py`）：
  - `PATCH /products/{id}`（编辑）、`POST /products/upload-image`（产品图上传，存 uploads/products/）
  - 定制规则 CRUD：`POST/PATCH/DELETE /products/quote-rules[/{id}]`
- **管理页 `/admin`**（导航「商品库」）：
  - 成品家具 Tab：搜索、卡片列表（缩略图/SKU/类别空间风格/价格）、新增/编辑弹窗（`ProductFormModal`，含图片上传预览）、内联确认下架（软删除）
  - 定制报价 Tab：表格展示 + 顶部快速新增行（项目/档位/单价/单位）+ 删除
  - 数据实时回读，改完立即反映到 AI 方案与报价单

### 验证

- 后端：新增→编辑（改价+卖点）→定制规则增删→软删除后不再出现在列表，全部正确
- 浏览器：/admin 加载 20 件真实产品与 SKU；UI 新增产品走通（20→21，列表即时出现）；定制报价表格正常；测试数据已清理回 20 件；控制台零报错

### 第三期完整回顾（本阶段三次提交）

1. AI 接通自家货：方案家具/报价全部来自商品库，后端回填真实价格
2. 品牌提案 PDF + 客户跟单
3. 商品库管理页 /admin

→ 现在从「录入产品 → AI 用自家货出方案+效果图 → 生成品牌报价 PDF → 客户建档跟单」全链路打通，是一套可用于自家生意的内部工具。

### 后续可选

1. 提案品牌信息可配置（店名/电话/logo，目前在 pdf_service.py 常量）
2. 客户详情页（点开看某客户全部方案与提案）
3. 权限/角色区分（客户端 vs 内部工具页）
4. 3D 布局（之前评估：Three.js 参数化路线，中等难度）

## 2026-07-23 (傍晚) 第三期（上）：品牌提案 PDF + 客户跟单

- 施工：Claude Code
- 当前状态：销售可一键生成带报价单的品牌提案 PDF 发客户；店内客户跟单页上线

### 已完成

- **品牌提案 PDF**（`app/services/pdf_service.py`，reportlab + 微软雅黑）：
  - 内容：品牌头 → 方案名/风格/推荐指数/预算 → 效果图（若该方案渲染过）→ 方案综述 → 布局建议 → **本店产品报价单**（成品+定制明细表，斑马纹，合计高亮）→ 温馨提示 → 页脚联系方式
  - 接口 `POST /api/design/proposal-pdf`（body: plan + task_id），PDF 存 `uploads/`，返回可微信转发的 URL
  - 品牌名/联系方式在 `pdf_service.py` 顶部常量（`SHOP_NAME`），待用户替换为自家品牌
  - 前端详情页「导出提案 PDF」按钮：生成中/已导出/失败三态，成功后自动打开 PDF 并把「我的方案」状态记为已导出
- **客户跟单**（店内轻 CRM）：
  - `customers` 表 + `design_tasks.customer_id` 列（手动 ALTER 迁移）
  - API：增/查/搜/改 + `attach-task`（把方案任务挂到客户名下）
  - 前端 `/customers` 页（导航「客户跟单」）：新增客户表单、姓名/电话搜索、方案数标签、「关联当前方案」按钮（当前会话生成过方案时出现）
- **修复**：PDF 大标题与 meta 行重叠（ParagraphStyle 缺 leading）

### 验证

- API：建客户→搜索→关联任务 13→详情显示 1 个方案；PDF 生成成功且报价单 7 行合计 ¥20,410 验算正确
- PDF 视觉：排版干净、中文正常、表格斑马纹与合计高亮符合品牌色
- 浏览器：客户页新增「李先生」成功、列表与方案数标签正确；详情页导出按钮走通（已导出状态 + 自动打开）

### 剩余（第三期下 + 后续）

1. 管理页 /admin：录入/编辑产品、上传产品图（当前靠 Excel 导入）
2. 提案 PDF 品牌信息可配置化（店名/电话/logo 进 .env 或设置页）
3. 客户详情页（点开看该客户全部方案与提案记录）
4. 效果图放进提案的覆盖率：生成方案后引导先渲染效果图再导出

## 2026-07-23 (下午) 商品库二期：AI 接通自家货

- 施工：Claude Code
- 当前状态：AI 方案的家具与报价全部来自自家商品库——「AI 只卖自家的货、只报自家的价」

### 已完成

- **桥接层**（`app/services/catalog_service.py`）：
  - `build_catalog_context`——商品库 + 定制价目表压缩成 LLM 上下文，随方案生成注入
  - `verify_and_enrich_plans`——LLM 返回后校验 SKU 有效性、**用数据库回填真实价格/材质/尺寸/图片**（AI 无法编造价格）、按价目表实算定制项小计、生成 shopQuote 汇总；无效 SKU 按风格从库中回退挑选；模板降级方案也走同一校验
- **Prompt 升级**：家具改为输出 `{sku, quantity, reason, alternative}`（必须来自商品库）；新增 `customItems`（从价目表选项目+档位，结合房屋面积估算工程量）
- **前端**：`ShopQuoteCard` 报价单组件（成品按件 + 定制按㎡/延米明细表 + 三行汇总）挂到详情页预算 Tab；家具 Tab 卡片支持 SKU 徽章与真实产品图
- **修复两个 bug**：
  1. EffectImage 内嵌 AnimatePresence 与详情页 tab 的 AnimatePresence 嵌套，exit 互相阻塞导致 tab 内容卡死 → 移除内层
  2. React 18 StrictMode 下 `AnimatePresence mode="wait"` 的 exit 完成回调失灵（内容 opacity 变 0 后不卸载、新内容不挂载）→ 详情页 tab 改为 key 重挂载 + 进入动画，不再依赖 exit 回调

### 验证

- API：三套方案家具 SKU 全部真实且组合各异（宠物家庭自动选中猫抓布沙发 SF-002）；定制项单价与价目表逐一对上（680×6.5=4420 等全部验算正确）
- 浏览器：预算 Tab 渲染完整报价单（4 件成品 + 3 项定制，合计 ¥23,504 验算无误）、家具 Tab SKU 徽章正常、tab 切换恢复流畅

### 下一步（第三期：成交武器）

1. 品牌提案 PDF：效果图 + 方案 + 本店报价单合成一份可发客户的文件
2. 客户跟单：客户记录（姓名/电话/户型图/出过的方案）
3. 简单管理页（/admin）：录入/编辑产品、传产品图

## 2026-07-23 商品库第一期：自家产品数据地基

- 施工：Claude Code
- 项目定位已明确：**为自家家具家装生意做 AI 赋能**（定制+成品混合、内部先用）
- 当前状态：商品库表结构 + 模拟数据 + API + 前端家具页切换到数据库，待用户导入真实产品

### 已完成

- **新表**（`app/db/models.py`）：
  - `products`——成品家具 SKU（名称/类别/空间/风格/材质/价格与区间/尺寸/卖点/替代选择/图片/软删除）
  - `custom_quote_rules`——定制报价规则（项目名/计价单位 ㎡·延米·项/材料档位/单价/说明）
- **种子数据**（`backend/seed_data.py`，`--force` 可重灌）：20 件成品（客厅/卧室/餐厅/书房全覆盖）+ 12 条定制规则（衣柜三档板材、橱柜延米、背景墙、榻榻米等，价格贴近行情）
- **Excel 导入工具**（`backend/import_products.py`）：`--template` 生成 `products_import.xlsx` 双工作表模板；导入按 SKU 去重（存在则更新）。**用户后期用它导入真实产品**
- **API**（`/api/products`）：列表（按空间/类别/风格过滤）、`/meta`（动态筛选项）、`/quote-rules`、创建/软删除（留给后续管理页）
- **前端家具页**：从数据库读取（`fetchFurnitureCatalog`，降级 mock）、筛选器选项随商品库动态生成、加载骨架屏、支持真实产品图（`image_url` 有值时覆盖渐变占位）

### 验证

- API：meta 返回 20 件商品与动态类别；客厅筛选 7 件；报价规则 12 条
- 浏览器：家具页渲染 20 件数据库商品（含 mock 中不存在的 SKU）、卧室筛选 5 件正确、控制台零报错

### 下一步（商品库二期，即「AI 接通自家货」）

1. DeepSeek 出方案时家具清单只从 `products` 表选（按风格/空间筛选后注入 prompt）
2. 报价改为：定制项按 `custom_quote_rules` 实算 + 成品按件累加，LLM 负责解释
3. 简单管理页（/admin）：录入/编辑产品，传产品图
4. 之后进入第三期：品牌提案 PDF + 客户跟单

## 2026-07-09 (夜) 本地效果图生成（SD1.5 + ControlNet）打通

- 施工：Claude Code
- 当前状态：核心卖点「效果图」落地——用户在方案详情页按需生成真实效果图，跑在本机 GPU

### 已完成

- **本地 SD 出图**（`app/services/sd_service.py`，RTX 5060 8G）：
  - 基础模型 Dreamshaper-8（SD1.5）+ ControlNet MLSD，共享组件省显存
  - 懒加载 + GPU 串行锁；实测单张 ~6-10s（模型加载后），峰值显存 ~3.6GB
  - 两条路径：**有上传照片** → MLSD 提结构线 → ControlNet 锁户型换风格；**无照片** → 文生图自由出软装齐全的效果图
  - 未装依赖/无 GPU/关闭时抛 SDUnavailable，接口返回 503
- **按需生成**（用户选择）：新接口 `POST /api/design/render`，方案详情页「生成效果图」按钮触发，不在生成方案时自动跑
- **风格 prompt**：中文风格/空间名 → 英文 prompt 映射（`render.py`），SD 对英文响应更好
- **落地保存**：效果图存 `uploads/`，`rendered_images` 表记录，经 `/uploads` 静态路由 + vite proxy 展示
- **前端**：新增 `EffectImage.tsx` 组件（占位→loading 打字点+轮播文案→图片+「换一张」/「基于你的户型」徽章），替换详情页原占位块

### 环境要点（避坑记录）

- RTX 50 系（Blackwell/sm_120）需 **cu128 版 PyTorch**——用户机器已装好（torch 2.11.0+cu128）
- 新版 huggingface_hub 的 Xet 协议会绕过 Clash 代理导致下载失败 → `HF_HUB_DISABLE_XET=1` 走代理直连官方源；hf-mirror 只代理 GET 不代理元数据 HEAD，用不了
- 模型缓存在 `D:/hf_cache`（config 的 `hf_home`）
- `xformers` 未装（sm_120 无预编译包），用 PyTorch 原生 SDPA

### 验证

- 独立脚本：文生图 → MLSD → ControlNet 重绘，三图证明「锁结构换风格」成立
- 接口直测：ControlNet 路径（真实房间图）生成的效果图保留窗/墙/地板结构，换成奶油暖调
- 浏览器：前端 fetch → 后端出图 → /uploads 代理 → `<img>` 加载 768×512 成功

### 下一步建议

1. 效果图 prompt 精修（引入方案的色板/材质/家具进 prompt，让出图更贴合方案文字）
2. img2img 强度调参（ControlNet 当前偏保守，可加 img2img 让原房间纹理参与）
3. 真实 PDF 导出（把效果图 + 方案 + 报价合成 PDF）
4. 用户体系 + 方案云端存储（打通「我的方案」到后端）

## 2026-07-09 (傍晚) 接入 Qwen3-VL 真实图片分析 + 端口调整

- 施工：Claude Code
- 当前状态：户型图/房间照片走真实视觉模型分析，并反哺方案生成；端口迁移到 8080/8081

### 已完成

- **端口调整**：前端 `localhost:8080`，后端 `localhost:8081`（vite proxy、CORS、launch.json、smoke_test、.env.example 已同步）
- **Qwen3-VL 视觉分析接入**（SiliconFlow，`app/services/llm_service.py::analyze_image`）：
  - 主力模型 `Qwen/Qwen3-VL-32B-Instruct`，配置读取 `.env` 的 `VL_API_KEY / VL_API_KEY_BASE_URL / VL_MODEL1 / VL_MODEL2`
  - 上传接口 `POST /api/upload/image` 传真实图片字节给 VL，返回结构化 JSON：image_kind / space_type / room_count / findings / suggestions
  - VL 识别到的空间信息回写 DB（uploaded_images.analysis_json），并覆盖按文件名的粗猜类型
  - 失败降级到占位结果（source=placeholder），前端再降级到本地 mock（source=mock）
- **图片分析反哺方案生成**：generate 时收集该任务下所有图片的 findings，作为 `image_analysis` 上下文一并喂给 DeepSeek 方案生成
- **前端展示升级**（AnalysisResult.tsx）：新增「Qwen3-VL 视觉分析」徽章、空间类型/房间数标签、独立的「装修建议」区块
- **方案生成健壮性**：新增 `_normalize_plans`——过滤 LLM 偶发的残缺方案、截取前 3 套、统一 id 与字段兜底（解决实测中 LLM 返回 5 套含 2 套残缺的问题）

### 验证

- 直接调 VL endpoint：准确识别测试户型图（客厅卧室相邻、厨卫并排、无独立餐厅、L型布局、缺玄关）
- 浏览器端到端：canvas 画户型图 → 上传 → 3 秒返回真实 VL 分析 → 页面渲染徽章+findings+建议，控制台零报错
- smoke_test.py：11 项全部 PASS

### 下一步建议

1. 效果图生成（第三方 API 或 SD + ControlNet，届时引入任务队列）
2. 真实 PDF 导出（weasyprint / reportlab）
3. 复杂户型可切换 VL_MODEL2（Thinking 版）做多房间动线深度推理
4. 「我的方案」与后端打通（用户体系 + 方案云端存储）


## 2026-07-09 (下午) MySQL 持久化 + DeepSeek LLM + 前后端联调完成

- 施工：Claude Code
- 当前状态：全链路真实化——前端页面 → FastAPI → MySQL 持久化 → DeepSeek 生成，端到端验证通过

### 已完成

- **MySQL 持久化**：本地 MySQL 8（`houseproject_db`），6 张表自动建表（design_tasks / uploaded_images / requirement_parse_results / design_results / chat_logs / users），替换掉全部内存存储
- **DeepSeek LLM 接入**（`app/services/llm_service.py`）：
  - 需求解析：自然语言 → 结构化 JSON（降级：原规则解析）
  - 对话确认：`POST /api/design/chat`，真实设计师人设对话（降级：前端本地规则回复）
  - 方案生成：一次产出 3 套完整方案，结构与前端 `DesignPlan` 对齐（降级：后端模板方案），耗时 24-41s
- **文件上传落地**：真实保存到 `backend/uploads/`，静态路由 `/uploads` 访问，DB 记录含空间识别结果（识别本身仍为占位，待接视觉模型）
- **前后端联调**：前端 `designApi.ts` 改为真实 fetch（vite proxy → 8010），后端不可用时自动降级本地 mock；修复 React StrictMode 双触发导致的重复 LLM 调用（in-flight 去重）
- **端口调整**：后端改用 **8010**（8000 被本机另一项目 Trust Contract AI Agent 占用）
- 重写 `smoke_test.py` 为针对运行中服务的端到端测试，11 项全部 PASS

### 遗留 / 已知问题

- LLM 方案生成偶发输出超长被截断 → 已通过收紧提示词字数缓解，仍有降级模板兜底
- 图片空间识别、效果图生成、PDF 导出仍为占位实现
- 生成接口为同步阻塞（~30s），并发量大时需改异步任务

### 下一步建议

1. 接入视觉模型（如 Qwen-VL）做真实户型图/照片分析
2. 效果图生成（第三方 API 或 SD + ControlNet，届时引入任务队列）
3. 真实 PDF 导出（weasyprint / reportlab）
4. 「我的方案」与后端打通（用户体系 + 方案云端存储）


## 2026-07-09 Web 前端基础版本完成

- 施工：Claude Code
- 需求来源：`AI_home_customization_frontend_prompt.md`（前端开发提示词）
- 当前状态：前端 10 个页面全部完成，构建通过，核心流程已在浏览器中验证

### 已完成

- 技术栈：React 18 + TypeScript + Vite 5 + Tailwind CSS v4 + framer-motion + zustand + react-router v6
- 目录：`frontend/`，启动方式 `cd frontend && npm install && npm run dev`（端口 5173）
- 页面（10 个）：首页、AI 定制表单（4 步向导）、户型图上传、AI 对话确认、方案结果、方案详情（6 个 Tab）、家具推荐（筛选 + 详情弹窗）、风格案例库、我的方案、登录注册
- 视觉体系：米白 / 原木 / 鼠尾草绿 / 陶土橙暖色调，Noto Serif SC 标题字体，自定义 Tailwind 主题 token
- 状态管理：zustand + localStorage 持久化（需求表单、保存的方案、收藏家具）
- Mock 数据：3 套完整设计方案、12 件家具、8 种风格案例、关键词规则 AI 对话回复
- API 层：`src/api/designApi.ts` 统一封装，vite proxy 已代理 `/api` → `localhost:8000`（FastAPI）

### 技术决策

- 未使用 shadcn/ui：自封装轻量组件（Button/Tag/EmptyState 等）以贴合定制视觉体系
- 已验证：TypeScript 零错误、生产构建通过、9 个路由页面移动端（375px）无横向溢出、控制台零报错

### 下一步建议

1. 前后端联调：将 `designApi.ts` 中的 mock 函数替换为真实 fetch 调用
2. 后端内存存储替换为 SQLAlchemy 持久化
3. 接入真实 LLM 需求解析与对话（对应前端 ChatPage）
4. 真实效果图生成与 PDF 导出



## 2026-06-04 初步 MVP 后端闭环

- 项目经理：Codex
- 施工 Worker：Gemini Backend MVP API Worker
- 需求来源：`AI家装项目初步项目计划书.md`
- 当前状态：第一阶段后端 MVP 闭环已初步实现并通过 smoke test

### 已完成

- 启用 FastAPI `/api` 路由。
- 实现图片上传模拟接口：`POST /api/upload/image`。
- 实现设计任务创建接口：`POST /api/design/tasks`。
- 实现结构化需求解析接口：`GET /api/design/tasks/{task_id}/requirement`。
- 实现需求确认接口：`POST /api/design/tasks/{task_id}/confirm-requirement`。
- 实现方案生成模拟接口：`POST /api/design/tasks/{task_id}/generate`。
- 实现任务状态查询接口：`GET /api/design/tasks/{task_id}`。
- 实现结果查询接口：`GET /api/design/tasks/{task_id}/result`。
- 实现导出接口：`POST /api/design/tasks/{task_id}/export-pdf`。
- 使用内存存储承载 MVP 数据流。
- 使用确定性规则模拟中文需求解析、报价计算、报告生成和效果图占位。
- 新增 smoke test 覆盖完整 API 流程。

### 验证结果

- `python list_routes.py`：确认计划书要求的核心 API 路由均已注册。
- `python smoke_test.py`：上传图片、创建任务、解析需求、确认需求、生成方案、查询结果、导出报告全流程通过。

### 当前限制

- 数据使用内存存储，服务重启后会丢失。
- 需求解析是规则模拟，不是真实 LLM。
- 效果图生成是占位 URL，不是真实 AI 绘图。
- PDF 导出当前是文本报告 artifact + mock `pdf_url`，不是正式 PDF 文件。
- 尚未实现前端 Web/H5 页面。
- 尚未接入数据库迁移、对象存储、异步任务队列和后台管理。

### 下一步建议

1. 构建 Web/H5 前端最小流程页面并接入现有 API。
2. 将内存存储替换为 SQLAlchemy 持久化模型。
3. 接入真实 LLM 需求解析，并保留当前规则解析作为 fallback。
4. 接入真实 PDF 生成能力。
5. 接入真实效果图生成服务或明确半自动占位流程。

# 数据库迁移

所有数据库结构变化必须通过 Alembic 迁移提交，禁止继续依赖手工 `ALTER TABLE`。

常用命令在 `backend` 目录执行：

```powershell
python -m alembic upgrade head
python -m alembic current
python -m alembic revision --autogenerate -m "中文变更说明"
```

`env.py` 默认读取项目根目录 `.env` 中的 `DATABASE_URL`，不会把连接信息写入仓库。

应用启动不再调用 `Base.metadata.create_all()`。一键启动脚本会先执行
`alembic upgrade head`；其他部署方式也必须先迁移，再启动 Uvicorn。

对于迁移接管前已经存在且结构匹配的数据库，只在首次接管时执行：

```powershell
python -m alembic stamp c0880aafa1bb
python -m alembic upgrade head
```

不要对空数据库执行 `stamp`，空数据库直接运行 `upgrade head`。

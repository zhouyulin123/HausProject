release: cd backend && python -m alembic upgrade head
web: cd backend && python -m app.run_api --port ${PORT:-8081}
worker-generation: cd backend && python -m app.workers.generation_worker
worker-effect-render: cd backend && python -m app.workers.effect_render_worker
worker-blender: cd backend && python -m app.workers.blender_worker

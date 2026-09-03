"""使用项目统一日志契约启动 FastAPI。"""

from __future__ import annotations

import argparse

import uvicorn

from app.core.logging_config import configure_logging


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须在 1 到 65535 之间")
    return port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="豪斯 FastAPI 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=_port, default=8081)
    args = parser.parse_args(argv)
    configure_logging()
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        access_log=False,
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


"""
Oasyce Logging Module - 结构化日志支持

提供统一的日志配置，支持文件输出、JSON 格式、日志级别控制。
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str,
    level: str = "INFO",
    log_file: Optional[str] = None,
    json_format: bool = False,
) -> logging.Logger:
    """
    配置并返回一个结构化 logger。

    Args:
        name: logger 名称（通常用 __name__）
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        log_file: 日志文件路径（None 表示只输出到控制台）
        json_format: 是否使用 JSON 格式（适合机器解析）

    Returns:
        配置好的 logging.Logger 实例
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # 防止重复添加 handler
    if logger.handlers:
        return logger

    # 创建 formatter
    if json_format:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件 handler (可选)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


class JsonFormatter(logging.Formatter):
    """JSON 格式 formatter - 适合机器解析和日志聚合系统。"""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime

        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加 exception 信息（如果有）
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


# 预配置的 logger 实例
def get_logger(name: str = "oasyce") -> logging.Logger:
    """快速获取一个默认配置的 logger。"""
    import os

    log_level = os.getenv("OASYCE_LOG_LEVEL", "INFO")
    log_file = os.getenv("OASYCE_LOG_FILE")  # 例如：~/.oasyce/oasyce.log
    return setup_logger(name, level=log_level, log_file=log_file)

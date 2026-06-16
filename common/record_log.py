"""
模块 3：日志系统

基于 Python 内建 logging 模块，支持：
1. 双通道输出 —— 控制台（实时看）+ 文件（持久化）
2. 分级过滤 —— DEBUG/INFO/WARNING/ERROR，生产环境调高级别减少噪音
3. 自动滚动 —— 文件按大小切割，避免单个日志文件无限膨胀
4. 格式化 —— 每条日志带时间戳、级别、文件名、行号
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from conf.setting import LOG_LEVEL, FILE_PATH


def get_logger(name=None):
    """
    获取一个配置好的 logger。

    设计要点：
    - name 用 __name__ 传入，日志里能看到来源模块
    - 控制台和文件分别设置级别，互不干扰
    """
    logger = logging.getLogger(name)    # 创建 logger，传入__name__
    logger.setLevel(logging.DEBUG)  # logger 自身设最低，由 handler 分别控制

    # 避免重复添加 handler（多次调用 get_logger 不会重复打印）
    if logger.handlers:
        return logger

    # 共用的日志格式
    fmt = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # ① 控制台 handler
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, LOG_LEVEL))
    console.setFormatter(fmt)   #给控制台设置格式
    logger.addHandler(console)  #把控制台处理器添加到 logger

    # ② 文件 handler（带滚动）
    log_dir = FILE_PATH['LOG']
    os.makedirs(log_dir, exist_ok=True) # 创建目录（如果不存在）
    log_file = os.path.join(log_dir, 'test.log')

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB 一个文件
        backupCount=5,              # 最多保留 5 个旧文件
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)  # 文件记录全部级别，便于排查
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger
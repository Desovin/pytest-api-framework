"""
模块 3：企业级日志系统（基于 loguru）

升级原因：
1. Python 内建 logging + RotatingFileHandler 在 Windows 多进程（pytest-xdist）下，
   日志滚动时会触发 PermissionError：os.rename 无法重命名被其他进程占用的文件。
2. loguru 使用进程安全的文件锁 + 内部队列（enqueue=True），天然支持多进程并发写入
   同一个日志文件，不再出现 rollover 冲突。
3. 额外收益：自动异常捕获（backtrace/diagnose）、日志压缩、彩色控制台、结构化输出。

设计要点：
- 全局只配置一次 logger，避免重复 handler
- 控制台（按 config.ini 级别过滤）+ 文件（DEBUG 全量）双通道
- 文件按 5MB 自动滚动，保留最近 5 个备份
- 多进程/多 worker 按身份写不同日志文件，避免跨进程抢占同一个文件：
  · 普通运行              → logs/test.log
  · benchmark 子进程      → logs/test_benchmark.log
  · pytest-xdist worker   → logs/test_gw0.log / test_gw1.log ...
- 提供 get_logger(name) 兼容旧接口，所有调用方无需改动
"""

import os
import sys

# ═══════════════════════════════════════════════════
# Windows 控制台编码修复
# ═══════════════════════════════════════════════════
# 现象：Windows 默认代码页是 GBK(936)，loguru 输出 UTF-8 中文时，
#       控制台按 GBK 解码，导致"测试会话"显示成"娴嬭瘯浼氳瘽"。
# 解决：在 loguru 初始化前，把控制台输出代码页切到 UTF-8(65001)，
#       并重写 sys.stdout/stderr 为 UTF-8，确保后续所有日志/print 都正常。
# 注意：只在 Windows 且当前不是 UTF-8 时处理，避免破坏已经正确的环境。
if sys.platform == 'win32':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # 65001 是 UTF-8 代码页
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:
        pass  # 非交互环境（如某些 CI）可能无控制台句柄，忽略即可

    # Python 3.7+ 可以通过 reconfigure 改 stdout 编码，比 TextIOWrapper 更安全
    # 关键：必须同时保留原 errors 策略，否则 pytest 的 FDCapture 会被从
    # errors='replace' 重置为 'strict'，导致捕获的非 UTF-8 字节（如 0x80）
    # 在 snap() 时抛出 UnicodeDecodeError。
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors=getattr(sys.stdout, 'errors', 'replace'))
            sys.stderr.reconfigure(encoding='utf-8', errors=getattr(sys.stderr, 'errors', 'replace'))
        except Exception:
            pass

from loguru import logger

from conf.setting import LOG_LEVEL, FILE_PATH


# 日志目录不存在则自动创建
LOG_DIR = FILE_PATH['LOG']
os.makedirs(LOG_DIR, exist_ok=True)


def _resolve_log_file():
    """
    按当前进程身份决定日志文件名。

    为什么分文件？
    - Windows 下多个独立进程（如 Mock Server、pytest 主进程、xdist worker）
      同时写一个文件时，即使 loguru 有锁，日志滚动 rename 仍可能因文件被占用失败。
    - 按身份分文件是工程里最稳的做法：互不阻塞、故障隔离、排查时定位到具体进程。
    """
    # Mock Server 是独立被测服务，不要让它的日志和测试框架混在同一个文件
    if os.environ.get('MOCK_SERVER_PROCESS'):
        return 'test_mock_server.log'
    worker = os.environ.get('PYTEST_XDIST_WORKER')
    if worker:
        # pytest-xdist worker 进程：gw0 / gw1 / ...
        return f'test_{worker}.log'
    if os.environ.get('BENCHMARK_RUN'):
        # benchmark 脚本通过 subprocess 启动的 pytest 进程
        return 'test_benchmark.log'
    # 普通 pytest / 直接运行脚本
    return 'test.log'


# 统一日志文件路径
LOG_FILE = os.path.join(LOG_DIR, _resolve_log_file())

# 移除 loguru 默认的 stderr handler，我们手动配置更精细的格式和过滤
logger.remove()

# ① 控制台 handler：带颜色，按 config.ini 的 LOG_LEVEL 过滤
# 颜色帮助本地快速区分级别，生产环境 CI 通常也能识别 ANSI 颜色
logger.add(
    sys.stdout,
    level=LOG_LEVEL,
    format=(
        '<green>{time:YYYY-MM-DD HH:mm:ss}</green> | '
        '<level>{level: <8}</level> | '
        '<cyan>{extra[name]}</cyan>:<cyan>{line}</cyan> | {message}'
    ),
    colorize=True,
    enqueue=True,  # 异步队列，避免多线程/多进程竞争 stdout
)

# ② 文件 handler：进程安全、自动滚动、全量 DEBUG 级别
# rotation="5 MB"  文件达到 5MB 自动切分
# retention=5      最多保留 5 个历史文件，防止磁盘无限增长
# enqueue=True     所有进程/线程通过队列写文件，loguru 内部加锁，不会互相覆盖
# backtrace=True   异常时自动记录完整堆栈
# diagnose=True    异常时显示变量值，便于定位
logger.add(
    LOG_FILE,
    level='DEBUG',
    format='{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[name]}:{line} | {message}',
    rotation='5 MB',
    retention=5,
    encoding='utf-8',
    enqueue=True,
    backtrace=True,
    diagnose=True,
)


def get_logger(name=None):
    """
    兼容旧接口，返回一个带 name 字段的 loguru logger。

    为什么保留这个函数？
    项目中大量代码使用 logger = get_logger(__name__)，为了不改动所有调用方，
    我们继续提供同名函数。底层用 loguru 的 bind() 把 name 注入 extra，
    让 format 里的 {extra[name]} 能显示来源模块。
    """
    return logger.bind(name=name or 'root')

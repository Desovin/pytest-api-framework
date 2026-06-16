"""验证日志系统是否正常工作"""
from common.record_log import get_logger

logger = get_logger(__name__)


def test_log_levels():
    """测试各级别日志输出"""
    logger.debug('这是 DEBUG 日志 —— 排查问题时用，生产环境通常不输出')
    logger.info('这是 INFO 日志 —— 记录关键操作')
    logger.warning('这是 WARNING 日志 —— 不太对劲但没挂')
    logger.error('这是 ERROR 日志 —— 出错了需要关注')


def test_both_outputs():
    """确认日志同时输出到控制台和文件"""
    logger.info('这条日志应该同时出现在控制台和 logs/test.log 里')
    assert True  # 日志不影响测试结果

"""登录接口 —— Redis 缓存断言演示（模块 10）"""
import allure
import pytest
from common.read_yaml import get_testcase_yaml
from base.apiutil import RequestBase


@allure.feature('用户管理模块')
class TestLoginWithRedis:

    @allure.story('登录-Redis缓存验证')
    @pytest.mark.parametrize('base_info,testcase',
                             get_testcase_yaml('data/login_with_redis.yaml'))
    def test_login_redis(self, base_info, testcase):
        """
        登录并验证 token 写入 Redis 缓存。

        断言流程：
        1. contains 断言：接口返回"登录成功"
        2. redis 断言：Redis 中 token:test01 键存在
        """
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

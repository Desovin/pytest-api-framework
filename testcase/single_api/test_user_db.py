"""用户管理 —— 单接口测试 + 数据库断言（模块 10）"""
import allure
import pytest
from common.read_yaml import get_testcase_yaml
from base.apiutil import RequestBase


@allure.feature('用户管理模块')
class TestUserWithDB:

    @allure.story('新增用户-含数据库验证')
    # 数据库写操作不能并发，否则可能出现主键冲突、脏数据
    @pytest.mark.serial
    @pytest.mark.parametrize('base_info,testcase',
                             get_testcase_yaml('data/add_user_with_db.yaml'))
    def test_add_user_with_db(self, base_info, testcase):
        """
        新增用户并验证数据落库。

        断言流程：
        1. contains 断言：接口返回"新增成功"
        2. db 断言：查 MySQL 确认 test_db_user 记录存在
        """
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

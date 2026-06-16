"""
用户管理模块 —— 单接口测试（单接口测试,每个接口独立验证）

对标 Test-Automation-Framework 的 testcase/Single interface/test_debug_api.py

重构前（test_data_driven.py）：每个测试函数 50+ 行，URL 拼接、token 处理、
  参数替换、断言全部混在一起
重构后：3 行核心代码，所有"怎么测"封装在 RequestBase.specification_yaml() 里
"""

import allure
import pytest
from common.read_yaml import get_testcase_yaml
from base.apiutil import RequestBase


@allure.feature('用户管理模块')
class TestUserManager:

    @allure.story('新增用户') # story 是一个独立的功能点，可测试的业务场景
    # 新增用户会写数据库/写 Mock Server 内存，并发会导致脏数据或唯一冲突，标记为串行
    @pytest.mark.serial
    @pytest.mark.parametrize('base_info,testcase',
                             get_testcase_yaml('data/add_user.yaml'))
    def test_add_user(self, base_info, testcase):
        """新增用户 —— 正向 + 反向共 4 个用例，数据全在 YAML 里"""
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

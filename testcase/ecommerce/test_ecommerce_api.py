"""
电商单接口测试类。

设计说明：
- 按 (baseInfo, testCase) 独立参数化，每个 YAML 用例都是一条 pytest 测试。
- place_order.yaml 中提取的 orderNumber 会被 order_pay.yaml / check_status.yaml 使用。
"""

import os
import allure
import pytest
from common.read_yaml import get_testcase_yaml
from base.apiutil import RequestBase

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_ECOMMERCE_DIR = os.path.join(_PROJECT_ROOT, 'data', 'ecommerce')
_ECOMMERCE_CASES = []
for yaml_name in sorted(os.listdir(_ECOMMERCE_DIR)):
    if not yaml_name.endswith('.yaml'):
        continue
    yaml_path = os.path.join('data', 'ecommerce', yaml_name)
    for base_info, testcase in get_testcase_yaml(yaml_path):
        _ECOMMERCE_CASES.append(
            pytest.param(
                base_info,
                testcase,
                id=f'{yaml_name}::{testcase["case_name"]}'
            )
        )


@allure.feature('电商模块')
@pytest.mark.serial  # place_order 提取的 orderNumber 需被 order_pay/check_status 按顺序读取
class TestEcommerceAPI:

    @allure.story('电商单接口')
    @pytest.mark.parametrize('base_info,testcase', _ECOMMERCE_CASES)
    def test_ecommerce_api(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

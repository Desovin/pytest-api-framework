"""
物流调度单接口测试类。

设计说明：
- 按 (baseInfo, testCase) 独立参数化，每个 YAML 用例都是一条 pytest 测试。
- 这样 pytest 收集时能看到 50+ 条物流用例，方便定位失败和统计数量。
- 用例间通过 extract.yaml 传递数据；每个 YAML 文件使用独立的 key，避免状态串扰。
"""

import os
import allure
import pytest
from common.read_yaml import get_testcase_yaml
from base.apiutil import RequestBase

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_LOGISTICS_DIR = os.path.join(_PROJECT_ROOT, 'data', 'logistics')
_LOGISTICS_CASES = []
for yaml_name in sorted(os.listdir(_LOGISTICS_DIR)):
    if not yaml_name.endswith('.yaml'):
        continue
    yaml_path = os.path.join('data', 'logistics', yaml_name)
    for base_info, testcase in get_testcase_yaml(yaml_path):
        _LOGISTICS_CASES.append(
            pytest.param(
                base_info,
                testcase,
                id=f'{yaml_name}::{testcase["case_name"]}'
            )
        )


@allure.feature('物流调度模块')
@pytest.mark.serial  # 共享 mock_data/logistics.json，串行避免文件写冲突
class TestLogistics:

    @allure.story('物流单接口')
    @pytest.mark.parametrize('base_info,testcase', _LOGISTICS_CASES)
    def test_logistics_api(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

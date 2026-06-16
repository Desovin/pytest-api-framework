"""
模块 4：YAML 数据读取

为什么要用 YAML 而不用 JSON？
1. YAML 支持注释，JSON 不支持 —— 测试数据需要解释为什么这样设计
2. YAML 比 JSON 更简洁（不用引号、不用大括号）
3. YAML 比 Excel 更适合版本管理（git diff 能看清楚改了什么）
"""

import yaml
import os


def read_yaml(file_path):
    """
    读取单个 YAML 文件，返回 Python 对象（通常为 list 或 dict）。

    使用 safe_load 而非 load：防止 YAML 注入执行任意 Python 代码
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        # 解析yaml文件，转换为Python对象
        return yaml.safe_load(f)  #safe_load不执行代码，防止yaml注入


def get_testcase_yaml(file_path):
    """
    读取测试用例 YAML，拆解为 baseInfo + testCase 元组列表，
    方便 pytest.mark.parametrize 直接使用。

    期望的 YAML 结构：
    - baseInfo:       # 接口公共信息（url, method, headers）
        api_name: 新增用户
        url: /dar/user/addUser
        method: POST
        header:
          Content-Type: application/x-www-form-urlencoded
    - testCase:       # 测试用例列表
        - case_name: 正常新增           # 断言时引用
          data:                          # 请求参数
            username: testadduser
          validation:                   # 断言规则
            - contains: { 'msg': '新增成功' }
    与参考项目一一对应：
    baseInfo的api_name：YAML中的 api_name 字段（接口名称）
    baseInfo的url：YAML中的 url 字段（接口路径）
    baseInfo的method：YAML中的 method 字段（请求方法）
    baseInfo的header：YAML中的 header 字段（请求头）
    testCase的case_name：YAML中的 case_name 字段（用例名称）
    testCase的data：YAML中的 data 字段（请求参数）
    testCase的validation：YAML中的 validation 字段（断言规则）

    :param file_path: YAML 文件路径
    :return: [(baseInfo, testcase), ...]
    """
    data = read_yaml(file_path)
    testcase_list = []
    for item in data:
        base_info = item['baseInfo']
        # 这里 tc 是一个 dict，包含 case_name、data、validation 等字段
        # tc就是testCase中的每个用例
        for tc in item['testCase']:
            testcase_list.append((base_info, tc))
    return testcase_list


# ── 模块 8：extract.yaml 读写（接口依赖数据中转）──

# extract.yaml 的默认路径，与项目根目录平级
EXTRACT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'extract.yaml'
)


def write_extract(data):
    """
    将数据写入 extract.yaml（追加模式）。

    为什么用追加（'a'）而非覆盖（'w'）？
    一个业务流程中可能有多个接口提取多个字段，追加模式保证
    每次提取都在文件末尾新增，不会覆盖前面接口存入的数据。

    :param data: dict，如 {'token': 'abc123', 'orderNumber': '12345'}
    """
    # 确保目录存在，不存在则创建
    os.makedirs(os.path.dirname(EXTRACT_PATH), exist_ok=True)
    with open(EXTRACT_PATH, 'a', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False) # 追加模式;不按字母顺序排序


def clear_extract():
    """清空 extract.yaml，每次测试会话开始前调用"""
    with open(EXTRACT_PATH, 'w', encoding='utf-8') as f:
        f.truncate(0) # 截断文件到0字符


def get_extract(key):
    """
    从 extract.yaml 读取指定 key 的值。

    用于 YAML 中的 ${get_extract_data(token)} 占位符替换。
    模块 8 的 DebugTalk.get_extract_data() 会调用此函数。

    :param key: 要读取的键名，如 'token'、'orderNumber'
    :return: 值，未找到返回 None
    """
    if not os.path.exists(EXTRACT_PATH):
        return None
    with open(EXTRACT_PATH, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    if data is None:
        return None
    return data.get(key)


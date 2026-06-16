"""验证 SendRequest + 配置管理是否正常工作"""
from common.send_request import SendRequest
from conf.setting import API_HOST, LOGIN_CONFIG


def test_get_index():
    client = SendRequest(base_url=API_HOST)
    resp = client.get("/index")

    assert resp is not None, "请求失败，返回了 None"
    assert resp["status_code"] == 200, f"状态码应为 200，实际 {resp['status_code']}"
    assert resp["json"]["msg"] == "成功访问首页"
    print(f"通过！响应时间: {resp['elapsed']:.3f}s")


def test_post_login():
    """验证 POST 登录请求，账号密码从 config.ini 读取"""
    client = SendRequest(base_url=API_HOST)
    resp = client.post(
        "/dar/user/login",
        data={
            "user_name": LOGIN_CONFIG['user_name'],
            "passwd": LOGIN_CONFIG['password']
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    assert resp is not None, "请求失败，返回了 None"
    assert resp["status_code"] == 200, f"状态码应为 200，实际 {resp['status_code']}"
    assert resp["json"]["msg"] == "登录成功"
    print(f"通过！响应时间: {resp['elapsed']:.3f}s")


def test_base_url_from_config():
    """验证配置读取正确"""
    assert API_HOST == "http://127.0.0.1:8787", f"API_HOST 配置错误: {API_HOST}"

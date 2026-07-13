"""
模块 1：请求封装

对 requests 库的二次封装，核心目的：
1. 统一 base_url —— 环境切换只改一处
2. 统一超时时间 —— 避免某个请求永久挂起
3. 统一请求头 —— 减少重复代码
4. Session 复用 —— 自动管理 Cookie，连接池复用，提升性能
5. 统一响应格式 —— 方便断言引擎统一处理
6. 401 自动刷新 token —— 应对 token 中途过期场景（企业级常见需求）
"""

import requests
from json import JSONDecodeError
from common.record_log import get_logger


class SendRequest:
    """统一接口请求类"""

    def __init__(
        self,
        base_url=None,
        timeout=60,
        headers=None,
        # 在编排层，token_refresh_callback = DebugTalk.get_token
        token_refresh_callback=None,
        auth_header_key='token',
        auth_param_key='token'
    ):
        """
        :param token_refresh_callback: 401/403 时调用的刷新 token 回调，
                                       签名为 callback(refresh=True) -> str
        :param auth_header_key: token 在 header 中的字段名
        :param auth_param_key: token 在请求参数（data/json/params）中的字段名
        """
        self.base_url = base_url
        self.timeout = timeout
        # headers or {} 处理 None 的惯用写法：外部不传则默认空字典
        self.headers = headers or {}
        # Session 复用 TCP 连接和 Cookie，比每次 request.get() 新建连接高效
        self.session = requests.Session()
        # logger 用模块名，日志里能看出来自 send_request
        self.logger = get_logger(__name__)

        self.token_refresh_callback = token_refresh_callback
        self.auth_header_key = auth_header_key
        self.auth_param_key = auth_param_key
        # 防止刷新 token 时递归触发 401 导致死循环
        self._refreshing = False

    def _send(self, method, path, **kwargs):
        url = self.base_url + path if self.base_url else path

        # 合并 headers：默认 headers 打底，本次请求 headers 覆盖同名 key
        req_headers = {**self.headers, **kwargs.pop('headers', {})}

        if 'timeout' not in kwargs:
            kwargs['timeout'] = self.timeout

        # 保存原始请求参数，用于 401 后重试时更新 token
        original_kwargs = kwargs.copy()

        # 请求前记一条 INFO 日志
        # info方法：记录一条INFO日志（正常运行的关键信息）
        self.logger.info('{} {}', method, url)

        try:
            resp = self.session.request(method, url, headers=req_headers, **kwargs)

            # 401/403 自动刷新 token 并重试一次
            if resp.status_code in (401, 403) and self.token_refresh_callback and not self._refreshing:
                self._refreshing = True
                try:
                    new_token = self.token_refresh_callback(refresh=True)
                    if new_token:
                        self.logger.warning('收到 %d，自动刷新 token 并重试', resp.status_code)
                        # 更新 header 中的 token
                        if self.auth_header_key in req_headers:
                            req_headers[self.auth_header_key] = new_token
                        # 更新 data/json/params 中的 token
                        for param_type in ['data', 'json', 'params']:
                            params = original_kwargs.get(param_type)
                            if isinstance(params, dict) and self.auth_param_key in params:
                                params[self.auth_param_key] = new_token
                        resp = self.session.request(
                            method, url, headers=req_headers, **original_kwargs
                        )
                finally:
                    self._refreshing = False

            # total_seconds() 返回完整秒数，microseconds 只取零头（<1秒的部分）
            try:
                body = resp.json()
            except JSONDecodeError:
                body = None

            # INFO 记录成功响应（DEBUG 级别才记录完整响应体，避免日志爆炸）
            self.logger.info('{} {} → {}, {:.3f}s', method, url, resp.status_code, resp.elapsed.total_seconds())
            self.logger.debug('响应体: {}', resp.text[:200])  # 只截前 200 字符

            return {
                'status_code': resp.status_code,
                'json': body,
                'text': resp.text,
                'elapsed': resp.elapsed.total_seconds()
            }
        except requests.RequestException as e:
            self.logger.error('{} {} 请求异常: {}', method, url, e)
            return None

    def get(self, path, **kwargs):
        """GET 请求"""
        return self._send('GET', path, **kwargs)

    def post(self, path, **kwargs):
        """POST 请求"""
        return self._send('POST', path, **kwargs)

    def put(self, path, **kwargs):
        """PUT 请求"""
        return self._send('PUT', path, **kwargs)

    def delete(self, path, **kwargs):
        """DELETE 请求"""
        return self._send('DELETE', path, **kwargs)

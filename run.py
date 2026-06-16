"""
一键运行入口（模块 11：支持并发 + 重试）。

执行流程：
1. 解析命令行参数（并发数、重试次数、目标目录）
2. pytest 发现并执行测试用例
   - 串行模式：直接跑全部用例
   - 并发模式：先并发跑非 serial 用例，再串行跑 serial 用例，合并结果
3. allure-pytest 插件自动收集结果到 ./report/temp
4. allure generate 生成静态 HTML 报告
5. Python HTTP 服务器启动，webbrowser 自动打开浏览器

使用示例：
    python run.py                          # 默认串行 + 失败重试 1 次
    python run.py -n auto                  # 自动并发（serial 用例最后串行跑）
    python run.py -n 4 --reruns 2          # 4 进程并发，失败重试 2 次
    python run.py testcase/single_api      # 只跑单接口用例
"""

import argparse     # 解析命令行参数
import subprocess
import os
import sys
import webbrowser
import socketserver
import pytest
from http.server import SimpleHTTPRequestHandler


def parse_args():
    """解析命令行参数，支持 pytest 的 -n 和 --reruns。"""
    parser = argparse.ArgumentParser(
        description='接口自动化测试一键运行',
        formatter_class=argparse.RawTextHelpFormatter # 保留原始换行格式
    )
    parser.add_argument(
        '-n', '--numprocesses',
        default=None,   # 并发进程数，默认串行(不启用并发)
        help='pytest-xdist 并发进程数，如 auto / 4'
    )
    parser.add_argument(
        '--reruns',
        default=None,
        help='失败重试次数，默认读取 pytest.ini'
    )
    parser.add_argument(
        'target',
        nargs='?',  # number of arguments , ? 表示参数可省略
        default='./testcase',
        help='测试目录或文件，默认 ./testcase'
    )
    return parser.parse_args()


def build_base_args(args):
    """组装基础 pytest 参数（目录 + 并发/重试）。"""
    pytest_args = [args.target]

    if args.numprocesses:
        pytest_args.extend(['-n', args.numprocesses])

    if args.reruns is not None:
        pytest_args.extend(['--reruns', args.reruns])

    return pytest_args


def run_tests(args):
    """
    执行测试。

    并发模式下分两步：
    1. 先并发跑非 serial 用例（pytest.ini 中的 --clean-alluredir 会清空历史数据）
    2. 再串行跑 serial 用例（覆盖 addopts 去掉 --clean-alluredir，避免清掉第一步结果）

    这样保证所有用例都执行，且 Allure 报告合并展示。
    """
    base_args = build_base_args(args)

    if args.numprocesses:
        print('[run.py] 并发模式：先跑非 serial 用例，再跑 serial 用例')

        # 第一步：并发跑非 serial 用例
        # pytest.ini 中的 --clean-alluredir 会在这里生效，清空旧报告数据
        parallel_args = base_args + ['-m', 'not serial']
        print(f'[run.py] 第一步 pytest 参数: {parallel_args}')
        code1 = pytest.main(parallel_args)

        # 第二步：串行跑 serial 用例
        # 覆盖 addopts 去掉 --clean-alluredir，但保留 --alluredir，让结果追加到 report/temp
        # 保留 --reruns 1 -v，和原配置行为一致
        serial_addopts = '--reruns 1 -v --alluredir=./report/temp'
        if args.reruns is not None:
            serial_addopts = f'-v --alluredir=./report/temp --reruns {args.reruns}'
        serial_args = [args.target, '-m', 'serial', '-o', f'addopts={serial_addopts}']
        print(f'[run.py] 第二步 pytest 参数: {serial_args}')
        code2 = pytest.main(serial_args)

        # 只要有一步失败，整体就返回失败
        return code1 or code2
    else:
        # 串行模式：直接跑全部，pytest.ini 自动处理 --clean-alluredir 和 --reruns
        print(f'[run.py] pytest 参数: {base_args}')
        return pytest.main(base_args)


if __name__ == '__main__':
    args = parse_args()

    # ① 跑测试
    # 返回值：0 表示所有用例通过，非 0 表示有用例失败
    exit_code = run_tests(args)

    # ② 生成 Allure 报告
    subprocess.run('allure generate ./report/temp -o ./report/allureReport --clean', shell=True)

    # ③ 启动 HTTP 服务器（Allure 报告必须通过 HTTP 访问，file:// 有 CORS 限制）
    report_dir = os.path.abspath('./report/allureReport')
    if not os.path.isfile(os.path.join(report_dir, 'index.html')):
        print('[run.py] 报告生成失败！请检查 allure 是否已安装（scoop install allure）')
        sys.exit(1)

    original_dir = os.getcwd()  # current working directory
    # 切换到报告目录 确保 HTTP 服务器只提供报告目录下的文件
    os.chdir(report_dir)    # change directory to report_dir

    try:
        server = socketserver.TCPServer(('127.0.0.1', 19200), SimpleHTTPRequestHandler)
    except OSError:
        # 端口被占用时自动分配
        server = socketserver.TCPServer(('127.0.0.1', 0), SimpleHTTPRequestHandler)

    # server.server_address：返回一个元组 (host, port)
    url = f'http://127.0.0.1:{server.server_address[1]}/index.html'

    print('\n' + '=' * 60)
    print(f'  Allure 报告: {url}')
    print('  按 Ctrl+C 停止服务')
    print('=' * 60 + '\n')

    webbrowser.open(url)

    try:
        server.serve_forever()  # 启动 HTTP 服务器，持续运行直到被停止，持续监听和处理客户端请求
    except KeyboardInterrupt:
        print('\n报告服务已停止')
        server.server_close()
    finally:
        os.chdir(original_dir)  # 换回原始目录

    # 测试失败时 run.py 也应该返回非 0 退出码，方便 CI 判断
    sys.exit(exit_code)

"""
并发执行 benchmark：串行 vs pytest-xdist。

设计说明：
- 用 subprocess 启动 pytest，避免当前进程内的缓存/fixture 状态影响测量。
- time.perf_counter() 记录 wall-clock 耗时。
- 使用 testcase/benchmark/test_concurrent_reads.py 作为负载：
  该文件只包含只读接口用例，不共享可变状态，可被 xdist 安全并行。
- 分别用 1/2/4/auto 个 worker 跑 xdist，取最优结果与串行对比。
- 输出 headline："优化至 X 秒"，并把详细结果写入 benchmark/report.json。

使用方式：
    python benchmark/concurrency_benchmark.py
"""

import json
import os
import subprocess
import sys
import time


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCHMARK_DIR = os.path.join(PROJECT_ROOT, 'benchmark')
REPORT_PATH = os.path.join(BENCHMARK_DIR, 'report.json')
BENCHMARK_TARGET = './testcase/benchmark/test_concurrent_reads.py'


def run_pytest(extra_args):
    """
    执行 pytest 并返回 (耗时秒数, returncode, stdout, stderr)。

    为什么不用 text=True：
    - subprocess 内部 reader 线程实时解码时，errors='replace' 在 Python 3.12/Windows
      某些场景下不生效，遇到 GBK 字节（如 0xb4/0xc1）会直接抛 UnicodeDecodeError。
    - 先拿原始 bytes，返回主线程后再 decode，errors='replace' 一定生效。

    为什么传 BENCHMARK_RUN=1 环境变量？
    - 让子进程里的 loguru 写独立的 logs/test_benchmark.log，
      避免和父进程/其他 pytest 进程抢占 logs/test.log，防止 Windows 下日志滚动 rename 失败。
    """
    cmd = [sys.executable, '-m', 'pytest', BENCHMARK_TARGET, '-q', '--no-header'] + extra_args
    env = os.environ.copy()
    env['BENCHMARK_RUN'] = '1'

    start = time.perf_counter()
    result = subprocess.run(
        cmd, cwd=PROJECT_ROOT, capture_output=True, env=env  # 原始 bytes，避开内部 reader 线程解码
    )
    elapsed = time.perf_counter() - start

    stdout = result.stdout.decode('utf-8', errors='replace')
    stderr = result.stderr.decode('utf-8', errors='replace')

    return elapsed, result.returncode, stdout, stderr


def _dump_fail_log(label, code, out, err):
    """
    失败输出不直接 print，而是追加写入 benchmark/benchmark.log。

    为什么：Windows 控制台默认 GBK 编码，无法显示 errors='replace' 产生的 �（�），
    直接 print 会触发第二次 UnicodeEncodeError。写入 UTF-8 文件即可绕过控制台编码限制。
    """
    if code == 0:
        return
    log_path = os.path.join(BENCHMARK_DIR, 'benchmark.log')
    with open(log_path, 'a', encoding='utf-8', errors='replace') as f:
        f.write(f'\n\n===== [{label}] exit_code={code} =====\n')
        f.write('----- stderr -----\n')
        f.write(err)
        f.write('\n----- stdout -----\n')
        f.write(out)
    print(f'      失败详情已写入：{log_path}')


def main():
    os.makedirs(BENCHMARK_DIR, exist_ok=True)

    print('=' * 60)
    print('并发 benchmark：串行 vs pytest-xdist')
    print(f'目标用例：{BENCHMARK_TARGET}')
    print('=' * 60)

    # 1. 串行基准
    print('\n[1/5] 串行执行...')
    serial_time, serial_code, serial_out, serial_err = run_pytest([])
    print(f'      耗时: {serial_time:.2f}s  exit_code: {serial_code}')
    _dump_fail_log('1/5 串行', serial_code, serial_out, serial_err)

    # 2. xdist 多 worker 对比
    worker_results = {}
    for workers in ['2', '4', 'auto']:
        print(f'\n[{list(["2", "4", "auto"]).index(workers) + 2}/5] xdist {workers} workers...')
        elapsed, code, out, err = run_pytest(['-n', workers])
        worker_results[workers] = {
            'seconds': round(elapsed, 2),
            'exit_code': code,
        }
        print(f'      耗时: {elapsed:.2f}s  exit_code: {code}')
        _dump_fail_log(f'xdist {workers}', code, out, err)

    # 取最优 xdist 结果
    best_workers = min(
        worker_results.items(),
        key=lambda item: item[1]['seconds'] if item[1]['exit_code'] == 0 else float('inf')
    )
    best_label, best_result = best_workers
    best_time = best_result['seconds']
    speedup = serial_time / best_time if best_time > 0 else 0

    # 3. 全量用例串行参考（仅作对比，不跑 xdist，因为大量用例带 serial 标记）
    print('\n[5/5] 全量用例串行参考...')
    full_cmd = [sys.executable, '-m', 'pytest', './testcase', '-q', '--no-header']
    full_env = os.environ.copy()
    full_env['BENCHMARK_RUN'] = '1'
    start = time.perf_counter()
    try:
        full_result = subprocess.run(
            full_cmd, cwd=PROJECT_ROOT, capture_output=True, env=full_env  # 同样改用 bytes 读取
        )
        full_serial_time = time.perf_counter() - start
        full_serial_code = full_result.returncode
        full_stdout = full_result.stdout.decode('utf-8', errors='replace')
        full_stderr = full_result.stderr.decode('utf-8', errors='replace')
        if full_serial_code != 0:
            _dump_fail_log('5/5 全量串行', full_serial_code, full_stdout, full_stderr)
    except Exception as e:
        full_serial_time = time.perf_counter() - start
        full_serial_code = -1
        print(f'      执行异常: {e}')
    print(f'      耗时: {full_serial_time:.2f}s  exit_code: {full_serial_code}')

    report = {
        'benchmark_target': BENCHMARK_TARGET,
        'serial_seconds': round(serial_time, 2),
        'serial_exit_code': serial_code,
        'xdist_workers': worker_results,
        'best_xdist': {
            'workers': best_label,
            'seconds': best_time,
            'speedup': round(speedup, 2),
        },
        'full_suite_serial_seconds': round(full_serial_time, 2),
        'full_suite_serial_exit_code': full_serial_code,
    }

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print('\n' + '=' * 60)
    print(f'Headline：并发用例从 {serial_time:.2f}s 优化至 {best_time:.2f}s（xdist -n {best_label}），加速 {speedup:.2f}x')
    print(f'报告已保存：{REPORT_PATH}')
    print('=' * 60)


if __name__ == '__main__':
    main()

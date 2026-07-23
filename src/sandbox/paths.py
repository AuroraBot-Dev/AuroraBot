"""沙箱路径与超时默认值，不依赖应用配置层。"""

from pathlib import Path

# 项目根目录（src/sandbox/paths.py → 上溯两级）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 沙箱数据目录
SANDBOX_DIR = PROJECT_ROOT / "data" / "sandbox"
# 临时脚本目录（每次执行创建独立子目录）
SANDBOX_TEMP_DIR = SANDBOX_DIR / "temp"
# 输出产物目录（stdout/stderr/文件）
SANDBOX_OUTPUT_DIR = SANDBOX_DIR / "output"
# 子进程执行超时（秒）
SANDBOX_EXEC_TIMEOUT = 30.0
# stdout/stderr 最大截断长度
SANDBOX_MAX_OUTPUT_SIZE = 50_000

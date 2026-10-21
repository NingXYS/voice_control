"""Linux exec 包装器：父进程消失时结束本子进程，无后台守护进程。"""
import ctypes
import os
import signal
import sys


def main():
    parent = int(sys.argv[1])
    command = sys.argv[2:]
    if not command:
        raise SystemExit("missing guarded command")
    if os.getppid() != parent:
        raise SystemExit(125)
    libc = ctypes.CDLL(None, use_errno=True)
    # 独立 exec 包装，避免多线程 Python 使用 preexec_fn 后死锁。
    if libc.prctl(1, int(signal.SIGKILL), 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_PDEATHSIG failed")
    # 覆盖父进程在检查与 prctl 之间退出的竞态。
    if os.getppid() != parent:
        raise SystemExit(125)
    os.execvpe(command[0], command, os.environ)


if __name__ == "__main__":
    main()

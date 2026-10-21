"""同一语音工程只允许一个语音运行时占用录音设备。"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path


@contextmanager
def voice_runtime_lock(directory: Path):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(directory / "voice.lock", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("已有语音进程运行，请先在原 UI 停止语音后再启动。") from None
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode("ascii"))
        yield
    finally:
        # 锁随 fd 关闭或进程死亡释放；锁文件保留，避免删除后出现双实例竞态。
        os.close(fd)

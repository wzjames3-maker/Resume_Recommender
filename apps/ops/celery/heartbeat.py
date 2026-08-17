import os
from pathlib import Path

from celery.signals import heartbeat_sent, worker_ready, worker_shutdown

# worker 心跳/就绪探针文件目录。默认 /opt/maxkb-app/tmp（生产部署路径），
# 本机开发无该目录写权限时可用 MAXKB_WORKER_TMP 环境变量覆盖。
WORKER_TMP_DIR = os.getenv("MAXKB_WORKER_TMP") or "/opt/maxkb-app/tmp"


def _probe_path(filename):
    directory = Path(WORKER_TMP_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename


@heartbeat_sent.connect
def heartbeat(sender, **kwargs):
    worker_name = sender.eventer.hostname.split('@')[0]
    _probe_path('worker_heartbeat_{}'.format(worker_name)).touch()


@worker_ready.connect
def worker_ready(sender, **kwargs):
    worker_name = sender.hostname.split('@')[0]
    _probe_path('worker_ready_{}'.format(worker_name)).touch()


@worker_shutdown.connect
def worker_shutdown(sender, **kwargs):
    worker_name = sender.hostname.split('@')[0]
    for signal in ['ready', 'heartbeat']:
        path = Path(WORKER_TMP_DIR) / 'worker_{}_{}'.format(signal, worker_name)
        path.unlink(missing_ok=True)

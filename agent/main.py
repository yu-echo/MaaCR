# -*- coding: utf-8 -*-
"""MaaCR Agent 入口。

由通用 UI（MFAAvalonia 等）按 interface.json 里的 `agent` 字段拉起：
    python ./agent/main.py <socket_id>
socket_id 由通用 UI 生成并作为最后一个参数传进来。

⚠️ 不要手动启动这个文件 —— 它需要通用 UI 给的 socket_id 才能与主进程通信。
   要调试 pipeline，用 VSCode 的 Maa Pipeline Support 插件，
   它会自动起 debug session 并插入 socket id。
"""

import os
import sys

from maa.agent.agent_server import AgentServer
from maa.toolkit import Toolkit

# 脚本目录要显式加进 sys.path：通用 UI 拉起时 CWD 是 interface.json 所在目录，
# 不一定是这里，直接 import 同目录模块会失败。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 导入即注册：各模块里的 @AgentServer.custom_* 装饰器在 import 时执行。
# 不 import 就等于没注册，pipeline 走到 Custom 节点会直接失败。
import cr_nodes  # noqa: E402,F401


def main():
    # 在 interface.json 所在目录（也就是 CWD）读写 config/maa_option.json，
    # 用于控制日志、save_draw、save_on_error 等调试选项。
    Toolkit.init_option("./")

    if len(sys.argv) < 2:
        print("Usage: python main.py <socket_id>")
        print("socket_id is provided by AgentIdentifier (the general UI).")
        sys.exit(1)

    socket_id = sys.argv[-1]
    print("[MaaCR] Agent 启动，socket_id=%s" % socket_id, flush=True)

    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()

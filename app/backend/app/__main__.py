"""包入口：``python -m app ai <命令>`` 取数，``python -m app export <命令>`` 导出视图。

ai：summary / weak / pending / recent / doubt / plan / snapshot；
默认输出 markdown，加 ``--json`` 输出机器可读，``--limit N`` 控制条数。
export：plan（节点状态列）/ wrongbook（错题本三表）/ all（两者）；
以 SQLite 为源重生成 markdown 视图，可反复执行（幂等）。
"""

from __future__ import annotations

import sys

from . import ai


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "export":
        from . import exporter

        return exporter.main(argv[1:])
    if argv and argv[0] == "ai":  # 兼容 `python -m app ai …` 写法
        argv = argv[1:]
    return ai.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

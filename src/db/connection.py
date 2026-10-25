"""数据库连接与事务边界：上层（service / api）唯一的数据库入口。

**为什么要有这一层**，而不是让每个 service 自己 ``sqlite3.connect()``：

1. **换库只改一处**：上层只 import 本模块暴露的 ``Connection`` / ``Row`` /
   ``IntegrityError``，不直接依赖 ``sqlite3``。将来迁移到 PostgreSQL 时，
   类型与异常差异收敛在本文件（service 的 SQL 仍要改，但类型与连接语义不用逐个文件动）。
2. **事务语义统一**：``transaction()`` 只在一个地方判定"这次要不要 commit / rollback / close"。
   此前 12 个 service 各自复制了一份 ``try/finally``，任何一处写错都只影响那一个文件。
3. **原子性**：一个函数里的多步写操作共用一个事务 —— 失败整体回滚，
   不会出现"登录码已标记使用、但用户没开出来"这类半成品状态。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from src.db.sqlite import get_connection

#: 连接类型。换库时只改这一行（例如换成 psycopg 的 Connection）。
Connection = sqlite3.Connection

#: 行类型：支持 ``row["email"]`` 按列名取值。
Row = sqlite3.Row

#: 异常别名。上层捕获的是语义而不是驱动实现：
#: 唯一约束冲突、SQL 语句错误、以及兜底的数据库基类异常。
Error = sqlite3.Error
DatabaseError = sqlite3.DatabaseError
IntegrityError = sqlite3.IntegrityError
OperationalError = sqlite3.OperationalError


@contextmanager
def transaction(conn: Connection | None = None) -> Iterator[Connection]:
    """以事务方式使用连接。

    - ``conn is None``：**新开连接并拥有这个事务** —— 正常结束 commit，异常 rollback，最后 close；
    - ``conn`` 非 None：**复用调用方的连接** —— 不 commit、不 close，
      事务边界由最外层持有者决定，这样 service 之间的嵌套调用仍然是一个事务。

    用法::

        with transaction(conn) as active:
            active.execute(...)
            other_service.do_something(conn=active)   # 不新开事务，跟着外层一起提交
    """
    owned = conn is None
    active: Connection = get_connection() if owned else conn
    try:
        yield active
    except Exception:
        if owned:
            active.rollback()
        raise
    else:
        if owned:
            active.commit()
    finally:
        if owned:
            active.close()

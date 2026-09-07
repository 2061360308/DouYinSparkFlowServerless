"""Write admission before reading a snapshot on SQLite's deferred transactions."""
from contextlib import asynccontextmanager
from tortoise.transactions import in_transaction


@asynccontextmanager
async def write_transaction():
    async with in_transaction() as connection:
        if connection.capabilities.dialect == 'sqlite':
            # SELECT FOR UPDATE is ignored on SQLite. Acquire the write lock
            # before any decision reads, avoiding a cross-process read/upgrade race.
            await connection.execute_query('UPDATE task_quota_policy SET id = id WHERE id = 1')
        yield connection

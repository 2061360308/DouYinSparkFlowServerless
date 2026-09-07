"""Child worker for isolated cross-process queue tests; no real dispatcher calls."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db.connection import open_persistent, close_persistent
from core.services import task_scheduling as scheduling


async def main():
    async def fake_dispatch(_):
        with open(sys.argv[2], 'a', encoding='utf-8') as record:
            record.write('dispatch\n')
        await asyncio.sleep(0.5)
    scheduling._dispatch = fake_dispatch
    await open_persistent()
    try:
        print(await scheduling.process_job(sys.argv[1]))
    finally:
        await close_persistent()


if __name__ == '__main__':
    asyncio.run(main())

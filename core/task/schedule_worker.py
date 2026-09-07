"""Durable schedule reconciler: python -m core.task.schedule_worker [--once]."""
import argparse
import asyncio
import logging
from core.db.connection import open_persistent, close_persistent
from core.services.task_scheduling import reconcile


async def run(once=False):
    await open_persistent()
    try:
        while True:
            try:
                await reconcile()
            except Exception as error:
                if once:
                    raise
                logging.warning('Schedule reconciliation failed (%s)', type(error).__name__)
            if once:
                break
            await asyncio.sleep(15)
    finally:
        await close_persistent()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    asyncio.run(run(parser.parse_args().once))

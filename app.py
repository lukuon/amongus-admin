import asyncio
import logging
import os
import sys
from typing import Awaitable, Callable

import dotenv
import uvicorn
from fastapi import FastAPI, Request, Response
from uvicorn.logging import DefaultFormatter

from discordbot import bot, bot_invitation_link


logger = logging.getLogger("amongus_admin")
app = FastAPI()


@app.middleware("http")
async def catch_all(_request: Request, _call_next: Callable[[Request], Awaitable[Response]]):
    return Response(status_code=302, headers={"Location": bot_invitation_link})


def _cancel_tasks(loop):
    task_retriever = asyncio.all_tasks
    tasks = {t for t in task_retriever(loop=loop) if not t.done()}

    if not tasks:
        return

    logger.info("Cleaning up after %d tasks.", len(tasks))
    for task in tasks:
        task.cancel()

    loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
    logger.info("All tasks finished cancelling.")

    for task in tasks:
        if task.cancelled():
            continue
        if task.exception() is not None:
            loop.call_exception_handler(
                {
                    "message": "Unhandled exception during Client.run shutdown.",
                    "exception": task.exception(),
                    "task": task,
                }
            )


def _cleanup_loop(loop):
    try:
        _cancel_tasks(loop)
        if sys.version_info >= (3, 6):
            loop.run_until_complete(loop.shutdown_asyncgens())
    finally:
        logger.info("Closing the event loop.")
        loop.close()


if __name__ == "__main__":
    dotenv.load_dotenv(".env")
    root_handler = logging.StreamHandler(sys.stderr)
    fmt = "%(levelprefix)s [%(name)s]\t%(message)s"
    root_handler.setFormatter(DefaultFormatter(fmt=fmt))
    # noinspection PyArgumentList
    logging.basicConfig(level=logging.DEBUG, handlers=[root_handler])

    main_loop = asyncio.get_event_loop()
    asyncio.set_event_loop(main_loop)
    bot.loop = main_loop

    async def bot_runner(*args, **kwargs):
        try:
            await bot.start(*args, **kwargs)
        finally:
            if not bot.is_closed():
                await bot.close()

    asyncio.ensure_future(bot_runner(os.environ["DISCORD_BOT_TOKEN"]))
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False, workers=1, loop="none", log_config=None)
    main_loop.run_until_complete(bot.close())
    _cleanup_loop(main_loop)

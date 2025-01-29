from datetime import datetime
from functools import wraps
import logging
import os
import re
import traceback
from typing import Optional

import yaml
from summarizer import Summarizer
from exceptions import *
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackContext, ConversationHandler


logger = logging.getLogger('bot')


# Pre-assign menu text
HELP_USAGE = "Натрави меня реплаем на сообщение, в котором есть ссылка на YouTube видео и напиши /short@imikdev_bot"
HELP_USAGE_CLARIFY = "Натрави меня реплаем на сообщение, в котором есть ссылка на YouTube видео. Напиши в одном реплае /clarify@imikdev_bot и добавь что нужно уточнить."

class AlwaysInWhitelist:
    def __eq__(self, _):
        return True


def setup_logger(log_level: Optional[str]='INFO', logfile: Optional[str]=None) -> None:
    """Logger setup to write into console and to the file (Optional)"""
    log_formatter = logging.Formatter('%(asctime)s %(name)s [%(levelname)s] %(message)s', datefmt='%d-%m-%Y %H:%M:%S')
    logger.setLevel(log_level)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)

    if logfile:
        fileHandler = logging.FileHandler("{0}_{1}".format(logfile, datetime.utcnow().strftime('%F_%T.%f')[:-3]))
        fileHandler.setLevel(log_level)
        fileHandler.setFormatter(log_formatter)
        logger.addHandler(fileHandler)

def auth(func):
    """Decorator to restrict access to whitelisted users."""
    @wraps(func)
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in id_whitelist:
            if update.message:
                await update.message.reply_text("Access denied. You are not authorized to use this bot.")
            elif update.callback_query:
                await update.callback_query.answer("Access denied. You are not authorized to use this bot.", show_alert=True)
            return ConversationHandler.END
        return await func(update, context, *args, **kwargs)
    return wrapper


async def process_request(update: Update, context: CallbackContext, clarify=None) -> None:
    if update.message.reply_to_message:
        message = update.message.reply_to_message.text
        logger.info(f'From {update.message.chat_id}: {update.message.from_user.name} received {message}')
        try:
            if clarify:
                clarify = re.sub(r"/clarify|@imikdev_bot", "", update.message.text)
            reply = summarizer.get_youtube_summary(chat_id=update.message.chat_id, text=message, clarify=clarify)
        except AlreadySeenException:
            logger.debug(f"Seen this url before {message}")
            reply = f"Была уже эта ссылка. Не ленись поскролить выше."
        except NotYoutubeUrlException:
            logger.debug(traceback.format_exc())                        
            logger.debug(f"Cannot find a YouTube url {message}")
            reply = f"Ссылки на YouTube видео нету."
            pass
        except NoCaptionsException:
            logger.debug(f"Canot get captions for {message}")
            reply = f"Не смог получить субтитры для видео."
        except TooExpensiveException as e:
            logger.debug(f"Too expensive {e}")
            reply = f"Братишка, чет дорого выходит {e}."
        except Exception as e:
            logger.warning(traceback.format_exc())                        
            logger.warning(e)      
            logger.warning(f"Failed to reply with a summary to {message}")
            reply = f"Что-то пошло не так {message}. Ошибка: {e}"
            pass
    else:
        reply = HELP_USAGE_CLARIFY if clarify else HELP_USAGE

    chunk_size = 3500
    chunks = [
        reply[i : i + chunk_size]
        for i in range(0, len(reply), chunk_size)
    ]

    for chunk in chunks:
        await context.bot.send_message(
            update.message.chat_id,
            reply_to_message_id=update.message.message_id,
            text=chunk,
            # To preserve the markdown, we attach entities (bold, italic...)
            entities=update.message.entities
        )

async def process_free_prompt(update: Update, context: CallbackContext) -> None:
    try:
        message = re.sub(r"/prompt|@imikdev_bot", "", update.message.text)
        reply_message = None
        if update.message.reply_to_message:
            reply_message = update.message.reply_to_message.text
        reply = summarizer.get_free_prompt_reply(chat_id=update.message.chat_id, text=message, reply_message=reply_message)
    except TooExpensiveException as e:
        logger.debug(f"Too expensive {e}")
        reply = f"Братишка, чет дорого выходит {e}."
    except Exception as e:
        logger.warning(traceback.format_exc())                        
        logger.warning(e)      
        logger.warning(f"Failed to reply with a summary to {message}")
        reply = f"Что-то пошло не так {message}. Ошибка: {e}"
        pass

    chunk_size = 3500
    chunks = [
        reply[i : i + chunk_size]
        for i in range(0, len(reply), chunk_size)
    ]

    for chunk in chunks:
        await context.bot.send_message(
            update.message.chat_id,
            reply_to_message_id=update.message.message_id,
            text=chunk,
            # To preserve the markdown, we attach entities (bold, italic...)
            entities=update.message.entities
        )

@auth
async def clarify(update: Update, context: CallbackContext) -> None:
    """This handler will exctract YouTube link from the replayed message and will apply custom prompt to it"""

    # Print to console
    logger.info(f'From {update.message.chat_id}: {update.message.from_user.name} wrote {update.message.text}')
    await process_request(update=update, context=context, clarify=True)

@auth
async def short(update: Update, context: CallbackContext) -> None:
    """This handler will exctract YouTube link from the replayed message and will apply summarize it"""

    # Print to console
    logger.info(f'From {update.message.chat_id}: {update.message.from_user.name} wrote {update.message.text}')
    await process_request(update=update, context=context)

@auth
async def prompt(update: Update, context: CallbackContext) -> None:
    """This handler will use the message as a general prompt"""
    
    # Print to console
    logger.info(f'From {update.message.chat_id}: {update.message.from_user.name} wrote {update.message.text}')
    await process_free_prompt(update=update, context=context)

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=str, default=None, help="Path to config.yaml file.")
    args = parser.parse_args()

    config_file = args.config
    with open(config_file, "r") as file:
        config = yaml.safe_load(file)

    log_level = config.get('log_level', 'INFO').upper()
    log_file = config.get('logfile', None)
    setup_logger(log_level, log_file)

    global id_whitelist
    id_whitelist = config.get('whitelist', [])
    if not id_whitelist:
        id_whitelist.append(AlwaysInWhitelist())

    global summarizer
    summarizer = Summarizer()

    api_token = os.environ.get('TELEGRAM_API_TOKEN', None)
    application = ApplicationBuilder().token(api_token).build()

    # Register commands
    application.add_handler(CommandHandler("short", short))
    application.add_handler(CommandHandler("clarify", clarify))
    application.add_handler(CommandHandler("prompt", prompt))

    # Start the Bot
    application.run_polling()


if __name__ == '__main__':
    main()

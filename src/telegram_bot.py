from datetime import datetime
from functools import wraps
import logging
import os
import re
import traceback
from typing import Optional

import yaml
from chat import Chat
from summarizer import Summarizer
from exceptions import *
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackContext, ConversationHandler, MessageHandler, filters


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
        chat_id = update.message.chat_id
        if user_id not in id_whitelist and chat_id not in id_whitelist:
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

async def process_system_prompt(update: Update, context: CallbackContext) -> None:
    message = update.message.text
    if "/system" in message:
        message = re.sub(r"/system|@imikdev_bot", "", message).strip()
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    free_chat.set_system_prompt(chat_id, user_id, message)

    await context.bot.send_message(
        chat_id,
        reply_to_message_id=update.message.message_id,
        text=f"Системный промпт установлен на {message}"
    )


async def process_free_chat(update: Update, context: CallbackContext) -> None:
    try:
        message = update.message.text
        if context.bot.username in message:
            message = re.sub(f"@{context.bot.username}", "", message).strip()
        if "/prompt" in message:
            message = re.sub(r"/prompt|@imikdev_bot", "", message).strip()

        chat_id = update.message.chat_id
        user_id = update.message.from_user.id
        id = update.message.message_id
        reply_id = update.message.reply_to_message.message_id if update.message.reply_to_message else None
        reply = free_chat.free_chat(message, chat_id=chat_id, user_id=user_id, message_id=id, reply_id=reply_id)
        content = reply["content"]
    except TooLongMessageException as e:
        logger.debug(f"Too long {e}")
        reply = f"Наш разговор получился слишком длинным. Давай начнем с чистого листа. {e}."
    except Exception as e:
        logger.warning(traceback.format_exc())                        
        logger.warning(e)      
        logger.warning(f"Failed to reply with a summary to {message}")
        reply = f"Что-то пошло не так {message}. Ошибка: {e}"
        pass

    chunk_size = 3500
    chunks = [
        content[i : i + chunk_size]
        for i in range(0, len(reply), chunk_size)
    ]

    for chunk in chunks:
        sent_message = await context.bot.send_message(
            update.message.chat_id,
            reply_to_message_id=update.message.message_id,
            text=chunk,
            # To preserve the markdown, we attach entities (bold, italic...)
            # entities=update.message.entities
        )
    free_chat.conversation[chat_id][sent_message.message_id] = {"request": reply, "reply_id": update.message.message_id}

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
async def system(update: Update, context: CallbackContext) -> None:
    """This handler will use the message to set a system prompt"""

    logger.info(f'From {update.message.chat_id}: {update.message.from_user.name} wrote {update.message.text}')
    await process_system_prompt(update=update, context=context)

@auth
async def prompt(update: Update, context: CallbackContext) -> None:
    """This handler will use the message as a general prompt"""

    logger.info(f'From {update.message.chat_id}: {update.message.from_user.name} wrote {update.message.text}')
    await process_free_chat(update=update, context=context)

@auth
async def handle_direct_message(update: Update, context: CallbackContext) -> None:
    """Process messages sent directly to the bot or mentioned in a group."""
    logger.info(f'From {update.message.chat_id}: {update.message.from_user.name} wrote {update.message.text}')
    await process_free_chat(update=update, context=context)

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
    
    base_url = config.get('base_url', "https://api.deepseek.com")

    proxies = config.get('youtube_api_proxies', None)
    if not proxies:
        proxies = {}
        if os.environ.get('HTTP_PROXY', None):
            proxies['http'] = os.environ['HTTP_PROXY']
        if os.environ.get('HTTPS_PROXY', None):
            proxies['https'] = os.environ['HTTPS_PROXY']

    global summarizer
    summarizer = Summarizer(base_url=base_url, youtube_api_proxies=proxies)
    
    global free_chat
    free_chat = Chat(base_url=base_url)

    api_token = os.environ.get('TELEGRAM_API_TOKEN', None)
    application = ApplicationBuilder().token(api_token).build()

    # Initialize the bot asynchronously
    bot_username = "imikdev_bot"

    # Register commands
    application.add_handler(CommandHandler("short", short))
    application.add_handler(CommandHandler("clarify", clarify))
    application.add_handler(CommandHandler("prompt", prompt))
    application.add_handler(CommandHandler("system", system))

    # Register direct message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct_message))

    # Start the Bot
    application.run_polling()


if __name__ == '__main__':
    main()

import logging
import time

from functools import partial
from enum import Enum
from textwrap import dedent

import redis

from environs import Env
from telegram import Bot, ReplyKeyboardMarkup, Update
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    ConversationHandler,
    Filters,
    MessageHandler,
    Updater,
)

from bot_logger import BotLogsHandler
from elasticpath import ElasticPath

logger = logging.getLogger(__file__)


class Step(Enum):
    HANDLE_MENU  = 1
    WAIT = 2


def handle_fallback(update: Update, context: CallbackContext) -> Step:
    update.message.reply_text('Я тебя не понял...')

    return Step.HANDLE_MENU

def start(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    db.set(update.message.chat.id, 'SТART')

    products = []
    for product_notes in elastic.get_products():
        products.append([product_notes.get('attributes').get('name')])

    products_keyboard = ReplyKeyboardMarkup(products, resize_keyboard=True)

    update.message.reply_text(
        f'{update.effective_user.full_name}, будем знакомы, я Бот Ботыч!',
        reply_markup=products_keyboard,
    )

    return Step.HANDLE_MENU


def send_echo_msg(update: Update, context: CallbackContext, db: redis.StrictRedis) -> Step:
    db.set(update.message.chat.id, update.message.text)
    update.message.reply_text(update.message.text)

    return Step.HANDLE_MENU


def send_err(update: Update, context: CallbackContext) -> None:
    logger.error(msg='Exception during message processing:', exc_info=context.error)

    if update.effective_message:
        text = 'К сожалению произошла ошибка в момент обработки сообщения. ' \
               'Мы уже работаем над этой проблемой.'
        update.effective_message.reply_text(text)


def main():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s:%(levelname)s:%(message)s')
    logger.setLevel(logging.DEBUG)

    env = Env()
    env.read_env()
    elastic_base_url = env.str('ELASTIC_BASE_URL')
    elastic_client_id = env.str('ELASTIC_CLIENT_ID')
    elastic_client_secret = env.str('ELASTIC_CLIENT_SECRET')
    elastic_store_id = env.str('ELASTIC_STORE_ID')
    tg_token = env.str('TELEGRAM_BOT_TOKEN')
    admin_tg_token = env.str('TELEGRAM_ADMIN_BOT_TOKEN', '')
    admin_tg_chat_id = env.str('TELEGRAM_ADMIN_CHAT_ID', '')
    db_host = env.str('REDIS_HOST')
    db_port = env.int('REDIS_PORT')
    db_password = env.str('REDIS_PASSWORD')

    elastic = ElasticPath(
        base_url=env.str('ELASTIC_BASE_URL'),
        client_id=env.str('ELASTIC_CLIENT_ID'),
        client_secret=env.str('ELASTIC_CLIENT_SECRET'),
        store_id=env.str('ELASTIC_STORE_ID'),
    )


    elastic.get_products()

    bot = Bot(tg_token)
    tg_bot_name = f'@{bot.get_me().username}'

    if not admin_tg_token:
        admin_tg_token = tg_token

    logger.addHandler(BotLogsHandler(
        bot_name=tg_bot_name,
        admin_tg_token=admin_tg_token,
        admin_tg_chat_id=admin_tg_chat_id,
    ))


    db = redis.StrictRedis(
        host=db_host,
        port=db_port,
        password=db_password,
        charset='utf-8',
        decode_responses=True,
    )

    start_ = partial(start, db=db, elastic=elastic)
    send_echo_msg_ = partial(send_echo_msg, db=db)


    logger.info('Start Telegram bot.')

    while True:
        try:
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler('start', start_)],
                states={
                    Step.ECHO: [
                        MessageHandler(Filters.text, send_echo_msg_),
                        CommandHandler('start', start_),
                    ],
                    Step.HANDLE_MENU: [
                        MessageHandler(Filters.text, send_echo_msg_),
                        CommandHandler('start', start_)
                    ],
                },
                fallbacks=[MessageHandler(Filters.all, handle_fallback)],
            )

            updater = Updater(tg_token)
            dispatcher = updater.dispatcher
            dispatcher.add_error_handler(send_err)
            dispatcher.add_handler(conv_handler)
            updater.start_polling()
            updater.idle()

        except Exception as error:
            logger.exception(error)
            time.sleep(60)

if __name__ == '__main__':
    main()
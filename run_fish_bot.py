import logging
import time

from functools import partial
from enum import Enum
from textwrap import dedent
from typing import List

import redis

from environs import Env
from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
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
    HANDLE_DESCRIPTION = 2


def build_menu(buttons: List[InlineKeyboardButton], n_cols: int) -> List[List[InlineKeyboardButton]]:
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]

    return menu

def get_assortment_keyboard(elastic: ElasticPath):
    products = []
    for product_notes in elastic.get_products():
        products.append(
            InlineKeyboardButton(
                text=product_notes.get('attributes').get('name'),
                callback_data=product_notes.get('id'),
            )
        )

    return InlineKeyboardMarkup(build_menu(products, n_cols=3))


def handle_fallback(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Я тебя не понял...')


def handle_description(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query
    product_id = query.data

    db.set(query.message.chat.id, 'HANDLE_DESCRIPTION')

    product_notes = elastic.get_product_notes(product_id)
    product_attributes = product_notes.pop('attributes')
    product_relationships = product_notes.pop('relationships')

    name = product_attributes.get('name')
    price = int(product_attributes.get('price').get('USD').get('amount') / 100)
    description = product_attributes.get('description')
    image_id = product_relationships.get('main_image').get('data').get('id')

    variants = [
        InlineKeyboardButton(text='1 кг.', callback_data=1),
        InlineKeyboardButton(text='5 кг.', callback_data=5),
        InlineKeyboardButton(text='10 кг.', callback_data=10),
        InlineKeyboardButton(text='Назад', callback_data=0),
    ]

    query.answer()
    query.edit_message_media(
        media=InputMediaPhoto(
            media=open(elastic.get_image_path(image_id), 'rb'),
            caption=dedent(f'''\
                {name} -  {price}₽/кг.
                
                {description}
            '''),
        ),
        reply_markup=InlineKeyboardMarkup(build_menu(variants, n_cols=3)),
    )

    return Step.HANDLE_MENU


def handle_menu(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query

    db.set(query.message.chat.id, 'HANDLE_MENU')

    query.answer()
    query.edit_message_media(
        media=InputMediaPhoto(
            media=open('logo.png', 'rb'),
            caption=f'{update.effective_user.full_name}, посмотрит мой ассортимент 👇',
        ),
        reply_markup=get_assortment_keyboard(elastic),
    ),


    return Step.HANDLE_DESCRIPTION


def handle_start(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    db.set(update.message.chat.id, 'START')

    context.bot.send_photo(
        update.message.chat.id,
        photo=open('logo.png', 'rb'),
        caption=f'{update.effective_user.full_name}, посмотрит мой ассортимент 👇',
        reply_markup=get_assortment_keyboard(elastic),
    )

    return Step.HANDLE_DESCRIPTION

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

    handle_start_ = partial(handle_start, db=db, elastic=elastic)
    handle_menu_ = partial(handle_menu, db=db, elastic=elastic)
    handle_description_ = partial(handle_description, db=db, elastic=elastic)
    handle_fallback_ = partial(handle_fallback)

    logger.info('Start Telegram bot.')

    while True:
        try:
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler('start', handle_start_)],
                states={
                    Step.HANDLE_MENU: [
                        CallbackQueryHandler(handle_menu_),
                        CommandHandler('start', handle_start_),
                    ],
                    Step.HANDLE_DESCRIPTION: [
                        CallbackQueryHandler(handle_description_),
                        CommandHandler('start', handle_start_),
                    ],
                },
                fallbacks=[MessageHandler(Filters.all, handle_fallback_)],
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
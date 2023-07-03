import json
import logging
import time

from functools import partial
from enum import Enum
from textwrap import dedent

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
    HANDLE_ADD_TO_CART = 3
    HANDLE_CART = 4
    WAITING_EMAIL = 5


def build_keyboard_buttons(buttons: list[InlineKeyboardButton], n_cols: int) -> list[list[InlineKeyboardButton]]:
    buttons = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]

    return buttons

def get_assortment_keyboard(elastic: ElasticPath):
    products = []
    for product_notes in elastic.get_products():
        products.append(
            InlineKeyboardButton(
                text=product_notes.get('name'),
                callback_data=json.dumps({'id': product_notes.get('id')}),
            )
        )
    keyboard_buttons = build_keyboard_buttons(products, n_cols=4)
    keyboard_buttons += [
        [InlineKeyboardButton(
            text='Посмотреть корзину',
            callback_data=json.dumps({'cart': True}),
        )],
    ]

    return InlineKeyboardMarkup(keyboard_buttons)


def handle_add_to_cart(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query
    callback_query = json.loads(query.data)

    if callback_query.get('menu'):
        return handle_menu(update, context, db, elastic)
    elif callback_query.get('cart'):
        return handle_cart(update, context, db, elastic)

    db.set(query.message.chat.id, 'HANDLE_ADD_TO_CART')

    product_id = callback_query.get('id')
    quantity = callback_query.get('quantity')

    elastic.add_product_to_cart(product_id, quantity)

    variants = [
        InlineKeyboardButton(
            text='В меню',
            callback_data=json.dumps({'menu': True}),
        ),
        InlineKeyboardButton(
            text='Посмотреть корзину',
            callback_data=json.dumps({'cart': True}),
        ),
    ]

    query.answer()
    query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup(build_keyboard_buttons(variants, n_cols=1)),
    )

    return Step.HANDLE_CART


def handle_cart(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query
    callback_query = json.loads(query.data)

    if callback_query.get('menu'):
        return handle_menu(update, context, db, elastic)
    elif callback_query.get('delete'):
        elastic.delete_product_from_cart(callback_query.get('id'))
    elif callback_query.get('payment'):
        return handle_payment(update, context, db, elastic)

    db.set(query.message.chat.id, 'HANDLE_CART')

    cart_items = elastic.get_cart_items()
    cart_amount = int(cart_items.get("cart_amount") / 100)
    text = 'Состав корзины:\n'
    variants = [
        InlineKeyboardButton(
            text='В меню',
            callback_data=json.dumps({'menu': True}),
        ),
    ]

    for product_notes in cart_items.get('products'):
        product_name = product_notes.get("name")
        product_quantity = product_notes.get("quantity")
        product_amount = int(product_notes.get("amount") / 100)
        text += f'{product_name} {product_quantity}кг. - {product_amount} ₽\n'

        variants.append(
            InlineKeyboardButton(
                text=f'Удалить {product_notes.get("name")}',
                callback_data=json.dumps({
                    'delete': True,
                    'id': product_notes.get('id'),
                }),
            )
        )

    if cart_amount:
        text += f'\nСтоимость корзины - {cart_amount} ₽'

        variants.append(
            InlineKeyboardButton(
                text=f'Оплатить {cart_amount} ₽',
                callback_data=json.dumps({
                    'payment': True,
                    'cart_amount': cart_amount,
                }),
            ),
        )
    else:
        text = 'Ваша корзина пуста.'

    query.answer()
    query.edit_message_media(
        media=InputMediaPhoto(
            media=open('cart.png', 'rb'),
            caption=text,
        ),
        reply_markup=InlineKeyboardMarkup(build_keyboard_buttons(variants, n_cols=1)),
    )

    return Step.HANDLE_CART


def handle_description(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query
    callback_query = json.loads(query.data)

    if callback_query.get('menu'):
        return handle_menu(update, context, db, elastic)
    elif callback_query.get('cart'):
        return handle_cart(update, context, db, elastic)

    db.set(query.message.chat.id, 'HANDLE_DESCRIPTION')

    product_id = callback_query.get('id')
    product_notes = elastic.get_product_notes(product_id)

    name = product_notes.get('name')
    price = int(product_notes.get('price') / 100)
    description = product_notes.get('description')
    image_id = product_notes.get('main_image_id')

    variants = [
        InlineKeyboardButton(
            text='1 кг.',
            callback_data=json.dumps({'id': product_id, 'quantity': 1})
        ),
        InlineKeyboardButton(
            text='5 кг.',
            callback_data=json.dumps({'id': product_id, 'quantity': 5})
        ),
        InlineKeyboardButton(
            text='10 кг.',
            callback_data=json.dumps({'id': product_id, 'quantity': 10})
        ),
    ]

    keyboard_buttons = build_keyboard_buttons(variants, n_cols=3)
    keyboard_buttons += [
        [InlineKeyboardButton(
            text='В меню',
            callback_data=json.dumps({'menu': True}),
        )],
        [InlineKeyboardButton(
            text='Посмотреть корзину',
            callback_data=json.dumps({'cart': True}),
        )],
    ]

    query.answer()
    query.edit_message_media(
        media=InputMediaPhoto(
            media=open(elastic.get_image_path(image_id), 'rb'),
            caption=dedent(f'''\
                {name} - {price} ₽/кг.
                
                {description}
            '''),
        ),
        reply_markup=InlineKeyboardMarkup(keyboard_buttons),
    )

    return Step.HANDLE_ADD_TO_CART


def handle_error(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    logger.error(msg='Exception during message processing:', exc_info=context.error)

    db.set(context.user_data['chat_id'], 'ERROR')

    context.bot.edit_message_media(
        chat_id=context.user_data['chat_id'],
        message_id=context.user_data['bot_last_message_id'],
        media=InputMediaPhoto(
            media=open('logo.png', 'rb'),
            caption=dedent(f'''\
                    К сожалению произошла ошибка в момент обработки сообщения ☹️
                    Мы уже работаем над этой проблемой 👨‍🔧

                    {update.effective_user.full_name}, а пока посмотри мой ассортимент 👇,
                '''),
        ),
        reply_markup=get_assortment_keyboard(elastic),
    ),

    return Step.HANDLE_MENU


def handle_fallback(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    db.set(context.user_data['chat_id'], 'FALLBACK')

    context.bot.edit_message_media(
        chat_id=context.user_data['chat_id'],
        message_id=context.user_data['bot_last_message_id'],
        media=InputMediaPhoto(
            media=open('logo.png', 'rb'),
            caption=dedent(f'''\
                {update.effective_user.full_name}, я не понял твоё прошлое сообщение ☹️\n
                Мне понятны только нажатия на кнопки 🤷
                
                Посмотри мой ассортимент 👇,
            '''),
        ),
        reply_markup=get_assortment_keyboard(elastic),
    ),

    return Step.HANDLE_MENU


def handle_menu(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query
    callback_query = json.loads(query.data)

    db.set(query.message.chat.id, 'HANDLE_MENU')

    if callback_query.get('cart'):
        return handle_cart(update, context, db, elastic)

    query.answer()
    query.edit_message_media(
        media=InputMediaPhoto(
            media=open('logo.png', 'rb'),
            caption=dedent(f'''\
                {update.effective_user.full_name}, я продаю свежую красную рыбу 🐠

                Посмотри мой ассортимент 👇
            '''),
        ),
        reply_markup=get_assortment_keyboard(elastic),
    ),

    context.user_data['bot_last_message_id'] = query.message.message_id
    context.user_data['chat_id'] = query.message.chat.id

    return Step.HANDLE_DESCRIPTION


def handle_payment(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query
    callback_query = json.loads(query.data)

    db.set(query.message.chat.id, 'WAITING_EMAIL')

    if callback_query.get('menu'):
        return handle_menu(update, context, db, elastic)
    elif callback_query.get('cart'):
        return handle_cart(update, context, db, elastic)

    variants = [
        InlineKeyboardButton(
            text='В меню',
            callback_data=json.dumps({'menu': True}),
        ),
        InlineKeyboardButton(
            text='Посмотреть корзину',
            callback_data=json.dumps({'cart': True}),
        ),
    ]

    query.answer()
    query.edit_message_media(
        media=InputMediaPhoto(
            media=open('logo.png', 'rb'),
            caption=dedent(f'''\
                Укажите свой email 📧
                
                Мы на него отправим счёта на оплату {callback_query.get("cart_amount")} ₽
            '''),
        ),
        reply_markup=InlineKeyboardMarkup(build_keyboard_buttons(variants, n_cols=1)),
    )

    return Step.WAITING_EMAIL


def handle_start(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    db.set(update.message.chat.id, 'START')

    message = context.bot.send_photo(
        update.message.chat.id,
        photo=open('logo.png', 'rb'),
        caption=dedent(f'''\
                {update.effective_user.full_name}, привет 👋
                Я продаю свежую красную рыбу 🐠
                
                Посмотри мой ассортимент 👇
            '''),
        reply_markup=get_assortment_keyboard(elastic),
    )

    context.user_data['bot_last_message_id'] = message.message_id
    context.user_data['chat_id'] = update.message.chat.id

    return Step.HANDLE_DESCRIPTION


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

    handle_add_to_cart_ = partial(handle_add_to_cart, db=db, elastic=elastic)
    handle_cart_ = partial(handle_cart, db=db, elastic=elastic)
    handle_description_ = partial(handle_description, db=db, elastic=elastic)
    handle_error_ = partial(handle_error, db=db, elastic=elastic)
    handle_fallback_ = partial(handle_fallback, db=db, elastic=elastic)
    handle_menu_ = partial(handle_menu, db=db, elastic=elastic)
    handle_start_ = partial(handle_start, db=db, elastic=elastic)

    logger.info('Start Telegram bot.')

    while True:
        try:
            conv_handler = ConversationHandler(
                entry_points=[
                    CommandHandler('start', handle_start_),
                    CallbackQueryHandler(handle_menu_),
                ],
                states={
                    Step.HANDLE_MENU: [
                        CallbackQueryHandler(handle_menu_),
                        CommandHandler('start', handle_start_),
                    ],
                    Step.HANDLE_DESCRIPTION: [
                        CallbackQueryHandler(handle_description_),
                        CommandHandler('start', handle_start_),
                    ],
                    Step.HANDLE_ADD_TO_CART: [
                        CallbackQueryHandler(handle_add_to_cart_),
                        CommandHandler('start', handle_start_),
                    ],
                    Step.HANDLE_CART: [
                        CallbackQueryHandler(handle_cart_),
                        CommandHandler('start', handle_start_),
                    ],
                },
                fallbacks=[MessageHandler(Filters.all, handle_fallback_)],
            )

            updater = Updater(tg_token)
            dispatcher = updater.dispatcher
            dispatcher.add_error_handler(handle_error_)
            dispatcher.add_handler(conv_handler)
            updater.start_polling()
            updater.idle()

        except Exception as error:
            logger.exception(error)
            time.sleep(60)

if __name__ == '__main__':
    main()
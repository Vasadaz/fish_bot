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


def build_keyboard_buttons(buttons: list[InlineKeyboardButton], cols_count: int) -> list[list[InlineKeyboardButton]]:
    buttons = [buttons[i:i + cols_count] for i in range(0, len(buttons), cols_count)]

    return buttons


def get_assortment_keyboard(elastic: ElasticPath) -> InlineKeyboardMarkup:
    products = []
    for product_notes in elastic.get_products():
        products.append(InlineKeyboardButton(
                text=product_notes.get('name'),
                callback_data=json.dumps({'id': product_notes.get('id')}),
        ))

    keyboard_buttons = build_keyboard_buttons(products, cols_count=4)
    keyboard_buttons += [[InlineKeyboardButton(text='Посмотреть корзину', callback_data='cart')]]

    return InlineKeyboardMarkup(keyboard_buttons)


def get_standard_buttons() -> list[list[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(text='В меню', callback_data='menu')],
        [InlineKeyboardButton(text='Посмотреть корзину', callback_data='cart')],
    ]


def handle_add_to_cart(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query
    callback_query = json.loads(query.data)

    db.set(query.message.chat.id, 'HANDLE_ADD_TO_CART')

    customer_id = db.get(f'{query.message.chat.id}_customer_id')

    if not customer_id:
        email = f'{query.message.chat.id}@telegram.id'
        name = f'{query.message.chat.full_name} ({query.message.chat.id})'
        customer_id = elastic.create_customer(email, name)
        db.set(f'{query.message.chat.id}_customer_id', customer_id)

    product_id = callback_query.get('id')
    quantity = callback_query.get('quantity')

    elastic.add_product_to_cart(customer_id, product_id, quantity)

    query.answer()
    query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(get_standard_buttons()))

    return Step.HANDLE_CART


def handle_cart(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query

    db.set(query.message.chat.id, 'HANDLE_CART')
    customer_id = db.get(f'{query.message.chat.id}_customer_id')

    cart_items = elastic.get_cart_items(customer_id)
    cart_amount = int(cart_items.get("cart_amount") / 100)
    text = 'Состав корзины:\n'
    keyboard_buttons = []

    for product_notes in cart_items.get('products'):
        product_name = product_notes.get("name")
        product_quantity = product_notes.get("quantity")
        product_amount = int(product_notes.get("amount") / 100)
        text += f'{product_name} {product_quantity}кг. - {product_amount} ₽\n'

        keyboard_buttons.append(InlineKeyboardButton(
            text=f'Удалить {product_notes.get("name")}',
            callback_data=json.dumps({'delete': True, 'id': product_notes.get('id')}),
        ))

    keyboard_buttons.append(InlineKeyboardButton(text='В меню', callback_data='menu'))

    if cart_amount:
        text += f'\nСтоимость корзины - {cart_amount} ₽'

        keyboard_buttons.append(InlineKeyboardButton(
            text=f'Оплатить {cart_amount} ₽',
            callback_data=json.dumps({'payment': True, 'cart_amount': cart_amount}),
        ))
    else:
        text = 'Ваша корзина пуста.'

    image_path = 'static/cart.png'
    keyboard_buttons = build_keyboard_buttons(keyboard_buttons, cols_count=1)
    media = InputMediaPhoto(media=open(image_path, 'rb'), caption=text)

    query.answer()
    query.edit_message_media(media=media, reply_markup=InlineKeyboardMarkup(keyboard_buttons))

    return Step.HANDLE_CART

def handle_delete(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query
    callback_query = json.loads(query.data)
    customer_id = db.get(f'{query.message.chat.id}_customer_id')

    elastic.delete_product_from_cart(customer_id, callback_query.get('id'))

    return handle_cart(update, context, db, elastic)


def handle_description(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query
    callback_query = json.loads(query.data)

    db.set(query.message.chat.id, 'HANDLE_DESCRIPTION')

    product_id = callback_query.get('id')
    product_notes = elastic.get_product_notes(product_id)

    name = product_notes.get('name')
    price = int(product_notes.get('price') / 100)
    description = product_notes.get('description')
    image_id = product_notes.get('main_image_id')

    keyboard_buttons = [
        InlineKeyboardButton(
            text='1 кг.',
            callback_data=json.dumps({'id': product_id, 'quantity': 1}),
        ),
        InlineKeyboardButton(
            text='5 кг.',
            callback_data=json.dumps({'id': product_id, 'quantity': 5}),
        ),
        InlineKeyboardButton(
            text='10 кг.',
            callback_data=json.dumps({'id': product_id, 'quantity': 10}),
        ),
    ]

    keyboard_buttons = build_keyboard_buttons(keyboard_buttons, cols_count=3)
    keyboard_buttons += get_standard_buttons()

    text = dedent(f'''\
    {name} - {price} ₽/кг.
    
    {description}
    ''')
    media = InputMediaPhoto(media=open(elastic.get_image_path(image_id), 'rb'), caption=text)

    query.answer()
    query.edit_message_media(media=media, reply_markup=InlineKeyboardMarkup(keyboard_buttons))

    return Step.HANDLE_ADD_TO_CART


def handle_email(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    db.set(update.message.chat.id, 'WAITING_EMAIL')

    customer_id = db.get(f'{update.message.chat.id}_customer_id')

    elastic.update_customer_email(customer_id, update.message.text)
    elastic.create_order(customer_id)
    elastic.clear_cart(customer_id)

    keyboard_buttons = InlineKeyboardMarkup([[InlineKeyboardButton(text='В меню', callback_data='menu')]])
    image_path = 'static/cart.png'
    text = dedent(f'''\
    Мы получили ваш email 📧
    В течении дня вам придёт счёт на почту {elastic.get_customer_email(customer_id)}

    Ваша корзина пуста.
    ''')
    media = InputMediaPhoto(media=open(image_path, 'rb'), caption=text)

    context.bot.edit_message_media(
        chat_id=context.user_data['chat_id'],
        message_id=context.user_data['bot_last_message_id'],
        media=media,
        reply_markup=keyboard_buttons,
    )

    return Step.HANDLE_CART


def handle_error(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    logger.error(msg='Exception during message processing:', exc_info=context.error)
    db.set(context.user_data['chat_id'], 'ERROR')

    image_path = 'static/logo.png'
    text = dedent(f'''\
    К сожалению произошла ошибка в момент обработки сообщения ☹️
    Мы уже работаем над этой проблемой 👨‍🔧

    {update.effective_user.full_name}, а пока посмотри мой ассортимент 👇,
    ''')
    media = InputMediaPhoto(media=open(image_path, 'rb'), caption=text)

    context.bot.edit_message_media(
        chat_id=context.user_data['chat_id'],
        message_id=context.user_data['bot_last_message_id'],
        media=media,
        reply_markup=get_assortment_keyboard(elastic),
    ),

    return Step.HANDLE_MENU


def handle_fallback(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    db.set(context.user_data['chat_id'], 'FALLBACK')

    image_path = 'static/logo.png'
    text = dedent(f'''\
    {update.effective_user.full_name}, я не понял твоё прошлое сообщение ☹️
    Мне понятны только нажатия на кнопки 🤷
    
    Посмотри мой ассортимент 👇
    ''')
    media = InputMediaPhoto(media=open(image_path, 'rb'),  caption=text)

    context.bot.edit_message_media(
        chat_id=context.user_data['chat_id'],
        message_id=context.user_data['bot_last_message_id'],
        media=media,
        reply_markup=get_assortment_keyboard(elastic),
    ),

    return Step.HANDLE_MENU


def handle_menu(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query

    db.set(query.message.chat.id, 'HANDLE_MENU')

    image_path = 'static/logo.png'
    text = dedent(f'''\
    {update.effective_user.full_name}, я продаю свежую красную рыбу 🐠

    Посмотри мой ассортимент 👇
    ''')
    media = InputMediaPhoto(media=open(image_path, 'rb'), caption=text)

    query.answer()
    query.edit_message_media(media=media, reply_markup=get_assortment_keyboard(elastic))

    context.user_data['bot_last_message_id'] = query.message.message_id
    context.user_data['chat_id'] = query.message.chat.id

    return Step.HANDLE_DESCRIPTION

def handle_order(update: Update, context: CallbackContext,  db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query
    db.set(query.message.chat.id, 'CREATE_ORDER')

    customer_id = db.get(f'{query.message.chat.id}_customer_id')

    elastic.create_order(customer_id)
    elastic.clear_cart(customer_id)

    keyboard_buttons = InlineKeyboardMarkup([[InlineKeyboardButton(text='В меню', callback_data='menu')]])
    image_path = 'static/cart.png'
    text = dedent(f'''\
    В течении дня вам придёт счёт на почту {elastic.get_customer_email(customer_id)}

    Ваша корзина пуста.
    ''')
    media = InputMediaPhoto(media=open(image_path, 'rb'), caption=text)

    query.edit_message_media(
        media=media,
        reply_markup=keyboard_buttons,
    )

    return Step.HANDLE_CART


def handle_payment(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    query = update.callback_query
    callback_query = json.loads(query.data)

    db.set(query.message.chat.id, 'WAITING_EMAIL')

    customer_id = db.get(f'{query.message.chat.id}_customer_id')

    if not str(query.message.chat.id) in elastic.get_customer_email(customer_id):
        return handle_order(update, context, db, elastic)

    image_path = 'static/cart.png'
    text = dedent(f'''\
    У нас нет вашей почты 😔
    Укажите свой email 📧
    
    Мы на него отправим счёта на оплату {callback_query.get("cart_amount")} ₽
    ''')
    media = InputMediaPhoto(media=open(image_path, 'rb'), caption=text)

    query.answer()
    query.edit_message_media(media=media, reply_markup=InlineKeyboardMarkup(get_standard_buttons()))

    return Step.WAITING_EMAIL


def handle_start(update: Update, context: CallbackContext, db: redis.StrictRedis, elastic: ElasticPath) -> Step:
    db.set(update.message.chat.id, 'START')

    image_path = 'static/logo.png'
    text = dedent(f'''\
    {update.effective_user.full_name}, привет 👋
    Я продаю свежую красную рыбу 🐠
    
    Посмотри мой ассортимент 👇
    ''')

    message = context.bot.send_photo(
        update.message.chat.id,
        photo=open(image_path, 'rb'),
        caption=text,
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
    tg_token = env.str('TELEGRAM_BOT_TOKEN')
    admin_tg_token = env.str('TELEGRAM_ADMIN_BOT_TOKEN', '')
    admin_tg_chat_id = env.str('TELEGRAM_ADMIN_CHAT_ID', '')
    db_host = env.str('REDIS_HOST')
    db_port = env.int('REDIS_PORT')
    db_password = env.str('REDIS_PASSWORD')



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

    elastic = ElasticPath(
        base_url=env.str('ELASTIC_BASE_URL'),
        client_id=env.str('ELASTIC_CLIENT_ID'),
        client_secret=env.str('ELASTIC_CLIENT_SECRET'),
    )

    handle_add_to_cart_ = partial(handle_add_to_cart, db=db, elastic=elastic)
    handle_cart_ = partial(handle_cart, db=db, elastic=elastic)
    handle_description_ = partial(handle_description, db=db, elastic=elastic)
    handle_delete_ = partial(handle_delete, db=db, elastic=elastic)
    handle_email_ = partial(handle_email, db=db, elastic=elastic)
    handle_error_ = partial(handle_error, db=db, elastic=elastic)
    handle_fallback_ = partial(handle_fallback, db=db, elastic=elastic)
    handle_menu_ = partial(handle_menu, db=db, elastic=elastic)
    handle_payment_ = partial(handle_payment, db=db, elastic=elastic)
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
                        CallbackQueryHandler(handle_cart_, pattern='cart'),
                        CallbackQueryHandler(handle_menu_),
                    ],
                    Step.HANDLE_DESCRIPTION: [
                        CallbackQueryHandler(handle_cart_, pattern='cart'),
                        CallbackQueryHandler(handle_description_),

                    ],
                    Step.HANDLE_ADD_TO_CART: [
                        CallbackQueryHandler(handle_menu_, pattern='menu'),
                        CallbackQueryHandler(handle_cart_, pattern='cart'),
                        CallbackQueryHandler(handle_add_to_cart_),
                    ],
                    Step.HANDLE_CART: [
                        CallbackQueryHandler(handle_menu_, pattern='menu'),
                        CallbackQueryHandler(handle_payment_, pattern='.*payment.*'),
                        CallbackQueryHandler(handle_delete_, pattern='.*delete.*'),
                        CallbackQueryHandler(handle_cart_),
                    ],
                    Step.WAITING_EMAIL: [
                        CallbackQueryHandler(handle_menu_, pattern='menu'),
                        CallbackQueryHandler(handle_cart_, pattern='cart'),
                        MessageHandler(Filters.regex('@'), handle_email_),
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
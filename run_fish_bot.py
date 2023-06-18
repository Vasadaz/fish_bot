import logging
import time

from environs import Env
from telegram import Bot, Update, ForceReply
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

from bot_logger import BotLogsHandler

logger = logging.getLogger(__file__)


def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(f'{update.effective_user.full_name}, будем знакомы, я Бот Ботыч!')


def send_echo_msg(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(update.message.text)


def send_err(update: Update, context: CallbackContext) -> None:
    logger.error(msg='Exception during message processing:', exc_info=context.error)

    if update.effective_message:
        text = 'К сожалению произошла ошибка в момент обработки сообщения. ' \
               'Мы уже работаем над этой проблемой.'
        update.effective_message.reply_text(text)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s:%(levelname)s:%(message)s')
    logger.setLevel(logging.DEBUG)

    env = Env()
    env.read_env()
    tg_token = env.str('TELEGRAM_BOT_TOKEN')
    admin_tg_token = env.str('TELEGRAM_ADMIN_BOT_TOKEN', '')
    admin_tg_chat_id = env.str('TELEGRAM_ADMIN_CHAT_ID', '')

    bot = Bot(tg_token)
    tg_bot_name = f'@{bot.get_me().username}'

    if not admin_tg_token:
        admin_tg_token = tg_token

    logger.addHandler(BotLogsHandler(
        bot_name=tg_bot_name,
        admin_tg_token=admin_tg_token,
        admin_tg_chat_id=admin_tg_chat_id,
    ))

    logger.info('Start Telegram bot.')

    while True:
        try:
            updater = Updater(tg_token)

            dispatcher = updater.dispatcher
            dispatcher.add_error_handler(send_err)
            dispatcher.add_handler(CommandHandler('start', start))
            dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, send_echo_msg))

            updater.start_polling()
            updater.idle()
        except Exception as error:
            logger.exception(error)
            time.sleep(60)

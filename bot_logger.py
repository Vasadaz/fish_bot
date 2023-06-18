import logging

from telegram import Bot


class BotLogsHandler(logging.Handler):
    def __init__(self, bot_name, admin_tg_token, admin_tg_chat_id):
        super().__init__()
        self.bot_name = bot_name
        self.admin_tg_token = admin_tg_token
        self.admin_tg_chat_id = admin_tg_chat_id

    def emit(self, record):
        log_entry = self.format(record)
        bot = Bot(self.admin_tg_token)
        bot.send_message(
            chat_id=self.admin_tg_chat_id,
            text=f'{record.levelname} - sender {self.bot_name}:\n\n{log_entry}',
        )

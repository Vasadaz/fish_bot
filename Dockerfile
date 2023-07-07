FROM python:3.11.3-slim
LABEL authors="Nikolay Sysoev"
COPY requirements.txt /opt/fish_bot/requirements.txt
WORKDIR /opt/fish_bot
RUN pip install --no-cache-dir --upgrade -r requirements.txt
COPY . .
CMD ["python", "run_fish_bot.py"]

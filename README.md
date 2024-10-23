# Tea Bot

A telegram bot that allows you to post anonymously create secrets in Nillion and post them to a web app.

## Requirements

Before running the bot, you need to install the required packages. You can do this by running:

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file by copying the `.env.example` file and add your telegram bot token. You can create the Nillion API base endpoint expected by cloning and running the APIs here: https://github.com/oceans404/blind_confessions.

## Running the bot

Start the bot by running:

```
python bot.py
```

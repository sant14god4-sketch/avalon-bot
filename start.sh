#!/bin/bash
# Iniciar la pasarela de pagos (gunicorn) en segundo plano
gunicorn transak_gateway:app --bind 0.0.0.0:$PORT &

# Iniciar el bot de trading (en primer plano, para que Render no lo mate)
python main_bot.py

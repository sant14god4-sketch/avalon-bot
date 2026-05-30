#!/bin/bash
gunicorn transak_gateway:app --bind 0.0.0.0:$PORT &
python main_bot.py

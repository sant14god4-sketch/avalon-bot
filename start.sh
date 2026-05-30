#!/bin/bash
echo "📦 Instalando dependencias forzadamente..."
pip install alpaca-py twelvedata flask gunicorn requests python-dotenv schedule pandas yfinance

echo "🚀 Iniciando Gunicorn (pasarela de pagos)..."
gunicorn transak_gateway:app --bind 0.0.0.0:$PORT &

echo "🤖 Iniciando Bot de trading..."
python main_bot.py

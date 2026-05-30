#!/bin/bash
echo "📦 Instalando dependencias forzadamente..."
pip install alpaca-trade-api twelvedata flask gunicorn requests python-dotenv schedule pandas

echo "🚀 Iniciando Gunicorn (pasarela de pagos)..."
gunicorn transak_gateway:app --bind 0.0.0.0:$PORT &

echo "🤖 Iniciando Bot de trading..."
python main_bot.py

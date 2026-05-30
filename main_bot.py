#!/usr/bin/env python3
import os
import time
import logging
import requests
import schedule
from datetime import datetime, timedelta
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from twelvedata import TDClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AvalonBot:
    def __init__(self):
        # --- Configuración de APIs (Corregido) ---
        self.alpaca = TradingClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            paper=True
        )
        self.td = TDClient(apikey=os.getenv("TWELVEDATA_API_KEY"))
        self.deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        
        # --- Estado del bot ---
        self.capital_usd = 100000.0
        self.vix = 25.0
        self.panic_score = 0.0
        self.panic_history = []  # Lista de tuplas (datetime, score)
        self.etfs = {
            "JETS": 0.20,
            "EWW": 0.10,
            "EWC": 0.10,
            "KRE": 0.20,
            "XLE": 0.15,
            "HYG": 0.15,
            "PEJ": 0.10
        }
        self.fase = "VIGILIA"
        
        # --- Fechas clave de la estrategia ---
        self.eval_date = datetime(2026, 8, 25)       # 25 de agosto 2026
        self.force_close_date = datetime(2026, 9, 16) # 16 de septiembre 2026
        self.expiry_date = datetime(2027, 1, 15)      # Vencimiento LEAPS

    # ---------- OBTENCIÓN DE DATOS ----------
    def get_vix(self):
        """Obtiene el VIX real usando el símbolo IVX para Twelve Data"""
        try:
            # Cambio crucial: "IVX" es el símbolo correcto para el VIX en el plan gratuito
            df = self.td.time_series(symbol="IVX", interval="1min", outputsize=1).as_pandas()
            self.vix = df['close'].iloc[-1]
            logger.info(f"VIX actual: {self.vix}")
        except Exception as e:
            logger.error(f"Error obteniendo VIX: {e}")
            self.vix = 25.0

    def get_panic_score(self):
        """Consulta a DeepSeek con un manejo de errores robusto"""
        try:
            prompt = ("Eres analista financiero. Analiza noticias recientes de Norteamérica: "
                      "cuarentenas, restricciones de viaje, emergencias sanitarias, pánico en redes. "
                      "Asigna una puntuación de pánico del 0 al 1. Responde SOLO con el número.")
            headers = {"Authorization": f"Bearer {self.deepseek_key}", "Content-Type": "application/json"}
            data = {
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 10
            }
            resp = requests.post("https://api.deepseek.com/v1/chat/completions", json=data, headers=headers, timeout=30)
            # Manejo de errores robusto
            result = resp.json()
            if "choices" in result and len(result["choices"]) > 0 and "message" in result["choices"][0]:
                content = result["choices"][0]["message"]["content"].strip()
                score = float(content)
                self.panic_score = min(max(score, 0.0), 1.0)
                self.panic_history.append((datetime.now(), self.panic_score))
                # Mantener solo últimos 30 días
                cutoff = datetime.now() - timedelta(days=30)
                self.panic_history = [(d, s) for d, s in self.panic_history if d > cutoff]
                logger.info(f"DeepSeek puntuación de pánico: {self.panic_score}")
            else:
                # Respuesta inesperada, se usa el valor anterior
                logger.warning(f"Respuesta inesperada de DeepSeek: {result}")
        except Exception as e:
            logger.error(f"DeepSeek falló: {e}")
            # Mantener la puntuación anterior

    # ---------- INDICADORES DE LA ESTRATEGIA ----------
    def check_indicators(self):
        """Evalúa si los indicadores de pánico muestran presencia o aceleración"""
        now = datetime.now()
        # 1. Aceleración: puntuación > 0.5 en los últimos 7 días
        last_7days = [(d, s) for d, s in self.panic_history if d > now - timedelta(days=7)]
        if any(s > 0.5 for _, s in last_7days):
            return "ACELERACION"
        # 2. Presencia: puntuación > 0.3 sostenida durante 72h
        three_days_ago = now - timedelta(hours=72)
        recent = [(d, s) for d, s in self.panic_history if d > three_days_ago]
        if len(recent) >= 3 and all(s > 0.3 for _, s in recent):
            return "PRESENCIA"
        return "NINGUNO"

    # ---------- ESTRATEGIA DE FUTUROS ----------
    def manage_futures(self):
        """Termómetro VIX: ajusta margen, stops y apalancamiento"""
        if self.vix < 26:
            margin_pct, stop = 0.25, -0.02
            mode = "CALMA"
        elif self.vix < 40:
            margin_pct, stop = 0.35, -0.015
            mode = "ALERTA"
        elif self.vix < 60:
            margin_pct, stop = 0.40, 0.0
            mode = "PANICO"
        elif self.vix < 85:
            margin_pct, stop = 0.40, None
            mode = "CRISIS"
        else:
            logger.info("VIX > 85: ¡Objetivo alcanzado! Cerrando todo.")
            self.close_all_positions()
            return

        # Refuerzo adicional si pánico > 0.7
        if self.panic_score > 0.7:
            margin_pct = min(0.40, margin_pct + 0.10)
            logger.info("Refuerzo +10% por pánico extremo")
        
        # Cálculo de exposición con apalancamiento 3x
        exposicion = self.capital_usd * 3.0
        spy = self.get_sp500()
        if spy > 0:
            # Cada contrato /MES (Micro E-mini S&P 500) equivale a $5 x SPX ≈ $25,000 de exposición
            contratos = max(1, min(10, int(exposicion / (spy * 5))))
            logger.info(f"{mode} | VIX={self.vix:.1f} | Margen: {margin_pct*100}% | Stop: {stop if stop else 'ninguno'} | Contratos: {contratos} /MES")
            # Llamada a la API para enviar la orden (modo paper)
            # ...
    
    def get_sp500(self):
        try:
            df = self.td.time_series(symbol="SPX", interval="1min", outputsize=1).as_pandas()
            return df['close'].iloc[-1]
        except:
            return 5000.0

    # ---------- OPCIONES PUT LEAPS ----------
    def buy_puts(self):
        """Compra PUT LEAPS sobre los 7 ETFs si VIX bajo"""
        if self.vix > 30:
            logger.info("VIX alto, esperando para comprar puts (mejor precio con VIX bajo)")
            return
        for etf, alloc in self.etfs.items():
            monto = self.capital_usd * alloc
            logger.info(f"Comprando PUT LEAPS {etf} por ${monto:,.2f} USD")
            # Llamada a la API para comprar opciones
            # ...

    def renew_options(self):
        """Renovación inteligente si DeepSeek > 0.15"""
        if self.panic_score > 0.15:
            logger.info("Renovando opciones (DeepSeek > 0.15)")
            # ...
    
    def close_all_positions(self):
        logger.info("Cerrando todas las posiciones (futuros y opciones).")

    def check_closure(self):
        """Evalúa las fechas clave: cierre del 25 de agosto o forzoso del 16 de septiembre"""
        today = datetime.now().date()
        if today >= self.force_close_date.date():
            logger.info("=== FECHA LÍMITE: 16 DE SEPTIEMBRE 2026 ===")
            self.close_all_positions()
            self.fase = "CERRADA"
            return
        if today == self.eval_date.date() or today > self.eval_date.date():
            logger.info("=== EVALUACIÓN: 25 DE AGOSTO 2026 ===")
            indicator = self.check_indicators()
            if indicator == "NINGUNO":
                logger.info("Sin indicadores. Cierre preventivo: liquidando y devolviendo capital.")
                self.close_all_positions()
                self.fase = "CERRADA"
            else:
                logger.info(f"Indicadores activos ({indicator}). La estrategia continúa hasta enero 2027 o VIX > 85.")
                self.fase = "ACTIVA"
                
    def run_cycle(self):
        logger.info("=== Ciclo Avalon Bot ===")
        self.get_vix()
        self.get_panic_score()
        self.check_closure()
        if self.fase != "CERRADA":
            self.manage_futures()
            self.buy_puts()
            self.renew_options()
    
    def start(self):
        logger.info("🚀 Bot Avalon iniciado. Evaluación: 25/08/2026, Cierre forzoso: 16/09/2026.")
        schedule.every(30).minutes.do(self.run_cycle)
        self.run_cycle()
        while True:
            schedule.run_pending()
            time.sleep(60)

if __name__ == "__main__":
    bot = AvalonBot()
    bot.start()

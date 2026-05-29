#!/usr/bin/env python3
import os, time, logging, requests, schedule
from datetime import datetime, timedelta
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from twelvedata import TDClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AvalonBot:
    def __init__(self):
        self.alpaca = TradingClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True)
        self.td = TDClient(apikey=os.getenv("TWELVEDATA_API_KEY"))
        self.deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        self.capital_usd = 100000.0
        self.vix = 25.0
        self.panic_score = 0.0
        self.panic_history = []
        self.etfs = {"JETS":0.20, "EWW":0.10, "EWC":0.10, "KRE":0.20, "XLE":0.15, "HYG":0.15, "PEJ":0.10}
        self.eval_date = datetime(2026, 8, 25)
        self.force_close_date = datetime(2026, 9, 16)
        self.expiry_date = datetime(2027, 1, 15)
        self.fase = "VIGILIA"

    def get_vix(self):
        try:
            df = self.td.time_series(symbol="VIX", interval="1min", outputsize=1).as_pandas()
            self.vix = df['close'].iloc[-1]
            logger.info(f"VIX: {self.vix}")
        except Exception as e:
            logger.error(f"Error VIX: {e}")

    def get_panic_score(self):
        try:
            prompt = "Puntuación de pánico (0-1) en Norteamérica por cuarentenas, restricciones. Solo número."
            headers = {"Authorization": f"Bearer {self.deepseek_key}", "Content-Type": "application/json"}
            data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 10}
            resp = requests.post("https://api.deepseek.com/v1/chat/completions", json=data, headers=headers, timeout=30)
            score = float(resp.json()["choices"][0]["message"]["content"].strip())
            self.panic_score = min(max(score, 0.0), 1.0)
            self.panic_history.append((datetime.now(), self.panic_score))
            cutoff = datetime.now() - timedelta(days=30)
            self.panic_history = [(d,s) for d,s in self.panic_history if d > cutoff]
            logger.info(f"DeepSeek pánico: {self.panic_score}")
        except Exception as e:
            logger.error(f"DeepSeek falló: {e}")

    def check_indicators(self):
        now = datetime.now()
        last_7days = [(d,s) for d,s in self.panic_history if d > now - timedelta(days=7)]
        if any(s > 0.5 for _,s in last_7days):
            return "ACELERACION"
        three_days_ago = now - timedelta(hours=72)
        recent = [(d,s) for d,s in self.panic_history if d > three_days_ago]
        if len(recent) >= 3 and all(s > 0.3 for _,s in recent):
            return "PRESENCIA"
        return "NINGUNO"

    def manage_futures(self):
        if self.vix < 26:
            margin_pct, stop = 0.25, -0.02
            mode = "CALMA"
        elif self.vix < 40:
            margin_pct, stop = 0.35, -0.015
            mode = "ALERTA"
        elif self.vix < 60:
            margin_pct, stop = 0.40, 0.0
            mode = "PÁNICO"
        elif self.vix < 85:
            margin_pct, stop = 0.40, None
            mode = "CRISIS"
        else:
            logger.info("VIX > 85 ¡Objetivo alcanzado! Cerrando todo.")
            self.close_all_positions()
            return
        if self.panic_score > 0.7:
            margin_pct = min(0.40, margin_pct + 0.10)
            logger.info("Refuerzo +10% por pánico extremo")
        exposicion = self.capital_usd * 3.0
        spy = self.get_sp500()
        if spy > 0:
            contratos = max(1, min(10, int(exposicion / (spy * 5))))
            logger.info(f"{mode} | Margen: {margin_pct*100}% | Stop: {stop if stop else 'ninguno'} | Contratos: {contratos} /MES")

    def get_sp500(self):
        try:
            df = self.td.time_series(symbol="SPX", interval="1min", outputsize=1).as_pandas()
            return df['close'].iloc[-1]
        except:
            return 5000.0

    def buy_puts(self):
        if self.vix > 30:
            logger.info("VIX alto, esperando para comprar puts")
            return
        for etf, alloc in self.etfs.items():
            monto = self.capital_usd * alloc
            logger.info(f"Comprando PUT LEAPS {etf} por ${monto:,.2f} USD")

    def renew_options(self):
        if self.panic_score > 0.15:
            logger.info("Renovando opciones (DeepSeek > 0.15)")

    def close_all_positions(self):
        logger.info("Cerrando todas las posiciones (futuros y opciones)")

    def check_closure(self):
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
                logger.info("Sin indicadores. Cierre preventivo.")
                self.close_all_positions()
                self.fase = "CERRADA"
            else:
                logger.info(f"Indicadores activos ({indicator}). Estrategia continúa.")

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
        logger.info("🚀 Bot Avalon iniciado. Evaluación: 25/08/2026, Cierre forzoso: 16/09/2026")
        schedule.every(30).minutes.do(self.run_cycle)
        self.run_cycle()
        while True:
            schedule.run_pending()
            time.sleep(60)

if __name__ == "__main__":
    bot = AvalonBot()
    bot.start()

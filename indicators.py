"""
QuantBot AI — Motor de Indicadores Técnicos
RSI, MACD, EMA, Volume, Price Action, Suporte/Resistência
"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class TechnicalAnalysis:
    """
    Motor completo de análise técnica.
    Recebe lista de candles e calcula todos os indicadores.
    """
    
    def __init__(self, candles: List[dict]):
        self.candles = [Candle(**c) for c in candles]
        self.closes = np.array([c.close for c in self.candles])
        self.highs = np.array([c.high for c in self.candles])
        self.lows = np.array([c.low for c in self.candles])
        self.volumes = np.array([c.volume for c in self.candles])
        self.opens = np.array([c.open for c in self.candles])

    # ─── EMA ─────────────────────────────────────────────────────────────────

    def ema(self, period: int, data: Optional[np.ndarray] = None) -> float:
        """Exponential Moving Average — retorna valor atual"""
        prices = data if data is not None else self.closes
        if len(prices) < period:
            return float(prices[-1])
        
        k = 2.0 / (period + 1)
        ema_val = float(prices[0])
        for price in prices[1:]:
            ema_val = float(price) * k + ema_val * (1 - k)
        return round(ema_val, 8)

    def ema_series(self, period: int, data: Optional[np.ndarray] = None) -> np.ndarray:
        """Série completa de EMA"""
        prices = data if data is not None else self.closes
        k = 2.0 / (period + 1)
        ema_arr = np.zeros(len(prices))
        ema_arr[0] = prices[0]
        for i in range(1, len(prices)):
            ema_arr[i] = prices[i] * k + ema_arr[i - 1] * (1 - k)
        return ema_arr

    def sma(self, period: int) -> float:
        """Simple Moving Average"""
        if len(self.closes) < period:
            return float(self.closes[-1])
        return round(float(np.mean(self.closes[-period:])), 8)

    # ─── RSI ─────────────────────────────────────────────────────────────────

    def rsi(self, period: int = 14) -> float:
        """
        Relative Strength Index
        < 30: sobrevenda (sinal de compra)
        > 70: sobrecompra (sinal de venda)
        """
        if len(self.closes) < period + 1:
            return 50.0
        
        deltas = np.diff(self.closes[-(period + 10):])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return round(100.0 - (100.0 / (1 + rs)), 2)

    # ─── MACD ────────────────────────────────────────────────────────────────

    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """
        MACD — Moving Average Convergence Divergence
        Retorna: macd_line, signal_line, histogram, crossover
        """
        ema_fast = self.ema_series(fast)
        ema_slow = self.ema_series(slow)
        
        macd_line = ema_fast - ema_slow
        signal_line = self.ema_series(signal, data=macd_line)
        histogram = macd_line - signal_line
        
        # Detectar cruzamento (últimas 2 velas)
        if len(histogram) >= 2:
            bullish_cross = histogram[-2] < 0 and histogram[-1] > 0
            bearish_cross = histogram[-2] > 0 and histogram[-1] < 0
        else:
            bullish_cross = bearish_cross = False
        
        return {
            "macd": round(float(macd_line[-1]), 6),
            "signal": round(float(signal_line[-1]), 6),
            "histogram": round(float(histogram[-1]), 6),
            "trend": "BULLISH" if macd_line[-1] > signal_line[-1] else "BEARISH",
            "bullish_cross": bullish_cross,
            "bearish_cross": bearish_cross,
        }

    # ─── BOLLINGER BANDS ─────────────────────────────────────────────────────

    def bollinger_bands(self, period: int = 20, std_dev: float = 2.0) -> Dict:
        """Bollinger Bands"""
        if len(self.closes) < period:
            return {"upper": 0, "middle": 0, "lower": 0, "bandwidth": 0}
        
        sma = np.mean(self.closes[-period:])
        std = np.std(self.closes[-period:])
        upper = sma + std_dev * std
        lower = sma - std_dev * std
        
        return {
            "upper": round(float(upper), 8),
            "middle": round(float(sma), 8),
            "lower": round(float(lower), 8),
            "bandwidth": round(float((upper - lower) / sma * 100), 4),
            "position": "ABOVE" if self.closes[-1] > upper else "BELOW" if self.closes[-1] < lower else "INSIDE",
        }

    # ─── VOLUME ──────────────────────────────────────────────────────────────

    def volume_ratio(self, period: int = 20) -> float:
        """
        Razão volume atual / média do período
        > 1.5 = volume alto (confirmação de movimento)
        """
        if len(self.volumes) < period:
            return 1.0
        avg_vol = np.mean(self.volumes[-period:-1])
        current_vol = self.volumes[-1]
        if avg_vol == 0:
            return 1.0
        return round(float(current_vol / avg_vol), 2)

    def obv(self) -> float:
        """On-Balance Volume"""
        obv_val = 0.0
        for i in range(1, len(self.closes)):
            if self.closes[i] > self.closes[i - 1]:
                obv_val += self.volumes[i]
            elif self.closes[i] < self.closes[i - 1]:
                obv_val -= self.volumes[i]
        return round(obv_val, 2)

    # ─── SUPORTE E RESISTÊNCIA ────────────────────────────────────────────────

    def support_resistance(self, lookback: int = 50, tolerance: float = 0.002) -> Dict:
        """
        Detectar níveis de suporte e resistência usando pivots
        Retorna os níveis mais significativos
        """
        highs = self.highs[-lookback:]
        lows = self.lows[-lookback:]
        current = float(self.closes[-1])
        
        # Encontrar pivots locais
        resistances = []
        supports = []
        
        for i in range(2, len(highs) - 2):
            # Pivot high (resistência)
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                resistances.append(float(highs[i]))
            # Pivot low (suporte)
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                supports.append(float(lows[i]))
        
        # Agrupar níveis próximos
        resistances = self._cluster_levels(resistances, tolerance)
        supports = self._cluster_levels(supports, tolerance)
        
        # Mais próximo acima (resistência) e abaixo (suporte)
        nearest_resistance = min([r for r in resistances if r > current], default=current * 1.02)
        nearest_support = max([s for s in supports if s < current], default=current * 0.98)
        
        return {
            "support": round(nearest_support, 8),
            "resistance": round(nearest_resistance, 8),
            "all_supports": [round(s, 8) for s in sorted(supports)[-3:]],
            "all_resistances": [round(r, 8) for r in sorted(resistances)[:3]],
        }

    def _cluster_levels(self, levels: List[float], tolerance: float) -> List[float]:
        """Agrupar níveis próximos"""
        if not levels:
            return []
        levels = sorted(levels)
        clusters = [[levels[0]]]
        
        for level in levels[1:]:
            if abs(level - clusters[-1][-1]) / clusters[-1][-1] < tolerance:
                clusters[-1].append(level)
            else:
                clusters.append([level])
        
        return [np.mean(cluster) for cluster in clusters]

    # ─── TENDÊNCIA ───────────────────────────────────────────────────────────

    def market_trend(self, short_period: int = 9, long_period: int = 21) -> str:
        """
        Determinar tendência do mercado baseado nas EMAs
        """
        ema_short = self.ema(short_period)
        ema_long = self.ema(long_period)
        
        ema_short_prev = self.ema(short_period, data=self.closes[:-3])
        ema_long_prev = self.ema(long_period, data=self.closes[:-3])
        
        if ema_short > ema_long and ema_short_prev <= ema_long_prev:
            return "CROSSOVER_BULLISH"  # Cruzamento acabou de acontecer
        elif ema_short < ema_long and ema_short_prev >= ema_long_prev:
            return "CROSSOVER_BEARISH"
        elif ema_short > ema_long:
            return "BULLISH"
        elif ema_short < ema_long:
            return "BEARISH"
        else:
            return "SIDEWAYS"

    # ─── PRICE ACTION ────────────────────────────────────────────────────────

    def price_action_signals(self) -> Dict:
        """
        Detectar padrões de price action nas últimas velas:
        - Doji, Hammer, Engulfing, etc.
        """
        if len(self.candles) < 3:
            return {"pattern": "NONE", "bias": "NEUTRAL"}
        
        c = self.candles
        last = c[-1]
        prev = c[-2]
        prev2 = c[-3]
        
        body = abs(last.close - last.open)
        full_range = last.high - last.low
        upper_wick = last.high - max(last.close, last.open)
        lower_wick = min(last.close, last.open) - last.low
        
        if full_range == 0:
            return {"pattern": "NONE", "bias": "NEUTRAL"}
        
        # Doji
        if body / full_range < 0.1:
            return {"pattern": "DOJI", "bias": "REVERSAL"}
        
        # Hammer (suporte)
        if lower_wick > body * 2 and upper_wick < body * 0.5:
            return {"pattern": "HAMMER", "bias": "BULLISH"}
        
        # Shooting Star (resistência)
        if upper_wick > body * 2 and lower_wick < body * 0.5:
            return {"pattern": "SHOOTING_STAR", "bias": "BEARISH"}
        
        # Bullish Engulfing
        if (prev.close < prev.open and  # Vela anterior baixista
            last.close > last.open and  # Vela atual altista
            last.open < prev.close and
            last.close > prev.open):
            return {"pattern": "BULLISH_ENGULFING", "bias": "BULLISH"}
        
        # Bearish Engulfing
        if (prev.close > prev.open and
            last.close < last.open and
            last.open > prev.close and
            last.close < prev.open):
            return {"pattern": "BEARISH_ENGULFING", "bias": "BEARISH"}
        
        # Vela forte altista
        if last.close > last.open and body / full_range > 0.7:
            return {"pattern": "STRONG_BULL", "bias": "BULLISH"}
        
        # Vela forte baixista
        if last.close < last.open and body / full_range > 0.7:
            return {"pattern": "STRONG_BEAR", "bias": "BEARISH"}
        
        return {"pattern": "NONE", "bias": "NEUTRAL"}

    # ─── VOLATILIDADE ────────────────────────────────────────────────────────

    def atr(self, period: int = 14) -> float:
        """Average True Range — medida de volatilidade"""
        if len(self.candles) < period + 1:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(self.candles)):
            high = float(self.highs[i])
            low = float(self.lows[i])
            prev_close = float(self.closes[i - 1])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        
        atr_val = np.mean(true_ranges[-period:])
        return round(float(atr_val), 8)

    def volatility_pct(self, period: int = 20) -> float:
        """Volatilidade em % (desvio padrão dos retornos)"""
        if len(self.closes) < period:
            return 0.0
        returns = np.diff(self.closes[-period:]) / self.closes[-period:-1]
        return round(float(np.std(returns) * 100), 4)

    # ─── GERADOR DE SINAIS ────────────────────────────────────────────────────

    def generate_signals(self) -> List[Dict]:
        """
        Gerar sinais para backtest — percorre todos os candles
        """
        signals = []
        min_period = 30  # Mínimo de candles para calcular indicadores
        
        for i in range(min_period, len(self.candles)):
            # Subconjunto de dados até o candle atual (sem lookahead)
            subset = TechnicalAnalysis([{
                "time": c.time, "open": c.open, "high": c.high,
                "low": c.low, "close": c.close, "volume": c.volume
            } for c in self.candles[:i+1]])
            
            rsi_val = subset.rsi()
            macd_data = subset.macd()
            trend = subset.market_trend()
            vol_ratio = subset.volume_ratio()
            
            # ─── ESTRATÉGIA BASE ───────────────────────────────────────────
            # COMPRAR: EMA cross bullish + RSI saindo sobrevenda + volume alto
            buy_conditions = (
                trend in ["CROSSOVER_BULLISH", "BULLISH"] and
                rsi_val < 60 and rsi_val > 30 and
                vol_ratio > 1.2 and
                macd_data["trend"] == "BULLISH"
            )
            
            # VENDER: EMA cross bearish + RSI sobrecomprado
            sell_conditions = (
                trend in ["CROSSOVER_BEARISH", "BEARISH"] and
                (rsi_val > 65 or macd_data["bearish_cross"])
            )
            
            if buy_conditions:
                signals.append({
                    "index": i,
                    "time": self.candles[i].time,
                    "price": float(self.candles[i].close),
                    "action": "BUY",
                    "rsi": rsi_val,
                    "trend": trend,
                })
            elif sell_conditions:
                signals.append({
                    "index": i,
                    "time": self.candles[i].time,
                    "price": float(self.candles[i].close),
                    "action": "SELL",
                    "rsi": rsi_val,
                    "trend": trend,
                })
        
        return signals

    def full_analysis(self) -> Dict:
        """Análise completa para um par — usado pelo motor de IA"""
        rsi_val = self.rsi()
        macd_data = self.macd()
        sr = self.support_resistance()
        trend = self.market_trend()
        vol_ratio = self.volume_ratio()
        pa = self.price_action_signals()
        bb = self.bollinger_bands()
        atr_val = self.atr()
        
        return {
            "rsi": rsi_val,
            "macd": macd_data,
            "ema_9": self.ema(9),
            "ema_21": self.ema(21),
            "ema_50": self.ema(50),
            "volume_ratio": vol_ratio,
            "support": sr["support"],
            "resistance": sr["resistance"],
            "trend": trend,
            "price_action": pa,
            "bollinger": bb,
            "atr": atr_val,
            "volatility_pct": self.volatility_pct(),
            "current_price": float(self.closes[-1]),
        }

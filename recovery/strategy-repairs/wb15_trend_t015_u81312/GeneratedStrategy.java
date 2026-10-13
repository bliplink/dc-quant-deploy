package com.app.dc.generated.autogen.wb15_trend_t015_u81312.v2;

import java.math.BigDecimal;
import com.app.dc.fix.message.MarketDataSnapshotFullRefresh;
import com.app.dc.po.OCType;
import com.app.dc.po.Side;
import com.app.dc.po.Signal;
import com.app.dc.signal.IndicatorSymbol;
import com.app.dc.signal.LegacyLiveSignalAdapter;
import org.ta4j.core.BarSeries;

public class GeneratedStrategy extends LegacyLiveSignalAdapter {
  @Override
  public Signal onBars(MarketDataSnapshotFullRefresh newKline, IndicatorSymbol indicatorSymbol) {
    Signal signal = new Signal();
    int trendSmaPeriod = paramInt("trendSmaPeriod", 20);
    int pullbackSmaPeriod = paramInt("pullbackSmaPeriod", 10);
    int atrPeriod = paramInt("atrPeriod", 14);
    double atrStopMult = paramDouble("atrStopMult", 2.0);
    double atrTargetMult = paramDouble("atrTargetMult", 3.0);
    int trendWindow = paramInt("trendWindow", 8);
    int minDirectionalBars = paramInt("maxDirectionalBars", 6);
    double rangeThreshold = paramDouble("maxRangeRatio", 0.025);
    double minSlopeAtr = paramDouble("minSlopeAtr", 0.25);

    String symbol = newKline.getSecurityID();
    if (symbol == null || symbol.length() == 0) return signal;
    IndicatorSymbol.IndicatorVar indicatorVar = indicatorSymbol.getIndicator(symbol);
    if (indicatorVar == null || indicatorVar.series == null) return signal;
    BarSeries series = indicatorVar.series;
    int endIndex = series.getEndIndex();
    int minBars = Math.max(trendSmaPeriod + trendWindow + 2,
            Math.max(pullbackSmaPeriod + 2, atrPeriod + 2));
    if (series.getBarCount() < minBars || endIndex < minBars - 1) return signal;

    double currentClose = close(series, endIndex);
    double previousClose = close(series, endIndex - 1);
    double previousHigh = high(series, endIndex - 1);
    double previousLow = low(series, endIndex - 1);
    double slowSma = sma(series, endIndex, trendSmaPeriod);
    double oldSlowSma = sma(series, endIndex - trendWindow, trendSmaPeriod);
    double fastSmaPrevious = sma(series, endIndex - 1, pullbackSmaPeriod);
    double fastSmaCurrent = sma(series, endIndex, pullbackSmaPeriod);
    double atrCurrent = atr(series, endIndex, atrPeriod);
    if (atrCurrent <= 0.0) return signal;

    int direction = trendDirection(series, endIndex, trendWindow,
            minDirectionalBars, rangeThreshold, slowSma, oldSlowSma,
            atrCurrent, minSlopeAtr);
    boolean longReclaim = previousLow <= fastSmaPrevious
            && currentClose > fastSmaCurrent && currentClose > previousClose;
    boolean shortReclaim = previousHigh >= fastSmaPrevious
            && currentClose < fastSmaCurrent && currentClose < previousClose;

    if (direction > 0 && currentClose > slowSma && longReclaim) {
      fill(signal, newKline, symbol, Side.BUY, currentClose,
              currentClose - atrStopMult * atrCurrent,
              currentClose + atrTargetMult * atrCurrent);
    } else if (direction < 0 && currentClose < slowSma && shortReclaim) {
      fill(signal, newKline, symbol, Side.SELL, currentClose,
              currentClose + atrStopMult * atrCurrent,
              currentClose - atrTargetMult * atrCurrent);
    }
    return signal;
  }

  private void fill(Signal signal, MarketDataSnapshotFullRefresh kline, String symbol,
                    Side side, double price, double stop, double take) {
    if ((side == Side.BUY && (stop >= price || take <= price))
            || (side == Side.SELL && (stop <= price || take >= price || take <= 0.0))) return;
    signal.symbol = symbol;
    signal.text = kline.getInfo3();
    signal.side = side;
    signal.ocType = OCType.OPEN;
    signal.orderType = "LIMIT";
    signal.price = BigDecimal.valueOf(price);
    signal.stopPrice = BigDecimal.valueOf(stop);
    signal.takerPrice = BigDecimal.valueOf(take);
    signal.firstStep = BigDecimal.valueOf(paramDouble("firstStepPct", 0.6));
    signal.step = BigDecimal.valueOf(paramDouble("stepPct", 0.3));
    signal.underTriggerProfitPrice = BigDecimal.valueOf(paramDouble("fallbackTriggerPct", 0.8));
    signal.underTakerProfitPrice = BigDecimal.valueOf(paramDouble("fallbackTakePct", 0.5));
    signal.strategyName = "wb15_trend_t015_u81312";
  }

  private int trendDirection(BarSeries series, int endIndex, int trendWindow,
                             int minDirectionalBars, double rangeThreshold,
                             double slowSma, double oldSlowSma, double atrValue,
                             double minSlopeAtr) {
    int start = endIndex - trendWindow + 1;
    double highest = high(series, start);
    double lowest = low(series, start);
    int bullish = 0;
    int bearish = 0;
    for (int i = start; i <= endIndex; i++) {
      highest = Math.max(highest, high(series, i));
      lowest = Math.min(lowest, low(series, i));
      if (i > start) {
        if (close(series, i) > close(series, i - 1)) bullish++;
        else if (close(series, i) < close(series, i - 1)) bearish++;
      }
    }
    double rangeRatio = (highest - lowest) / close(series, endIndex);
    boolean strongMove = Math.max(bullish, bearish) >= minDirectionalBars
            || rangeRatio > rangeThreshold;
    if (!strongMove || Math.abs(slowSma - oldSlowSma) < atrValue * minSlopeAtr) return 0;
    if (slowSma > oldSlowSma && bullish > bearish) return 1;
    if (slowSma < oldSlowSma && bearish > bullish) return -1;
    return 0;
  }

  private double close(BarSeries s, int i) { return s.getBar(i).getClosePrice().doubleValue(); }
  private double high(BarSeries s, int i) { return s.getBar(i).getHighPrice().doubleValue(); }
  private double low(BarSeries s, int i) { return s.getBar(i).getLowPrice().doubleValue(); }
  private double sma(BarSeries s, int end, int period) {
    double sum = 0.0;
    for (int i = end - period + 1; i <= end; i++) sum += close(s, i);
    return sum / period;
  }
  private double atr(BarSeries s, int end, int period) {
    double sum = 0.0;
    for (int i = end - period + 1; i <= end; i++) {
      double previousClose = close(s, i - 1);
      sum += Math.max(high(s, i) - low(s, i),
              Math.max(Math.abs(high(s, i) - previousClose), Math.abs(low(s, i) - previousClose)));
    }
    return sum / period;
  }
}

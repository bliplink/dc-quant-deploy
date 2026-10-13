package com.app.dc.generated.autogen.lcr1_xrp_ran_33d9206a.v2;

import java.math.BigDecimal;
import com.app.dc.fix.message.MarketDataSnapshotFullRefresh;
import com.app.dc.po.OCType;
import com.app.dc.po.Side;
import com.app.dc.po.Signal;
import com.app.dc.signal.LegacyLiveSignalAdapter;
import com.app.dc.signal.IndicatorSymbol;
import org.ta4j.core.BarSeries;

public class GeneratedStrategy extends LegacyLiveSignalAdapter {
    @Override
    public Signal onBars(MarketDataSnapshotFullRefresh newKline, IndicatorSymbol indicatorSymbol) {
        Signal signal = new Signal();
        String symbol = newKline.getSecurityID();
        if (symbol == null || symbol.length() == 0) return signal;
        IndicatorSymbol.IndicatorVar indicatorVar = indicatorSymbol.getIndicator(symbol);
        if (indicatorVar == null || indicatorVar.series == null) return signal;
        BarSeries series = indicatorVar.series;
        int endIndex = series.getEndIndex();
        int meanPeriod = paramInt("meanPeriod", 96);
        int meanOffset = paramInt("meanOffset", 32);
        int boundaryLookback = paramInt("boundaryLookback", 48);
        int atrPeriod = paramInt("atrPeriod", 14);
        int minBars = Math.max(meanPeriod + meanOffset + 2,
                Math.max(boundaryLookback + 2, atrPeriod + 2));
        if (series.getBarCount() < minBars || endIndex < minBars - 1) return signal;

        double mean = sma(series, endIndex - 2, meanPeriod);
        double oldMean = sma(series, endIndex - 2 - meanOffset, meanPeriod);
        double boundaryHigh = highestHigh(series,
                endIndex - boundaryLookback - 1, endIndex - 2);
        double previousHigh = high(series, endIndex - 1);
        double previousLow = low(series, endIndex - 1);
        double previousClose = close(series, endIndex - 1);
        double currentClose = close(series, endIndex);
        double eventAtr = atr(series, endIndex - 1, atrPeriod);
        double minSweepAtr = paramDouble("minSweepAtr", 0.10);
        if (oldMean <= 0.0 || eventAtr <= 0.0
                || Math.abs(mean / oldMean - 1.0) > paramDouble("maxMeanDrift", 0.012)
                || previousHigh - boundaryHigh < eventAtr * minSweepAtr
                || previousClose >= boundaryHigh
                || currentClose >= previousLow) return signal;

        double atrValue = atr(series, endIndex, atrPeriod);
        double stopPriceValue = currentClose
                + atrValue * paramDouble("stopMultiplier", 2.0);
        double takerPriceValue = currentClose
                - atrValue * paramDouble("takeMultiplier", 4.0);
        if (atrValue <= 0.0 || stopPriceValue <= currentClose
                || takerPriceValue <= 0.0 || takerPriceValue >= currentClose) return signal;
        fill(signal, newKline, symbol, currentClose, stopPriceValue, takerPriceValue);
        return signal;
    }

    private void fill(Signal signal, MarketDataSnapshotFullRefresh kline, String symbol,
                      double price, double stop, double take) {
        signal.symbol = symbol;
        signal.text = kline.getInfo3();
        signal.side = Side.SELL;
        signal.ocType = OCType.OPEN;
        signal.orderType = "LIMIT";
        signal.price = BigDecimal.valueOf(price);
        signal.stopPrice = BigDecimal.valueOf(stop);
        signal.takerPrice = BigDecimal.valueOf(take);
        signal.firstStep = BigDecimal.valueOf(paramDouble("firstStepPct", 0.5));
        signal.step = BigDecimal.valueOf(paramDouble("stepPct", 0.2));
        signal.underTriggerProfitPrice = BigDecimal.valueOf(paramDouble("fallbackTriggerPct", 0.8));
        signal.underTakerProfitPrice = BigDecimal.valueOf(paramDouble("fallbackTakePct", 0.5));
        signal.strategyName = "lcr1_xrp_ran_33d9206a";
    }

    private double sma(BarSeries series, int index, int period) {
        double sum = 0.0;
        for (int i = index - period + 1; i <= index; i++) sum += close(series, i);
        return sum / period;
    }

    private double highestHigh(BarSeries series, int start, int end) {
        double value = Double.NEGATIVE_INFINITY;
        for (int i = start; i <= end; i++) value = Math.max(value, high(series, i));
        return value;
    }

    private double atr(BarSeries series, int index, int period) {
        double sum = 0.0;
        for (int i = index - period + 1; i <= index; i++) {
            double previousClose = close(series, i - 1);
            sum += Math.max(high(series, i) - low(series, i),
                    Math.max(Math.abs(high(series, i) - previousClose),
                            Math.abs(low(series, i) - previousClose)));
        }
        return sum / period;
    }

    private double close(BarSeries series, int index) { return series.getBar(index).getClosePrice().doubleValue(); }
    private double high(BarSeries series, int index) { return series.getBar(index).getHighPrice().doubleValue(); }
    private double low(BarSeries series, int index) { return series.getBar(index).getLowPrice().doubleValue(); }
}

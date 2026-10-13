package com.app.dc.generated.autogen.lcr1_xrp_tre_8b8eb3e3.v3;

import java.math.BigDecimal;
import com.app.dc.fix.message.MarketDataSnapshotFullRefresh;
import com.app.dc.po.OCType;
import com.app.dc.po.Side;
import com.app.dc.po.Signal;
import com.app.dc.signal.IndicatorSymbol;
import com.app.dc.signal.LegacyLiveSignalAdapter;
import org.ta4j.core.BarSeries;

/** Volume breakout followed by a confirmed retest within three bars. */
public class GeneratedStrategy extends LegacyLiveSignalAdapter {
    private static final int RETEST_WINDOW = 3;

    @Override
    public Signal onBars(MarketDataSnapshotFullRefresh newKline,
                         IndicatorSymbol indicatorSymbol) {
        Signal signal = new Signal();
        String symbol = newKline.getSecurityID();
        IndicatorSymbol.IndicatorVar indicatorVar = symbol == null
                ? null : indicatorSymbol.getIndicator(symbol);
        if (indicatorVar == null || indicatorVar.series == null) return signal;
        BarSeries series = indicatorVar.series;
        int endIndex = series.getEndIndex();
        int rangePeriod = paramInt("rangePeriod", 49);
        int trendPeriod = paramInt("trendPeriod", 120);
        int trendOffset = paramInt("trendOffset", 16);
        int volumePeriod = paramInt("volumePeriod", 32);
        int atrPeriod = paramInt("atrPeriod", 14);
        int minBars = Math.max(180, Math.max(trendPeriod + trendOffset + 3,
                Math.max(rangePeriod + RETEST_WINDOW + 2,
                        Math.max(volumePeriod + RETEST_WINDOW + 2, atrPeriod + 2))));
        if (series.getBarCount() < minBars || endIndex < minBars - 1) return signal;

        double slow = averageClose(series, endIndex - 1, trendPeriod);
        double oldSlow = averageClose(series, endIndex - 1 - trendOffset,
                trendPeriod);
        if (slow <= oldSlow) return signal;

        double referenceHigh = Double.NaN;
        for (int barsAgo = 1; barsAgo <= RETEST_WINDOW; barsAgo++) {
            int breakoutIndex = endIndex - barsAgo;
            double candidateHigh = highestHigh(series,
                    breakoutIndex - rangePeriod, breakoutIndex - 1);
            double averageVolume = averageVolume(series,
                    breakoutIndex - 1, volumePeriod);
            if (close(series, breakoutIndex) > candidateHigh
                    && averageVolume > 0.0
                    && volume(series, breakoutIndex) >= averageVolume
                    * paramDouble("minVolumeRatio", 1.15)) {
                referenceHigh = candidateHigh;
                break;
            }
        }
        if (Double.isNaN(referenceHigh)) return signal;

        double price = close(series, endIndex);
        double currentOpen = open(series, endIndex);
        double currentLow = low(series, endIndex);
        double atrValue = atr(series, endIndex, atrPeriod);
        boolean retest = currentLow <= referenceHigh + 0.25 * atrValue
                && price > referenceHigh
                && price > currentOpen;
        if (atrValue <= 0.0 || !retest) return signal;

        double stop = Math.max(referenceHigh - 0.25 * atrValue,
                price - atrValue * paramDouble("stopMultiplier", 2.0));
        double take = price + atrValue * paramDouble("takeMultiplier", 5.0);
        if (stop <= 0.0 || stop >= price || take <= price) return signal;

        signal.symbol = symbol;
        signal.text = newKline.getInfo3();
        signal.side = Side.BUY;
        signal.ocType = OCType.OPEN;
        signal.orderType = "LIMIT";
        signal.price = BigDecimal.valueOf(price);
        signal.stopPrice = BigDecimal.valueOf(stop);
        signal.takerPrice = BigDecimal.valueOf(take);
        signal.firstStep = BigDecimal.valueOf(paramDouble("firstStepPct", 0.5));
        signal.step = BigDecimal.valueOf(paramDouble("stepPct", 0.2));
        signal.underTriggerProfitPrice = BigDecimal.valueOf(
                paramDouble("fallbackTriggerPct", 0.8));
        signal.underTakerProfitPrice = BigDecimal.valueOf(
                paramDouble("fallbackTakePct", 0.5));
        signal.strategyName = "lcr1_xrp_tre_8b8eb3e3";
        return signal;
    }

    private double averageClose(BarSeries series, int end, int period) {
        double sum = 0.0;
        for (int i = end - period + 1; i <= end; i++) sum += close(series, i);
        return sum / period;
    }

    private double averageVolume(BarSeries series, int end, int period) {
        double sum = 0.0;
        for (int i = end - period + 1; i <= end; i++) sum += volume(series, i);
        return sum / period;
    }

    private double highestHigh(BarSeries series, int start, int end) {
        double value = Double.NEGATIVE_INFINITY;
        for (int i = start; i <= end; i++) value = Math.max(value, high(series, i));
        return value;
    }

    private double atr(BarSeries series, int end, int period) {
        double sum = 0.0;
        for (int i = end - period + 1; i <= end; i++) {
            double previous = close(series, i - 1);
            sum += Math.max(high(series, i) - low(series, i),
                    Math.max(Math.abs(high(series, i) - previous),
                            Math.abs(low(series, i) - previous)));
        }
        return sum / period;
    }

    private double open(BarSeries series, int index) {
        return series.getBar(index).getOpenPrice().doubleValue();
    }

    private double close(BarSeries series, int index) {
        return series.getBar(index).getClosePrice().doubleValue();
    }

    private double high(BarSeries series, int index) {
        return series.getBar(index).getHighPrice().doubleValue();
    }

    private double low(BarSeries series, int index) {
        return series.getBar(index).getLowPrice().doubleValue();
    }

    private double volume(BarSeries series, int index) {
        return series.getBar(index).getVolume().doubleValue();
    }
}

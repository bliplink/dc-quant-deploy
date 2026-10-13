package com.app.dc.generated.autogen.research_r27_btc_low_volatility_bollinger_range_reentry_short.v3;

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
        int shortAtrPeriod = paramInt("shortAtrPeriod", 14);
        int longAtrPeriod = paramInt("longAtrPeriod", 80);
        int bollingerPeriod = paramInt("bollingerPeriod", 32);
        int riskAtrPeriod = paramInt("riskAtrPeriod", 14);
        int meanOffset = paramInt("meanOffset", 16);
        int minBars = Math.max(130, Math.max(shortAtrPeriod + 3,
                Math.max(longAtrPeriod + 3,
                        Math.max(bollingerPeriod + meanOffset + 2, riskAtrPeriod + 2))));
        if (series.getBarCount() < minBars || endIndex < minBars - 1) return signal;

        double shortAtr = atr(series, endIndex - 2, shortAtrPeriod);
        double longAtr = atr(series, endIndex - 2, longAtrPeriod);
        double mean = sma(series, endIndex - 2, bollingerPeriod);
        double oldMean = sma(series, endIndex - 2 - meanOffset, bollingerPeriod);
        double deviation = standardDeviation(series, endIndex - 2, bollingerPeriod, mean);
        double previousClose = close(series, endIndex - 1);
        double previousLow = low(series, endIndex - 1);
        double currentClose = close(series, endIndex);
        if (longAtr <= 0.0
                || shortAtr / longAtr > paramDouble("maxAtrRatio", 0.85)
                || Math.abs(mean - oldMean) / longAtr > paramDouble("maxMeanSlopeAtr", 0.75)
                || deviation <= 0.0
                || previousClose <= mean + paramDouble("eventDeviation", 2.0) * deviation
                || currentClose >= mean + paramDouble("confirmationDeviation", 1.6) * deviation
                || currentClose >= previousLow) return signal;

        double atrValue = atr(series, endIndex, riskAtrPeriod);
        double stopPriceValue = currentClose
                + atrValue * paramDouble("stopMultiplier", 2.0);
        double takerPriceValue = currentClose
                - atrValue * paramDouble("takeMultiplier", 5.0);
        if (atrValue <= 0.0 || stopPriceValue <= currentClose
                || takerPriceValue <= 0.0 || takerPriceValue >= currentClose) return signal;
        signal.symbol = symbol;
        signal.text = newKline.getInfo3();
        signal.side = Side.SELL;
        signal.ocType = OCType.OPEN;
        signal.orderType = "LIMIT";
        signal.price = BigDecimal.valueOf(currentClose);
        signal.stopPrice = BigDecimal.valueOf(stopPriceValue);
        signal.takerPrice = BigDecimal.valueOf(takerPriceValue);
        signal.firstStep = BigDecimal.valueOf(paramDouble("firstStepPct", 0.5));
        signal.step = BigDecimal.valueOf(paramDouble("stepPct", 0.2));
        signal.underTriggerProfitPrice = BigDecimal.valueOf(paramDouble("fallbackTriggerPct", 0.8));
        signal.underTakerProfitPrice = BigDecimal.valueOf(paramDouble("fallbackTakePct", 0.5));
        signal.strategyName = "research_r27_btc_low_volatility_bollinger_range_reentry_short";
        return signal;
    }

    private double sma(BarSeries series, int end, int period) {
        double sum = 0.0;
        for (int i = end - period + 1; i <= end; i++) sum += close(series, i);
        return sum / period;
    }
    private double standardDeviation(BarSeries series, int end, int period, double mean) {
        double sum = 0.0;
        for (int i = end - period + 1; i <= end; i++) {
            double delta = close(series, i) - mean;
            sum += delta * delta;
        }
        return Math.sqrt(sum / period);
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
    private double close(BarSeries s, int i) { return s.getBar(i).getClosePrice().doubleValue(); }
    private double high(BarSeries s, int i) { return s.getBar(i).getHighPrice().doubleValue(); }
    private double low(BarSeries s, int i) { return s.getBar(i).getLowPrice().doubleValue(); }
}

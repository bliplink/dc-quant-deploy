package com.app.dc.generated.autogen.lcr1_xrp_bre_8842e444.v2;

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
        String symbol = newKline.getSecurityID();
        if (symbol == null || symbol.length() == 0) return signal;
        IndicatorSymbol.IndicatorVar indicatorVar = indicatorSymbol.getIndicator(symbol);
        if (indicatorVar == null || indicatorVar.series == null) return signal;
        BarSeries series = indicatorVar.series;
        int endIndex = series.getEndIndex();
        int atrPeriod = paramInt("atrPeriod", 14);
        int momentumPeriod = paramInt("momentumPeriod", 8);
        int minBars = Math.max(64, Math.max(atrPeriod, momentumPeriod) + 3);
        if (series.getBarCount() < minBars || endIndex < minBars - 1) return signal;

        double currentOpen = open(series, endIndex);
        double currentClose = close(series, endIndex);
        double previousOpen = open(series, endIndex - 1);
        double previousClose = close(series, endIndex - 1);
        double previousLow = low(series, endIndex - 1);
        double atrValue = atr(series, endIndex, atrPeriod);
        if (atrValue <= 0.0) return signal;
        double previousBody = previousClose - previousOpen;
        double cumulativeMove = previousClose - close(series, endIndex - 1 - momentumPeriod);
        double priorLow = lowestLow(series, endIndex - 1 - momentumPeriod, endIndex - 2);
        if (previousBody > -paramDouble("minBodyAtr", 0.35) * atrValue
                || cumulativeMove > -paramDouble("minMomentumAtr", 1.0) * atrValue
                || previousLow > priorLow
                || currentClose <= (previousOpen + previousClose) / 2.0
                || currentClose <= currentOpen) return signal;

        double stopPriceValue = currentClose
                - atrValue * paramDouble("stopMultiplier", 0.9);
        double takerPriceValue = currentClose
                + atrValue * paramDouble("takeMultiplier", 1.8);
        if (stopPriceValue <= 0.0 || stopPriceValue >= currentClose
                || takerPriceValue <= currentClose) return signal;
        signal.symbol = symbol;
        signal.text = newKline.getInfo3();
        signal.side = Side.BUY;
        signal.ocType = OCType.OPEN;
        signal.orderType = "LIMIT";
        signal.price = BigDecimal.valueOf(currentClose);
        signal.stopPrice = BigDecimal.valueOf(stopPriceValue);
        signal.takerPrice = BigDecimal.valueOf(takerPriceValue);
        signal.firstStep = BigDecimal.valueOf(paramDouble("firstStepPct", 0.5));
        signal.step = BigDecimal.valueOf(paramDouble("stepPct", 0.2));
        signal.underTriggerProfitPrice = BigDecimal.valueOf(paramDouble("fallbackTriggerPct", 0.8));
        signal.underTakerProfitPrice = BigDecimal.valueOf(paramDouble("fallbackTakePct", 0.5));
        signal.strategyName = "lcr1_xrp_bre_8842e444";
        return signal;
    }

    private double lowestLow(BarSeries s, int start, int end) {
        double value = Double.POSITIVE_INFINITY;
        for (int i = start; i <= end; i++) value = Math.min(value, low(s, i));
        return value;
    }
    private double atr(BarSeries s, int end, int period) {
        double value = 0.0;
        for (int i = end - period + 1; i <= end; i++) {
            double previous = close(s, i - 1);
            value += Math.max(high(s, i) - low(s, i),
                    Math.max(Math.abs(high(s, i) - previous), Math.abs(low(s, i) - previous)));
        }
        return value / period;
    }
    private double open(BarSeries s, int i) { return s.getBar(i).getOpenPrice().doubleValue(); }
    private double close(BarSeries s, int i) { return s.getBar(i).getClosePrice().doubleValue(); }
    private double high(BarSeries s, int i) { return s.getBar(i).getHighPrice().doubleValue(); }
    private double low(BarSeries s, int i) { return s.getBar(i).getLowPrice().doubleValue(); }
}

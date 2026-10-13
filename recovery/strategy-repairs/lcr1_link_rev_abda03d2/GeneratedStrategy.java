package com.app.dc.generated.autogen.lcr1_link_rev_abda03d2.v3;

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
        int momentumPeriod = paramInt("momentumPeriod", 4);
        int atrPeriod = paramInt("atrPeriod", 14);
        if (series.getBarCount() < 80 || endIndex < Math.max(32, momentumPeriod) + 1) return signal;

        double currentOpen = open(series, endIndex);
        double currentClose = close(series, endIndex);
        double previousClose = close(series, endIndex - 1);
        double atrValue = atr(series, endIndex, atrPeriod);
        double currentRange = high(series, endIndex) - low(series, endIndex);
        if (currentClose <= 0.0 || atrValue <= 0.0 || currentRange <= 0.0) return signal;
        double normalizedMomentum = (previousClose
                - close(series, endIndex - 1 - momentumPeriod)) / atrValue;
        double closeLocation = (currentClose - low(series, endIndex)) / currentRange;
        if (normalizedMomentum < paramDouble("minMomentumAtr", 0.55)
                || sma(series, endIndex - 1, 8) <= sma(series, endIndex - 1, 32)
                || currentClose >= previousClose
                || currentClose >= currentOpen
                || closeLocation > 0.40) return signal;

        double stopPriceValue = currentClose
                + atrValue * paramDouble("stopMultiplier", 2.0);
        double takerPriceValue = currentClose
                - atrValue * paramDouble("takeMultiplier", 4.0);
        if (stopPriceValue <= currentClose || takerPriceValue <= 0.0
                || takerPriceValue >= currentClose) return signal;
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
        signal.strategyName = "lcr1_link_rev_abda03d2";
        return signal;
    }

    private double sma(BarSeries s, int end, int period) {
        double value = 0.0;
        for (int i = end - period + 1; i <= end; i++) value += close(s, i);
        return value / period;
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

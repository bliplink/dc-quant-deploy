package com.app.dc.generated.autogen.lcr1_link_rev_99b035a4.v3;

import java.math.BigDecimal;
import com.app.dc.fix.message.MarketDataSnapshotFullRefresh;
import com.app.dc.po.OCType;
import com.app.dc.po.Side;
import com.app.dc.po.Signal;
import com.app.dc.signal.IndicatorSymbol;
import com.app.dc.signal.LegacyLiveSignalAdapter;
import org.ta4j.core.BarSeries;

/** Expanding bearish exhaustion reversal with explicit local-high context. */
public class GeneratedStrategy extends LegacyLiveSignalAdapter {
    @Override
    public Signal onBars(MarketDataSnapshotFullRefresh newKline,
                         IndicatorSymbol indicatorSymbol) {
        Signal signal = new Signal();
        String symbol = newKline.getSecurityID();
        if (symbol == null || symbol.isEmpty()) return signal;
        IndicatorSymbol.IndicatorVar indicatorVar = indicatorSymbol.getIndicator(symbol);
        if (indicatorVar == null || indicatorVar.series == null) return signal;
        BarSeries series = indicatorVar.series;
        int endIndex = series.getEndIndex();
        int atrPeriod = paramInt("atrPeriod", 14);
        int momentumPeriod = paramInt("momentumPeriod", 8);
        int minBars = Math.max(80, Math.max(atrPeriod, momentumPeriod) + 2);
        if (series.getBarCount() < minBars || endIndex < minBars - 1) return signal;

        double atrValue = atr(series, endIndex, atrPeriod);
        double previousOpen = open(series, endIndex - 1);
        double previousClose = close(series, endIndex - 1);
        double previousHigh = high(series, endIndex - 1);
        double previousBody = previousClose - previousOpen;
        double currentOpen = open(series, endIndex);
        double currentClose = close(series, endIndex);
        double currentRange = high(series, endIndex) - low(series, endIndex);
        double priorHigh = highestHigh(series, endIndex - momentumPeriod,
                endIndex - 2);

        boolean extendedImpulse = previousBody >= 0.45 * atrValue
                && previousClose > close(series, endIndex - momentumPeriod)
                && previousHigh >= priorHigh;
        boolean bearishConfirmation = currentClose < currentOpen
                && currentClose < (previousOpen + previousClose) / 2.0
                && (currentClose - low(series, endIndex)) / Math.max(currentRange, 1e-9)
                <= 0.40;
        if (atrValue <= 0.0 || !extendedImpulse || !bearishConfirmation) return signal;

        double stop = currentClose
                + atrValue * paramDouble("stopMultiplier", 2.0);
        double take = currentClose
                - atrValue * paramDouble("takeMultiplier", 4.0);
        if (stop <= currentClose || take <= 0.0 || take >= currentClose) return signal;

        signal.symbol = symbol;
        signal.text = newKline.getInfo3();
        signal.side = Side.SELL;
        signal.ocType = OCType.OPEN;
        signal.orderType = "LIMIT";
        signal.price = BigDecimal.valueOf(currentClose);
        signal.stopPrice = BigDecimal.valueOf(stop);
        signal.takerPrice = BigDecimal.valueOf(take);
        signal.firstStep = BigDecimal.valueOf(paramDouble("firstStepPct", 0.5));
        signal.step = BigDecimal.valueOf(paramDouble("stepPct", 0.2));
        signal.underTriggerProfitPrice = BigDecimal.valueOf(
                paramDouble("fallbackTriggerPct", 0.8));
        signal.underTakerProfitPrice = BigDecimal.valueOf(
                paramDouble("fallbackTakePct", 0.5));
        signal.strategyName = "lcr1_link_rev_99b035a4";
        return signal;
    }

    private double atr(BarSeries series, int end, int period) {
        double value = 0.0;
        for (int i = end - period + 1; i <= end; i++) {
            double previous = close(series, i - 1);
            value += Math.max(high(series, i) - low(series, i),
                    Math.max(Math.abs(high(series, i) - previous),
                            Math.abs(low(series, i) - previous)));
        }
        return value / period;
    }

    private double highestHigh(BarSeries series, int start, int end) {
        double value = Double.NEGATIVE_INFINITY;
        for (int i = start; i <= end; i++) value = Math.max(value, high(series, i));
        return value;
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
}

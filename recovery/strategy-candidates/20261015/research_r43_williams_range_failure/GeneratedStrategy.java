package com.app.dc.generated.autogen.research_r43_williams_range_failure.v1;

import java.math.BigDecimal;
import com.app.dc.fix.message.MarketDataSnapshotFullRefresh;
import com.app.dc.po.OCType;
import com.app.dc.po.Side;
import com.app.dc.po.Signal;
import com.app.dc.signal.IndicatorSymbol;
import com.app.dc.signal.LegacyLiveSignalAdapter;
import org.ta4j.core.BarSeries;

/** Frozen round24 Williams %R range failure: ADA long and XRP short, ATR 2/4. */
public class GeneratedStrategy extends LegacyLiveSignalAdapter {
    @Override
    public Signal onBars(MarketDataSnapshotFullRefresh newKline, IndicatorSymbol indicatorSymbol) {
        Signal signal = new Signal();
        String symbol = newKline.getSecurityID();
        boolean isLong = "ADAUSDT".equals(symbol);
        if (!isLong && !"XRPUSDT".equals(symbol)) return signal;
        IndicatorSymbol.IndicatorVar indicatorVar = indicatorSymbol.getIndicator(symbol);
        if (indicatorVar == null || indicatorVar.series == null) return signal;
        BarSeries series = indicatorVar.series;
        int end = series.getEndIndex();
        if (series.getBarCount() < 150 || end < series.getBeginIndex() + 149) return signal;

        double mean = smaClose(series, end - 2, 96);
        double oldMean = smaClose(series, end - 34, 96);
        if (oldMean <= 0 || Math.abs(mean / oldMean - 1.0) > 0.012) return signal;
        double older = williamsR(series, end - 2, 20);
        double previous = williamsR(series, end - 1, 20);
        double price = close(series, end);
        boolean matches = isLong
                ? older <= -95.0 && previous > older + 8.0 && price > high(series, end - 1)
                : older >= -5.0 && previous < older - 8.0 && price < low(series, end - 1);
        if (!matches) return signal;

        double atrValue = atr(series, end, 14);
        if (price <= 0 || atrValue <= 0) return signal;
        double stopMultiplier = paramDouble("stopMultiplier", 2.0);
        double takeMultiplier = paramDouble("takeMultiplier", 4.0);
        double stop = price + (isLong ? -1 : 1) * atrValue * stopMultiplier;
        double take = price + (isLong ? 1 : -1) * atrValue * takeMultiplier;
        if (stop <= 0 || take <= 0 || (isLong ? stop >= price || take <= price
                : stop <= price || take >= price)) return signal;
        signal.symbol = symbol;
        signal.text = newKline.getInfo3();
        signal.side = isLong ? Side.BUY : Side.SELL;
        signal.ocType = OCType.OPEN;
        signal.orderType = "LIMIT";
        signal.price = BigDecimal.valueOf(price);
        signal.stopPrice = BigDecimal.valueOf(stop);
        signal.takerPrice = BigDecimal.valueOf(take);
        signal.firstStep = BigDecimal.valueOf(paramDouble("firstStepPct", 0.5));
        signal.step = BigDecimal.valueOf(paramDouble("stepPct", 0.2));
        signal.underTriggerProfitPrice = BigDecimal.valueOf(paramDouble("fallbackTriggerPct", 0.8));
        signal.underTakerProfitPrice = BigDecimal.valueOf(paramDouble("fallbackTakePct", 0.5));
        signal.strategyName = isLong ? "research_r43_ada_williams_range_failure_long"
                : "research_r43_xrp_williams_range_failure_short";
        return signal;
    }

    private double smaClose(BarSeries series, int end, int period) {
        double sum = 0.0;
        for (int i = end - period + 1; i <= end; i++) sum += close(series, i);
        return sum / period;
    }

    private double williamsR(BarSeries series, int end, int period) {
        double highest = Double.NEGATIVE_INFINITY;
        double lowest = Double.POSITIVE_INFINITY;
        for (int i = end - period + 1; i <= end; i++) {
            highest = Math.max(highest, high(series, i));
            lowest = Math.min(lowest, low(series, i));
        }
        return highest <= lowest ? -50.0 : -100.0 * (highest - close(series, end)) / (highest - lowest);
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

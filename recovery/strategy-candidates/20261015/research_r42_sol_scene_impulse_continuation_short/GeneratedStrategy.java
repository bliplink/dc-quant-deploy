package com.app.dc.generated.autogen.research_r42_sol_scene_impulse_continuation_short.v1;

import java.math.BigDecimal;
import com.app.dc.fix.message.MarketDataSnapshotFullRefresh;
import com.app.dc.po.OCType;
import com.app.dc.po.Side;
import com.app.dc.po.Signal;
import com.app.dc.signal.IndicatorSymbol;
import com.app.dc.signal.LegacyLiveSignalAdapter;
import org.ta4j.core.BarSeries;

/** Frozen 15m trend-scene hypothesis: eight-bar bearish impulse and close near bar low. */
public class GeneratedStrategy extends LegacyLiveSignalAdapter {
    @Override
    public Signal onBars(MarketDataSnapshotFullRefresh newKline, IndicatorSymbol indicatorSymbol) {
        Signal signal = new Signal();
        String symbol = newKline.getSecurityID();
        IndicatorSymbol.IndicatorVar indicatorVar = symbol == null ? null : indicatorSymbol.getIndicator(symbol);
        if (indicatorVar == null || indicatorVar.series == null) return signal;
        BarSeries series = indicatorVar.series;
        int end = series.getEndIndex();
        if (series.getBarCount() < 80 || end < series.getBeginIndex() + 79) return signal;

        double price = close(series, end);
        double atrValue = atr(series, end, 14);
        if (price <= 0 || atrValue <= 0) return signal;
        double normalizedMomentum = (price - close(series, end - 8)) / atrValue;
        double fast = meanClose(series, end, 8);
        double slow = meanClose(series, end, 32);
        double range = high(series, end) - low(series, end);
        if (range <= 0) return signal;
        double closeLocation = (price - low(series, end)) / range;
        if (!(normalizedMomentum <= -0.55 && fast < slow && closeLocation <= 0.40)) return signal;

        double stop = price + atrValue * paramDouble("stopMultiplier", 2.0);
        double take = price - atrValue * paramDouble("takeMultiplier", 4.0);
        if (stop <= price || take <= 0 || take >= price) return signal;
        signal.symbol = symbol;
        signal.text = newKline.getInfo3();
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
        signal.strategyName = "research_r42_sol_scene_impulse_continuation_short";
        return signal;
    }

    private double meanClose(BarSeries series, int end, int period) {
        double sum = 0;
        for (int i = end - period + 1; i <= end; i++) sum += close(series, i);
        return sum / period;
    }

    private double atr(BarSeries series, int end, int period) {
        double sum = 0;
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

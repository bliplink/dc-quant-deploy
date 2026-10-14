package com.app.dc.generated.autogen.research_r41_ada_volume_weighted_channel_failure_short.v1;

import java.math.BigDecimal;
import com.app.dc.fix.message.MarketDataSnapshotFullRefresh;
import com.app.dc.po.OCType;
import com.app.dc.po.Side;
import com.app.dc.po.Signal;
import com.app.dc.signal.IndicatorSymbol;
import com.app.dc.signal.LegacyLiveSignalAdapter;
import org.ta4j.core.BarSeries;

/** Frozen validation hypothesis: VWMA80 channel failure, downside confirmation. */
public class GeneratedStrategy extends LegacyLiveSignalAdapter {
    @Override
    public Signal onBars(MarketDataSnapshotFullRefresh newKline, IndicatorSymbol indicatorSymbol) {
        Signal signal = new Signal();
        String symbol = newKline.getSecurityID();
        IndicatorSymbol.IndicatorVar indicatorVar = symbol == null ? null : indicatorSymbol.getIndicator(symbol);
        if (indicatorVar == null || indicatorVar.series == null) return signal;
        BarSeries series = indicatorVar.series;
        int end = series.getEndIndex();
        if (series.getBarCount() < 170 || end < series.getBeginIndex() + 169) return signal;

        double center = volumeWeightedClose(series, end - 2, 80);
        double oldCenter = volumeWeightedClose(series, end - 34, 80);
        double envelope = atr(series, end - 2, 32) * 1.8;
        if (oldCenter <= 0 || envelope <= 0 || Math.abs(center / oldCenter - 1.0) > 0.012) return signal;
        double previousHigh = high(series, end - 1);
        double previousClose = close(series, end - 1);
        double price = close(series, end);
        if (!(previousHigh > center + envelope && previousClose < center + envelope
                && price < low(series, end - 1) && price > center)) return signal;

        double atrValue = atr(series, end, 14);
        double stop = price + atrValue * paramDouble("stopMultiplier", 2.5);
        double take = price - atrValue * paramDouble("takeMultiplier", 6.0);
        if (atrValue <= 0 || stop <= price || take <= 0 || take >= price) return signal;
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
        signal.strategyName = "research_r41_ada_volume_weighted_channel_failure_short";
        return signal;
    }

    private double volumeWeightedClose(BarSeries series, int end, int period) {
        double weighted = 0;
        double volume = 0;
        for (int i = end - period + 1; i <= end; i++) {
            double barVolume = series.getBar(i).getVolume().doubleValue();
            weighted += close(series, i) * barVolume;
            volume += barVolume;
        }
        return volume <= 0 ? close(series, end) : weighted / volume;
    }

    private double atr(BarSeries series, int end, int period) {
        double sum = 0;
        for (int i = end - period + 1; i <= end; i++) {
            double previous = close(series, i - 1);
            sum += Math.max(high(series, i) - low(series, i),
                    Math.max(Math.abs(high(series, i) - previous), Math.abs(low(series, i) - previous)));
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

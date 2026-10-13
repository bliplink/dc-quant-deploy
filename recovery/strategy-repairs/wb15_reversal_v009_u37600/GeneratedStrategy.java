package com.app.dc.generated.autogen.wb15_reversal_v009_u37600.v2;

import java.math.BigDecimal;
import com.app.dc.fix.message.MarketDataSnapshotFullRefresh;
import com.app.dc.po.Side;
import com.app.dc.po.Signal;
import com.app.dc.signal.IndicatorSymbol;
import com.app.dc.signal.LegacyLiveSignalAdapter;
import org.ta4j.core.BarSeries;

/**
 * Repairs the original sweep calculation and admits canonical wick reclaims.
 *
 * <p>The v1 implementation measured sweep depth from the current close to the
 * swept extreme. That value includes the entire reclaim candle and therefore
 * rejected the strongest reclaims. It also required the sweep candle to close
 * outside the range, excluding the common wick-only liquidity sweep. This
 * version measures only the penetration beyond the range boundary and requires
 * directional confirmation from the reclaim candle.</p>
 */
public class GeneratedStrategy extends LegacyLiveSignalAdapter {
    private static final int SWEEP_LOOKBACK = 12;
    private static final double MAX_SWEEP_PCT = 0.012;
    private static final double MIN_RANGE_PCT = 0.012;
    private static final double STOP_BUFFER_PCT = 0.002;
    private static final double TAKE_PROFIT_PCT = 0.006;
    private static final double FIRST_STEP_PCT = 0.8;
    private static final double STEP_PCT = 0.3;
    private static final double FALLBACK_TRIGGER_PCT = 1.2;
    private static final double FALLBACK_TAKE_PCT = 0.5;

    @Override
    public Signal onBars(MarketDataSnapshotFullRefresh newKline,
                         IndicatorSymbol indicatorSymbol) {
        Signal signal = new Signal();
        int sweepLookback = paramInt("sweepLookback", SWEEP_LOOKBACK);
        double maxSweepPct = paramDouble("maxSweepPct", MAX_SWEEP_PCT);
        double minRangePct = paramDouble("minRangePct", MIN_RANGE_PCT);
        double stopBufferPct = paramDouble("stopBufferPct", STOP_BUFFER_PCT);
        double takeProfitPct = paramDouble("takeProfitPct", TAKE_PROFIT_PCT);

        String symbol = newKline.getSecurityID();
        if (symbol == null || symbol.isEmpty()) return signal;
        IndicatorSymbol.IndicatorVar indicatorVar = indicatorSymbol.getIndicator(symbol);
        if (indicatorVar == null || indicatorVar.series == null) return signal;
        BarSeries series = indicatorVar.series;
        int endIndex = series.getEndIndex();
        int minBars = sweepLookback + 2;
        if (series.getBarCount() < minBars || endIndex < minBars - 1) return signal;

        double currentOpen = open(series, endIndex);
        double currentClose = close(series, endIndex);
        double previousClose = close(series, endIndex - 1);
        double previousLow = low(series, endIndex - 1);
        double previousHigh = high(series, endIndex - 1);
        double referenceLow = lowestLow(series, endIndex - sweepLookback - 1,
                endIndex - 2);
        double referenceHigh = highestHigh(series, endIndex - sweepLookback - 1,
                endIndex - 2);
        double referenceMid = (referenceLow + referenceHigh) / 2.0;
        double rangeWidth = (referenceHigh - referenceLow) / currentClose;
        if (rangeWidth < minRangePct) return signal;

        double downsidePenetration = (referenceLow - previousLow) / currentClose;
        boolean sweptSupport = previousLow < referenceLow
                && downsidePenetration <= maxSweepPct;
        boolean bullishReclaim = currentClose > referenceLow
                && currentClose > previousClose
                && currentClose > currentOpen
                && currentClose < referenceMid;
        if (sweptSupport && bullishReclaim) {
            double stop = previousLow - currentClose * stopBufferPct;
            double take = Math.max(referenceMid,
                    currentClose * (1.0 + takeProfitPct));
            return fill(signal, newKline, symbol, Side.BUY, currentClose, stop, take);
        }

        double upsidePenetration = (previousHigh - referenceHigh) / currentClose;
        boolean sweptResistance = previousHigh > referenceHigh
                && upsidePenetration <= maxSweepPct;
        boolean bearishReclaim = currentClose < referenceHigh
                && currentClose < previousClose
                && currentClose < currentOpen
                && currentClose > referenceMid;
        if (sweptResistance && bearishReclaim) {
            double stop = previousHigh + currentClose * stopBufferPct;
            double take = Math.min(referenceMid,
                    currentClose * (1.0 - takeProfitPct));
            return fill(signal, newKline, symbol, Side.SELL, currentClose, stop, take);
        }
        return signal;
    }

    private Signal fill(Signal signal, MarketDataSnapshotFullRefresh kline,
                        String symbol, Side side, double price, double stop,
                        double take) {
        if (side == Side.BUY && (stop >= price || take <= price)) return signal;
        if (side == Side.SELL && (stop <= price || take >= price)) return signal;
        signal.symbol = symbol;
        signal.text = kline.getInfo3();
        signal.side = side;
        signal.ocType = com.app.dc.po.OCType.OPEN;
        signal.price = BigDecimal.valueOf(price);
        signal.stopPrice = BigDecimal.valueOf(stop);
        signal.takerPrice = BigDecimal.valueOf(take);
        signal.firstStep = BigDecimal.valueOf(paramDouble("firstStepPct", FIRST_STEP_PCT));
        signal.step = BigDecimal.valueOf(paramDouble("stepPct", STEP_PCT));
        signal.underTriggerProfitPrice = BigDecimal.valueOf(
                paramDouble("fallbackTriggerPct", FALLBACK_TRIGGER_PCT));
        signal.underTakerProfitPrice = BigDecimal.valueOf(
                paramDouble("fallbackTakePct", FALLBACK_TAKE_PCT));
        signal.strategyName = "wb15_reversal_v009_u37600";
        return signal;
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

    private double highestHigh(BarSeries series, int startIndex, int endIndex) {
        double highest = Double.NEGATIVE_INFINITY;
        for (int i = startIndex; i <= endIndex; i++) {
            highest = Math.max(highest, high(series, i));
        }
        return highest;
    }

    private double lowestLow(BarSeries series, int startIndex, int endIndex) {
        double lowest = Double.POSITIVE_INFINITY;
        for (int i = startIndex; i <= endIndex; i++) {
            lowest = Math.min(lowest, low(series, i));
        }
        return lowest;
    }
}

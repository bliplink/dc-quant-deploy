package com.app.dc.generated.autogen.research_r19_link_flat_channel_wick_reentry_short.v3;

import java.math.BigDecimal;
import com.app.dc.fix.message.MarketDataSnapshotFullRefresh;
import com.app.dc.po.OCType;
import com.app.dc.po.Side;
import com.app.dc.po.Signal;
import com.app.dc.signal.LegacyLiveSignalAdapter;
import com.app.dc.signal.IndicatorSymbol;
import org.ta4j.core.BarSeries;

/** Flat-channel wick rejection with a bearish low-close confirmation candle. */
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
        int regressionPeriod = paramInt("regressionPeriod", 96);
        int atrPeriod = paramInt("atrPeriod", 14);
        int minBars = Math.max(regressionPeriod + 3, atrPeriod + 2);
        if (series.getBarCount() < minBars || endIndex < minBars - 1) return signal;

        Regression channel = regression(series, endIndex - regressionPeriod - 1,
                regressionPeriod);
        double referenceClose = close(series, endIndex - 2);
        double normalizedMove = referenceClose <= 0.0
                ? Double.POSITIVE_INFINITY
                : Math.abs(channel.slope * regressionPeriod / referenceClose);
        double projectedCenter = channel.lastValue + channel.slope;
        double upper = projectedCenter
                + paramDouble("channelDeviation", 1.8) * channel.residualDeviation;
        double previousOpen = open(series, endIndex - 1);
        double previousClose = close(series, endIndex - 1);
        double previousHigh = high(series, endIndex - 1);
        double previousBody = Math.max(Math.abs(previousClose - previousOpen),
                previousClose * 0.0001);
        double upperWick = previousHigh - Math.max(previousOpen, previousClose);
        double currentOpen = open(series, endIndex);
        double currentClose = close(series, endIndex);
        double currentRange = high(series, endIndex) - low(series, endIndex);

        boolean wickRejection = previousHigh > upper
                && previousClose < upper
                && upperWick > previousBody;
        boolean bearishConfirmation = currentClose < currentOpen
                && currentClose < previousClose
                && (currentClose - low(series, endIndex))
                / Math.max(currentRange, 1e-9) <= 0.40;
        if (channel.residualDeviation <= 0.0
                || normalizedMove > paramDouble("maxNormalizedMove", 0.025)
                || !wickRejection || !bearishConfirmation) return signal;

        double atrValue = atr(series, endIndex, atrPeriod);
        double stop = currentClose
                + atrValue * paramDouble("stopMultiplier", 2.0);
        double take = currentClose
                - atrValue * paramDouble("takeMultiplier", 4.0);
        if (atrValue <= 0.0 || stop <= currentClose
                || take <= 0.0 || take >= currentClose) return signal;

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
        signal.strategyName = "research_r19_link_flat_channel_wick_reentry_short";
        return signal;
    }

    private Regression regression(BarSeries series, int start, int period) {
        double sumX = 0.0, sumY = 0.0, sumXY = 0.0, sumXX = 0.0;
        for (int i = 0; i < period; i++) {
            double value = close(series, start + i);
            sumX += i;
            sumY += value;
            sumXY += i * value;
            sumXX += i * i;
        }
        double denominator = period * sumXX - sumX * sumX;
        double slope = denominator == 0.0 ? 0.0
                : (period * sumXY - sumX * sumY) / denominator;
        double intercept = (sumY - slope * sumX) / period;
        double residualSquares = 0.0;
        for (int i = 0; i < period; i++) {
            double residual = close(series, start + i) - (intercept + slope * i);
            residualSquares += residual * residual;
        }
        return new Regression(intercept + slope * (period - 1), slope,
                Math.sqrt(residualSquares / period));
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

    private static final class Regression {
        private final double lastValue;
        private final double slope;
        private final double residualDeviation;

        private Regression(double lastValue, double slope, double residualDeviation) {
            this.lastValue = lastValue;
            this.slope = slope;
            this.residualDeviation = residualDeviation;
        }
    }
}

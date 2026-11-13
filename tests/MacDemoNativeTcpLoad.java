import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONArray;
import com.alibaba.fastjson2.JSONObject;
import com.gateway.connector.tcp.client.GateWayApi;
import com.gateway.connector.tcp.client.IMessage;
import com.gateway.connector.utils.Consts;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.LockSupport;

/** Test client using the deployed Robot's native GateWayApi and wire protocol. */
public final class MacDemoNativeTcpLoad {
    private final Object guard = new Object();
    private final Map<String, Map<String, Object>> orders = new LinkedHashMap<>();
    private final List<String> streamErrors = new ArrayList<>();
    private final JSONObject config;

    private MacDemoNativeTcpLoad(JSONObject config) {
        this.config = config;
    }

    private static double milliseconds(long nanos) {
        return Math.round(nanos / 1000.0) / 1000.0;
    }

    private void execution(Object payload) {
        if (payload instanceof JSONArray) {
            for (Object entry : (JSONArray) payload) execution(entry);
            return;
        }
        if (!(payload instanceof JSONObject)) return;
        JSONObject event = (JSONObject) payload;
        if (!"Trade".equals(event.getString("ExecType"))
                || !"Filled".equals(event.getString("OrdStatus"))
                || event.getString("ExecID") == null) return;
        long received = System.nanoTime();
        synchronized (guard) {
            Map<String, Object> row = orders.get(event.getString("ClOrdID"));
            if (row == null) return;
            if (!config.getString("location").equals(event.getString("Location"))
                    || new BigDecimal(config.getString("quantity")).compareTo(
                            event.getBigDecimal("LastQty")) != 0) {
                streamErrors.add("EXECUTION_IDENTITY_OR_QUANTITY_MISMATCH");
                return;
            }
            if (row.containsKey("execution_id")) {
                streamErrors.add("DUPLICATE_FINAL_EXECUTION");
                return;
            }
            row.put("execution_id", event.getString("ExecID"));
            row.put("received_ns", received);
            row.put("client_fill_ms", milliseconds(received - (Long) row.get("started_ns")));
            row.put("scheduled_fill_ms", milliseconds(received - (Long) row.get("scheduled_ns")));
            row.put("settlement_durability", event.getString("TradeSettlementDurability"));
            row.put("settlement_rpo_risk", event.getBoolean("TradeSettlementRpoRisk"));
            guard.notifyAll();
        }
    }

    private void submit(GateWayApi gateway, String clientId, long scheduled) {
        JSONObject content = new JSONObject();
        content.put("Location", config.getString("location"));
        content.put("UserID", config.getString("user_id"));
        content.put("SecurityID", config.getString("symbol"));
        content.put("MarketIndicator", "4");
        content.put("OCType", "OPEN");
        content.put("Side", "Buy");
        content.put("OrdType", "Limit");
        content.put("TimeInForce", "IOC");
        content.put("OrderQty", config.getString("quantity"));
        content.put("Price", config.getString("price"));
        content.put("ClOrdID", clientId);
        content.put("Terminal", "API");
        content.put("AlgoName", "cross");
        content.put("Demo", "0");
        String encoded = JSON.toJSONString(content);
        long started = System.nanoTime();
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("client_order_id", clientId);
        row.put("scheduled_ns", scheduled);
        row.put("started_ns", started);
        row.put("dispatch_delay_ms", milliseconds(started - scheduled));
        synchronized (guard) {
            orders.put(clientId, row);
        }
        String outcome = "NO_RESPONSE";
        String code = null;
        try {
            String routing = config.getString("location") + '\u001f' + "4" + '\u001f' + config.getString("symbol");
            String response = gateway.requestSyncWithKey(routing, "OrderSvr", "placeOrder", encoded, String.class, 8000L);
            if (response != null && !response.trim().isEmpty()) {
                code = JSON.parseObject(response).getString("code");
                outcome = "0".equals(code) ? "ACKNOWLEDGED" : "BUSINESS_REJECTED";
            }
        } catch (Exception error) {
            outcome = error.getClass().getSimpleName();
        }
        long finished = System.nanoTime();
        synchronized (guard) {
            row.put("outcome", outcome);
            row.put("error_code", "0".equals(code) ? null : code);
            row.put("ack_ms", milliseconds(finished - started));
        }
    }

    private Map<String, Object> run() throws Exception {
        GateWayApi gateway = new GateWayApi();
        ExecutorService clients = Executors.newFixedThreadPool(16);
        Semaphore available = new Semaphore(16);
        try {
            Consts.version = 2;
            gateway.setGzip(true);
            gateway.setLogOut(false);
            gateway.setReconnectFlag(false);
            Map<String, Object> metadata = new LinkedHashMap<>();
            metadata.put("clientType", "API");
            metadata.put("client_type", "API");
            metadata.put("Location", config.getString("location"));
            metadata.put("location", config.getString("location"));
            metadata.put("authType", "TOKEN");
            JSONObject login = JSON.parseObject(gateway.connect("127.0.0.1", config.getIntValue("port"),
                    config.getString("user_id"), config.getString("token"), false, 1, metadata));
            if (login == null || !"0".equals(login.getString("code")) || !gateway.isLogin())
                throw new IllegalStateException("Native TCP authentication failed");
            JSONObject identity = login.getJSONObject("data");
            if (identity == null || !config.getString("user_id").equals(identity.getString("user_id"))
                    || !config.getString("location").equals(identity.getString("location")))
                throw new IllegalStateException("Native TCP authenticated identity differs");
            String topic = "dc.order.trade." + config.getString("symbol") + ".*."
                    + config.getString("user_id") + "." + config.getString("location");
            if (!gateway.subscribe(topic, new IMessage<String>() {
                @Override public void onMessage(String ignored, String value) {
                    try {
                        execution(JSON.parse(value));
                    } catch (RuntimeException error) {
                        synchronized (guard) {
                            streamErrors.add(error.getClass().getSimpleName());
                        }
                    }
                }
            }, String.class)) throw new IllegalStateException("Native execution subscription failed");
            int seconds = config.getIntValue("seconds");
            double rate = config.getDoubleValue("rate");
            int planned = (int) (rate * seconds);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("from", Instant.now().toString());
            long begun = System.nanoTime();
            long end = begun + TimeUnit.SECONDS.toNanos(seconds);
            int dropped = 0;
            for (int index = 0; index < planned; index++) {
                long scheduled = begun + Math.round(index / rate * 1e9);
                while (System.nanoTime() < scheduled) LockSupport.parkNanos(scheduled - System.nanoTime());
                if (System.nanoTime() >= end || !available.tryAcquire()) {
                    dropped++;
                    continue;
                }
                final String clientId = "T554EXEC-" + config.getString("run") + "-" + index;
                clients.submit(() -> {
                    try { submit(gateway, clientId, scheduled); }
                    finally { available.release(); }
                });
            }
            clients.shutdown();
            if (!clients.awaitTermination(15, TimeUnit.SECONDS))
                throw new IllegalStateException("Native request pool exceeded bounded completion");
            while (System.nanoTime() < end) LockSupport.parkNanos(end - System.nanoTime());
            result.put("until", Instant.now().toString());
            result.put("offered_until", Instant.parse((String) result.get("from")).plusSeconds(seconds).toString());
            result.put("load_duration_seconds", (System.nanoTime() - begun) / 1e9);
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30);
            synchronized (guard) {
                while (System.nanoTime() < deadline && streamErrors.isEmpty()
                        && orders.values().stream().anyMatch(row -> !row.containsKey("execution_id"))) guard.wait(100);
                List<Map<String, Object>> measured = new ArrayList<>();
                for (Map<String, Object> row : orders.values()) measured.add(new LinkedHashMap<>(row));
                result.put("orders", measured);
                result.put("stream_errors", new ArrayList<>(streamErrors));
                result.put("fills_inside_offered_window", orders.values().stream()
                        .filter(row -> row.containsKey("received_ns") && (Long) row.get("received_ns") <= end).count());
            }
            result.put("planned_orders", planned);
            result.put("scheduler_drops", dropped);
            result.put("measurement_complete", true);
            return result;
        } finally {
            clients.shutdownNow();
            gateway.disconnect();
        }
    }

    private static void selfTest() {
        JSONObject config = JSON.parseObject("{\"location\":\"TEST01\",\"quantity\":\"0.001\"}");
        MacDemoNativeTcpLoad client = new MacDemoNativeTcpLoad(config);
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("started_ns", System.nanoTime());
        row.put("scheduled_ns", row.get("started_ns"));
        client.orders.put("test-order", row);
        JSONObject event = JSON.parseObject("{\"ExecType\":\"Trade\",\"OrdStatus\":\"Filled\","
                + "\"ExecID\":\"real-exec\",\"ClOrdID\":\"test-order\",\"Location\":\"TEST01\",\"LastQty\":\"0.001\"}");
        client.execution(JSON.parse("[{\"code\":0}]"));
        if (row.containsKey("execution_id")) throw new AssertionError("RPC reply counted as execution");
        client.execution(event);
        if (!"real-exec".equals(row.get("execution_id")) || (Double) row.get("client_fill_ms") < 0)
            throw new AssertionError("Native final execution timing missing");
        client.execution(event);
        if (!client.streamErrors.contains("DUPLICATE_FINAL_EXECUTION")) throw new AssertionError("Duplicate hidden");
        event.put("Location", "WRONG1");
        client.execution(event);
        if (!client.streamErrors.contains("EXECUTION_IDENTITY_OR_QUANTITY_MISMATCH"))
            throw new AssertionError("Wrong financial identity accepted");
        System.out.println("NATIVE_TCP_EXECUTION_OBSERVATION_SELF_TEST_PASS");
    }

    public static void main(String[] arguments) throws Exception {
        org.apache.log4j.Logger.getRootLogger().setLevel(org.apache.log4j.Level.OFF);
        if (arguments.length == 1 && "--self-test".equals(arguments[0])) {
            selfTest();
            return;
        }
        JSONObject input = JSON.parseObject(new BufferedReader(new InputStreamReader(System.in, "UTF-8")).readLine());
        try {
            System.out.println("T554_NATIVE_TCP_REPORT " + JSON.toJSONString(new MacDemoNativeTcpLoad(input).run()));
            System.exit(0);
        } catch (Exception error) {
            System.out.println("T554_NATIVE_TCP_FAILURE " + error.getClass().getSimpleName());
            System.exit(2);
        }
    }
}

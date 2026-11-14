import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONArray;
import com.alibaba.fastjson2.JSONObject;
import com.gateway.connector.tcp.client.GateWayApi;
import com.gateway.connector.utils.Consts;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/** Closed-loop native TCP counterpart of the existing HTTP order/cancel probe. */
public final class MacDemoNativeTcpOrderCancel {
    private final JSONObject config;
    private final GateWayApi gateway = new GateWayApi();
    private MacDemoNativeTcpOrderCancel(JSONObject config) { this.config = config; }
    private static double ms(long since) { return Math.round((System.nanoTime() - since) / 1000.0) / 1000.0; }

    private JSONObject content() {
        JSONObject value = new JSONObject();
        value.put("Location", config.getString("location"));
        value.put("UserID", config.getString("user_id"));
        value.put("SecurityID", config.getString("symbol"));
        value.put("MarketIndicator", "4");
        value.put("AlgoName", "cross");
        return value;
    }
    private static JSONObject successful(String raw) {
        JSONObject reply = raw == null ? null : JSON.parseObject(raw);
        if (reply == null || !"0".equals(reply.getString("code")))
            throw new IllegalStateException("NATIVE_REQUEST_NOT_ACKNOWLEDGED");
        return reply;
    }
    private JSONObject request(String method, JSONObject body) throws Exception {
        String key = config.getString("location") + '\u001f' + "4" + '\u001f' + config.getString("symbol");
        return successful(gateway.requestSyncWithKey(key, "OrderSvr", method, JSON.toJSONString(body), String.class, 8000L));
    }
    private static JSONObject own(JSONArray rows, String id) {
        if (rows == null) throw new IllegalStateException("NATIVE_ORDER_QUERY_MISSING_ARRAY");
        JSONObject found = null;
        for (Object entry : rows) {
            JSONObject row = (JSONObject) entry;
            if (id.equals(row.getString("ClOrdID"))) {
                if (found != null) throw new IllegalStateException("DUPLICATE_NATIVE_OPEN_ORDER");
                found = row;
            }
        }
        return found;
    }
    private String await(String id, boolean present) throws Exception {
        long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(30);
        while (System.nanoTime() < end) {
            JSONObject body = content();
            body.put("location", config.getString("location"));
            body.put("userid", config.getString("user_id"));
            body.put("securityid", config.getString("symbol"));
            body.put("marketIndicator", "4");
            body.put("maxOrderCount", 100);
            JSONObject row = own(request("queryOpenOrder", body).getJSONArray("data"), id);
            if (!present && row == null) return null;
            if (present && row != null && "New".equals(row.getString("OrdStatus"))) {
                if (!config.getString("location").equals(row.getString("Location"))
                        || !config.getString("user_id").equals(row.getString("UserID"))
                        || !config.getString("symbol").equals(row.getString("SecurityID")))
                    throw new IllegalStateException("NATIVE_ORDER_IDENTITY_MISMATCH");
                return row.getString("OrderID");
            }
            Thread.sleep(50);
        }
        throw new IllegalStateException("NATIVE_ORDER_STATE_TIMEOUT");
    }
    private void cancel(String id, String orderId) throws Exception {
        JSONObject body = content();body.put("ClOrdID", id);body.put("OrderID", orderId == null ? "" : orderId);
        request("cancelOrder", body);
    }
    private Map<String,Object> run() throws Exception {
        List<Map<String,Object>> orders = new ArrayList<>();
        Map<String,Object> report = new LinkedHashMap<>();
        Consts.version = 2;
        gateway.setGzip(true);gateway.setLogOut(false);gateway.setReconnectFlag(false);
        try {
            Map<String,Object> metadata = new LinkedHashMap<>();
            metadata.put("clientType", "API");metadata.put("client_type", "API");
            metadata.put("Location", config.getString("location"));metadata.put("location", config.getString("location"));
            metadata.put("authType", "TOKEN");
            JSONObject login = successful(gateway.connect("127.0.0.1", config.getIntValue("port"),
                    config.getString("user_id"), config.getString("token"), false, 1, metadata));
            JSONObject identity = login.getJSONObject("data");
            if (!gateway.isLogin() || identity == null
                    || !config.getString("location").equals(identity.getString("location"))
                    || !config.getString("user_id").equals(identity.getString("user_id")))
                throw new IllegalStateException("NATIVE_LOGIN_IDENTITY_MISMATCH");
            long target = config.getLongValue("start_at_epoch_ms");
            long delay = target - System.currentTimeMillis();
            if (delay < 0 || delay > 30000) throw new IllegalStateException("NATIVE_START_BARRIER_OUT_OF_RANGE");
            while (System.currentTimeMillis() < target) Thread.sleep(Math.max(1, Math.min(10, target - System.currentTimeMillis())));
            if (System.currentTimeMillis() - target > 250) throw new IllegalStateException("NATIVE_START_BARRIER_MISSED");
            report.put("actual_start", Instant.now().toString());
            long begun = System.nanoTime(), end = begun + TimeUnit.SECONDS.toNanos(config.getIntValue("seconds"));
            while (System.nanoTime() < end) {
                String id = config.getString("prefix") + "-" + orders.size();
                Map<String,Object> row = new LinkedHashMap<>();orders.add(row);
                row.put("client_order_id", id);row.put("location", config.getString("location"));
                row.put("user_id", config.getString("user_id"));row.put("passed", false);
                String orderId = null;
                try {
                    long start = System.nanoTime();
                    JSONObject body = content();
                    body.put("OCType", "OPEN");body.put("OrderQty", "0.001");body.put("OrdType", "Limit");
                    body.put("ClOrdID", id);body.put("Terminal", "API");body.put("Side", "Buy");
                    body.put("Price", config.getString("price"));body.put("TimeInForce", "GTC");
                    body.put("ReduceOnly", "false");body.put("Demo", "0");
                    request("placeOrder", body);row.put("place_ack_ms", ms(start));
                    orderId = await(id, true);row.put("order_id", orderId);row.put("place_new_ms", ms(start));
                    long cancelStart = System.nanoTime();cancel(id, orderId);row.put("cancel_ack_ms", ms(cancelStart));
                    await(id, false);row.put("cancel_absent_ms", ms(cancelStart));row.put("cycle_ms", ms(start));
                    row.put("passed", true);
                } catch (Exception failure) {
                    row.put("failure", failure.getClass().getSimpleName());
                    try { cancel(id, orderId);await(id, false);row.put("cleanup_confirmed", true); }
                    catch (Exception cleanup) { row.put("cleanup_failure", cleanup.getClass().getSimpleName()); }
                    break;
                }
            }
            report.put("orders", orders);report.put("elapsed_seconds", (System.nanoTime()-begun)/1e9);
            report.put("measurement_complete", true);return report;
        } finally { gateway.disconnect(); }
    }
    private static void selfTest() {
        for (String bad : new String[]{"{\"code\":7000}", "{\"data\":[]}", "null"}) {
            try { successful(bad);throw new AssertionError("Failed request counted as ACK"); }
            catch (IllegalStateException expected) { }
        }
        JSONArray rows = JSON.parseArray("[{\"ClOrdID\":\"a\",\"OrdStatus\":\"New\"}]");
        if (own(rows,"a")==null || own(rows,"b")!=null) throw new AssertionError("Wrong order selected");
        rows.add(rows.get(0));
        try { own(rows,"a");throw new AssertionError("Duplicate order accepted"); }
        catch (IllegalStateException expected) { }
        System.out.println("NATIVE_TCP_ORDER_CANCEL_OBSERVATION_SELF_TEST_PASS");
    }
    public static void main(String[] args) throws Exception {
        org.apache.log4j.Logger.getRootLogger().setLevel(org.apache.log4j.Level.OFF);
        if (args.length==1 && "--self-test".equals(args[0])) { selfTest();return; }
        JSONObject input=JSON.parseObject(new BufferedReader(new InputStreamReader(System.in,"UTF-8")).readLine());
        try {
            System.out.println("T554_NATIVE_TCP_REPORT "+JSON.toJSONString(new MacDemoNativeTcpOrderCancel(input).run()));
            System.exit(0);
        } catch(Exception failure) {
            System.out.println("T554_NATIVE_TCP_FAILURE "+failure.getClass().getSimpleName());System.exit(2);
        }
    }
}

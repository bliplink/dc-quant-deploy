import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONArray;
import com.alibaba.fastjson2.JSONObject;
import com.gateway.connector.tcp.client.GateWayApi;
import com.gateway.connector.tcp.client.IMessage;
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
    private final Object guard = new Object();
    private final Map<String,Map<String,Object>> observed = new LinkedHashMap<>();
    private final List<String> streamErrors = new ArrayList<>();
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
        return response(raw, false);
    }

    private static JSONObject response(String raw, boolean allowPlaceBusy) {
        JSONObject reply = raw == null ? null : JSON.parseObject(raw);
        if (reply == null) throw new IllegalStateException("NATIVE_RESPONSE_MISSING");
        String code = reply.getString("code");
        String id = reply.getString("info1");
        if (allowPlaceBusy && "429".equals(code) && "ORDER_BUSY_RETRYABLE".equals(reply.getString("msg"))
                && (id == null || id.isEmpty())) return reply;
        if (!"0".equals(code))
            throw new IllegalStateException(code != null && code.matches("[0-9]{1,9}")
                    ? "NATIVE_REQUEST_REJECTED_CODE_" + code : "NATIVE_REQUEST_REJECTED_UNKNOWN_CODE");
        return reply;
    }
    private JSONObject request(String method, JSONObject body) throws Exception {
        paceRequest();
        String key = config.getString("location") + '\u001f' + "4" + '\u001f' + config.getString("symbol");
        return response(gateway.requestSyncWithKey(key, "OrderSvr", method, JSON.toJSONString(body), String.class, 8000L),
                "placeOrder".equals(method));
    }
    private long nextRequest, pacedRequests, pacingWaitNanos;
    private static long requestInterval(double rate) {
        if (!Double.isFinite(rate) || rate <= 0 || rate > 100)
            throw new IllegalArgumentException("NATIVE_SESSION_REQUEST_RATE_INVALID");
        return (long)Math.ceil(1_000_000_000.0 / rate);
    }
    private void paceRequest() throws InterruptedException {
        double rate = config.containsKey("max_requests_per_second")
                ? config.getDoubleValue("max_requests_per_second") : 80.0;
        long interval = requestInterval(rate), before = System.nanoTime();
        while (System.nanoTime() < nextRequest) {
            if (Thread.currentThread().isInterrupted()) throw new InterruptedException();
            java.util.concurrent.locks.LockSupport.parkNanos(nextRequest-System.nanoTime());
        }
        long sent = System.nanoTime();
        pacingWaitNanos += sent-before; pacedRequests++;nextRequest=sent+interval;
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
    private String awaitQuery(String id, boolean present) throws Exception {
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
    private void observe(Object payload) {
        if (payload instanceof JSONArray) {
            for (Object row : (JSONArray) payload) observe(row);
            return;
        }
        if (!(payload instanceof JSONObject)) return;
        JSONObject event = (JSONObject) payload;
        long received = System.nanoTime();
        synchronized (guard) {
            Map<String,Object> row = observed.get(event.getString("ClOrdID"));
            if (row == null) return;
            if (row.containsKey("busy")) throw new IllegalStateException("NATIVE_STATUS_FOR_BUSY_ORDER");
            if (!config.getString("location").equals(event.getString("Location"))
                    || !config.getString("user_id").equals(event.getString("UserID"))
                    || !config.getString("symbol").equals(event.getString("SecurityID"))
                    || event.getString("OrderID") == null)
                throw new IllegalStateException("NATIVE_STATUS_IDENTITY_MISMATCH");
            String id = event.getString("OrderID"), status = event.getString("OrdStatus");
            if (row.containsKey("order_id") && !id.equals(row.get("order_id")))
                throw new IllegalStateException("NATIVE_STATUS_ORDER_ID_CHANGED");
            row.put("order_id", id);
            if ("New".equals(status)) {
                if (row.containsKey("cancel_received_ns"))
                    throw new IllegalStateException("NATIVE_NEW_AFTER_CANCELLED");
                if (!row.containsKey("new_received_ns")) row.put("new_received_ns", received);
            } else if ("Pending_Cancel".equals(status)) {
                if (!row.containsKey("new_received_ns") || row.containsKey("cancel_received_ns"))
                    throw new IllegalStateException("NATIVE_PENDING_CANCEL_OUT_OF_ORDER");
                if (!row.containsKey("pending_cancel_received_ns")) row.put("pending_cancel_received_ns", received);
            } else if ("Cancelled".equals(status) || "Canceled".equals(status)) {
                if (!row.containsKey("pending_cancel_received_ns"))
                    throw new IllegalStateException("NATIVE_CANCELLED_WITHOUT_PENDING_CANCEL");
                if (!row.containsKey("cancel_received_ns")) row.put("cancel_received_ns", received);
            } else if ("Rejected".equals(status) || "Filled".equals(status) || "Partially_Filled".equals(status)) {
                String kind = status.toUpperCase(java.util.Locale.ROOT);
                String reason = event.getString("OrdRejReason");
                if (reason != null && reason.matches("[0-9]{1,8}")) kind += "_CODE_" + reason;
                throw new IllegalStateException("NATIVE_UNEXPECTED_ORDER_" + kind);
            }
            guard.notifyAll();
        }
    }
    private long awaitStatus(Map<String,Object> row, String key) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30);
        synchronized (guard) {
            while (!row.containsKey(key) && streamErrors.isEmpty() && System.nanoTime() < deadline)
                guard.wait(50);
            if (!streamErrors.isEmpty()) throw new IllegalStateException("NATIVE_ORDER_STREAM_INVALID");
            if (!row.containsKey(key)) throw new IllegalStateException("NATIVE_ORDER_STATUS_TIMEOUT");
            return (Long) row.get(key);
        }
    }
    private static double between(long end, long start) {
        if (end < start) throw new IllegalStateException("NATIVE_STATUS_PRECEDES_REQUEST");
        return Math.round((end-start)/1000.0)/1000.0;
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
            String topic = "dc.order.status." + config.getString("symbol") + "."
                    + config.getString("user_id") + "." + config.getString("location");
            if (!gateway.subscribe(topic, new IMessage<String>() {
                public void onMessage(String ignored, String value) {
                    try { observe(JSON.parse(value)); }
                    catch (RuntimeException invalid) {
                        synchronized (guard) { streamErrors.add(safeReason(invalid));guard.notifyAll(); }
                    }
                }
            }, String.class)) throw new IllegalStateException("NATIVE_ORDER_STATUS_SUBSCRIPTION_FAILED");
            long target = config.getLongValue("start_at_epoch_ms");
            long delay = target - System.currentTimeMillis();
            if (delay < 0 || delay > 30000) throw new IllegalStateException("NATIVE_START_BARRIER_OUT_OF_RANGE");
            while (System.currentTimeMillis() < target) Thread.sleep(Math.max(1, Math.min(10, target - System.currentTimeMillis())));
            if (System.currentTimeMillis() - target > 250) throw new IllegalStateException("NATIVE_START_BARRIER_MISSED");
            report.put("actual_start", Instant.now().toString());
            long begun = System.nanoTime();
            long windowStart = begun - TimeUnit.MILLISECONDS.toNanos(System.currentTimeMillis() - target);
            long end = windowStart + TimeUnit.SECONDS.toNanos(config.getIntValue("seconds"));
            while (System.nanoTime() < end) {
                String id = config.getString("prefix") + "-" + orders.size();
                Map<String,Object> row = new LinkedHashMap<>();orders.add(row);
                row.put("client_order_id", id);row.put("location", config.getString("location"));
                row.put("user_id", config.getString("user_id"));row.put("passed", false);
                Map<String,Object> observation = new LinkedHashMap<>();
                synchronized (guard) { observed.put(id, observation); }
                String orderId = null;
                try {
                    long start = System.nanoTime();
                    JSONObject body = content();
                    body.put("OCType", "OPEN");body.put("OrderQty", "0.001");body.put("OrdType", "Limit");
                    body.put("ClOrdID", id);body.put("Terminal", "API");body.put("Side", "Buy");
                    body.put("Price", config.getString("price"));body.put("TimeInForce", "GTC");
                    body.put("ReduceOnly", "false");body.put("Demo", "0");
                    JSONObject placement = request("placeOrder", body);
                    if ("429".equals(placement.getString("code"))) {
                        row.put("outcome", "ORDER_BUSY_RETRYABLE");
                        row.put("busy_ms", ms(start));
                        synchronized (guard) {
                            if (!observation.isEmpty()) streamErrors.add("NATIVE_STATUS_FOR_BUSY_ORDER");
                            observation.put("busy", true);
                        }
                        continue;
                    }
                    row.put("place_ack_ms", ms(start));
                    long newAt = awaitStatus(observation, "new_received_ns");
                    synchronized (guard) { orderId = (String) observation.get("order_id"); }
                    row.put("order_id", orderId);
                    row.put("place_new_ms", between(newAt, start));
                    row.put("new_inside_window", newAt >= windowStart && newAt < end);
                    long cancelStart = System.nanoTime();cancel(id, orderId);row.put("cancel_ack_ms", ms(cancelStart));
                    long cancelledAt = awaitStatus(observation, "cancel_received_ns");
                    long pendingAt = awaitStatus(observation, "pending_cancel_received_ns");
                    row.put("cancel_pending_ms", between(pendingAt, cancelStart));
                    row.put("pending_to_terminal_ms", between(cancelledAt, pendingAt));
                    row.put("cancel_terminal_ms", between(cancelledAt, cancelStart));row.put("cycle_ms", ms(start));
                    row.put("cancel_inside_window", cancelledAt >= windowStart && cancelledAt < end);
                    row.put("passed", true);
                } catch (Exception failure) {
                    row.put("failure", failure.getClass().getSimpleName());
                    row.put("failure_reason", safeReason(failure));
                    try { cancel(id, orderId);awaitQuery(id, false);row.put("cleanup_confirmed", true); }
                    catch (Exception cleanup) { row.put("cleanup_failure", safeReason(cleanup)); }
                    break;
                }
            }
            synchronized (guard) {
                List<Map<String,Object>> copy = new ArrayList<>();
                for (Map<String,Object> row : orders) copy.add(new LinkedHashMap<>(row));
                report.put("orders", copy);report.put("stream_errors", new ArrayList<>(streamErrors));
            }
            report.put("elapsed_seconds", (System.nanoTime()-begun)/1e9);
            report.put("max_requests_per_second", config.containsKey("max_requests_per_second")
                    ? config.getDoubleValue("max_requests_per_second") : 80.0);
            report.put("paced_requests", pacedRequests);
            report.put("pacing_wait_ms", pacingWaitNanos/1_000_000.0);
            report.put("pacing_included_in_request_latency", true);
            report.put("measurement_complete", true);return report;
        } finally { gateway.disconnect(); }
    }
    // Retain our stable diagnostic codes without logging responses or sessions.
    private static String safeReason(Exception failure) {
        String reason = failure.getMessage();
        return reason != null && reason.matches("NATIVE_[A-Z0-9_]+")
                ? reason : failure.getClass().getSimpleName();
    }
    private static void selfTest() {
        if(requestInterval(80)!=12_500_000L)throw new AssertionError("Wrong session request budget");
        for(double rate:new double[]{0,-1,Double.NaN,Double.POSITIVE_INFINITY,101}){
            try{requestInterval(rate);throw new AssertionError("Invalid session budget accepted");}
            catch(IllegalArgumentException expected){}
        }
        try{successful("{\"code\":10003}");throw new AssertionError("Rate refusal counted as ACK");}
        catch(IllegalStateException expected){
            if(!"NATIVE_REQUEST_REJECTED_CODE_10003".equals(safeReason(expected)))
                throw new AssertionError("Safe numeric refusal code was discarded");
        }
        String busy = "{\"code\":429,\"msg\":\"ORDER_BUSY_RETRYABLE\"}";
        if (!"429".equals(response(busy,true).getString("code"))) throw new AssertionError("Place busy missing");
        try {response(busy,false);throw new AssertionError("Cancel busy accepted");}
        catch(IllegalStateException expected) {}
        try {response(busy.replace("}",",\"info1\":\"order-1\"}"),true);throw new AssertionError("Busy leaked ID");}
        catch(IllegalStateException expected) {}
        for (String bad : new String[]{"{\"code\":7000}", "{\"data\":[]}", "null"}) {
            try { successful(bad);throw new AssertionError("Failed request counted as ACK"); }
            catch (IllegalStateException expected) { }
        }
        JSONArray rows = JSON.parseArray("[{\"ClOrdID\":\"a\",\"OrdStatus\":\"New\"}]");
        if (own(rows,"a")==null || own(rows,"b")!=null) throw new AssertionError("Wrong order selected");
        rows.add(rows.get(0));
        try { own(rows,"a");throw new AssertionError("Duplicate order accepted"); }
        catch (IllegalStateException expected) { }
        MacDemoNativeTcpOrderCancel client = new MacDemoNativeTcpOrderCancel(JSON.parseObject(
                "{\"location\":\"TEST01\",\"user_id\":\"u1\",\"symbol\":\"BTC004USDT\"}"));
        Map<String,Object> observation = new LinkedHashMap<>();client.observed.put("a", observation);
        client.observe(JSON.parse("{\"code\":0}"));
        if (observation.containsKey("new_received_ns")) throw new AssertionError("RPC counted as New");
        JSONObject event = JSON.parseObject("{\"ClOrdID\":\"a\",\"OrderID\":\"1\",\"Location\":\"TEST01\","
                + "\"UserID\":\"u1\",\"SecurityID\":\"BTC004USDT\",\"OrdStatus\":\"New\"}");
        client.observe(event);
        if (!observation.containsKey("new_received_ns")) throw new AssertionError("New push not observed");
        event.put("OrdStatus", "Cancelled");
        try { client.observe(event);throw new AssertionError("Skipped Pending_Cancel accepted"); }
        catch (IllegalStateException expected) { }
        event.put("OrdStatus", "Pending_Cancel");client.observe(event);
        event.put("OrdStatus", "Cancelled");client.observe(event);
        event.put("OrdStatus", "Pending_Cancel");
        try { client.observe(event);throw new AssertionError("Late Pending_Cancel accepted"); }
        catch (IllegalStateException expected) { }
        if (!observation.containsKey("cancel_received_ns")) throw new AssertionError("Cancelled push not observed");
        event.put("OrdStatus", "New");
        try { client.observe(event);throw new AssertionError("New after cancellation accepted"); }
        catch (IllegalStateException expected) { }
        event.put("Location", "OTHER1");
        try { client.observe(event);throw new AssertionError("Wrong owner accepted"); }
        catch (IllegalStateException expected) { }
        // At80 requests/s, a300s window can retain12,000 complete two-command
        // cycles. Cover actual status observation plus the final copied
        // report/export under the generator's bounded heap.
        client.observed.clear();
        List<Map<String,Object>> retained=new ArrayList<>();
        for(int index=0;index<12000;index++){
            String id="memory-cancel-"+index;
            Map<String,Object> status=new LinkedHashMap<>();client.observed.put(id,status);
            JSONObject update=JSON.parseObject("{\"Location\":\"TEST01\",\"UserID\":\"u1\","
                    +"\"SecurityID\":\"BTC004USDT\",\"OrdStatus\":\"New\"}");
            update.put("ClOrdID",id);update.put("OrderID",String.valueOf(100000000L+index));
            client.observe(update);update.put("OrdStatus","Pending_Cancel");client.observe(update);
            update.put("OrdStatus","Cancelled");client.observe(update);
            if(!status.containsKey("new_received_ns") ||!status.containsKey("cancel_received_ns"))
                throw new AssertionError("Bounded client lost an actual terminal status");
            Map<String,Object> record=new LinkedHashMap<>();
            record.put("client_order_id",id);record.put("location","TEST01");record.put("user_id","u1");
            record.put("order_id",update.getString("OrderID"));record.put("passed",true);
            record.put("new_inside_window",true);record.put("cancel_inside_window",true);
            for(String field:new String[]{"place_ack_ms","place_new_ms","cancel_ack_ms","cancel_pending_ms","pending_to_terminal_ms","cancel_terminal_ms","cycle_ms"})
                record.put(field,1.0);
            retained.add(record);
        }
        List<Map<String,Object>> exported=new ArrayList<>();
        for(Map<String,Object> record:retained)exported.add(new LinkedHashMap<>(record));
        String complete=JSON.toJSONString(exported);
        if(exported.size()!=12000 ||!complete.contains("memory-cancel-11999"))
            throw new AssertionError("Bounded client truncated its final report");
        System.out.println("NATIVE_TCP_ORDER_CANCEL_OBSERVATION_SELF_TEST_PASS");
    }
    public static void main(String[] args) throws Exception {
        org.apache.log4j.Logger.getRootLogger().setLevel(org.apache.log4j.Level.OFF);
        if (args.length==1 && "--self-test".equals(args[0])) { selfTest();System.exit(0); }
        JSONObject input=JSON.parseObject(new BufferedReader(new InputStreamReader(System.in,"UTF-8")).readLine());
        try {
            System.out.println("T554_NATIVE_TCP_REPORT "+JSON.toJSONString(new MacDemoNativeTcpOrderCancel(input).run()));
            System.exit(0);
        } catch(Exception failure) {
            System.out.println("T554_NATIVE_TCP_FAILURE "+failure.getClass().getSimpleName());System.exit(2);
        }
    }
}

# Realtime and recovery

The GW carries public market and private account/order topics. The public contract covers initial depth images, ordered diffs, `updateId` gap detection, and reconnect/state-rebuild behavior. Broker private topics must remain scoped to customers authorized in the Broker's `location`.

Recommended sequence:

1. Perform signed HTTP API-key login and retain the returned `user_id`, `location`, `client_type`, and `sid` / `token`.
2. Connect to the GW realtime transport with those authoritative values and verify the identity returned by GW.
3. Subscribe to permitted public/private topics. Build local depth state from a snapshot plus ordered diffs; if a gap appears, fetch a new snapshot.
4. On session expiry or disconnect, sign in again, reconnect, resubscribe, and query open orders, balance, and positions before trusting local state.

Do **not** blindly resend `placeOrder`, `cancelOrder`, `cashIn`, or `cashOut` after an ambiguous disconnect; the server may already have accepted them. Reconcile orders by `ClOrdID` and cash by the relevant ledger identity first.

The external non-Java WebSocket URL, raw frame format, and heartbeat contract are not frozen for External GA. Do not reverse-engineer an internal gateway client and call that a stable public SDK. The [full Chinese Topic reference](/zh/openapi/WEBSOCKET_TOPICS_V1.zh-CN/) documents the currently verified gateway behavior and its limits.

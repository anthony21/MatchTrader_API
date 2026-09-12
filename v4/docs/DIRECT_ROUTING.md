# Direct bridge order flow

Start capture, select the connected broker account, save the bridge source, symbol
mapping and lot size in Copy Settings, then choose Live or Paper.

- Live submits each new matching accepted bridge order using the existing broker
  connection. Strategy signals use the same switch and their saved mapping.
- Paper records the formatted order request without contacting the broker.
- A cancellation in Live sends a cancel only for the exact mapped order still
  pending at the broker. It never closes a filled position.
- Edit and closed lifecycle messages are recorded without broker writes.
- Duplicate deliveries, snapshots, old events and uncertain attempts are never
  replayed. Restart returns to Paper.

Requests and broker replies appear in Raw Data. Native broker order IDs and
attempts remain in the trade journal so cancellation targets the original order.
TradingBox forwarding is a separate URL, Save and On/Off control.

No per-trade Send or additional source-arming switch is required.

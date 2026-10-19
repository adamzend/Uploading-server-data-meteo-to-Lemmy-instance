## v1.1.0 — Recovery and source freshness (2026-10-19)

### What changed and why
- Added bounded recovery after the initial fast Modbus retries (default: five extra attempts, 60 seconds apart). Temporary HMI/network outages no longer force waiting until the next hourly cycle when the station recovers within this window.
- Added optional, configurable source heartbeat verification. A responding HMI may still contain frozen sensor values; a successful Modbus reply alone is not evidence of fresh measurements.
- Added optional diagnostic register guards, checked against configured allowed values before accepting a heartbeat snapshot.
- Successful collection with heartbeat enabled requires observing a counter change during that collection. Counter wrap is supported. Unchanged temperature/humidity is valid when the source counter advances.
- Failed collection preserves the last good readings and their timestamp. The public post explains that they are historical, and cannot show green when heartbeat verification is required but missing.
- Status JSON now includes `error`, `heartbeat_enabled` and `freshness_verified`. Existing SQLite history and private configuration are retained.

### Upgrade and configuration
Back up the installation and database, update the program files, then run `python settings.py` and the tests. Do not replace an existing private config with the example. Existing configurations remain valid: heartbeat defaults to disabled and recovery defaults to five attempts with a 60-second delay.

Add `recovery: {"attempts": 5, "delay_seconds": 60}` to configure recovery; use zero attempts to disable it. Each recovery attempt performs one collection, including heartbeat verification if enabled.

To enable source freshness, add a `heartbeat` object like the one in config.example.json, set `enabled` to true and supply a zero-based 16-bit counter register `address`. The counter must originate from the measuring station and be forwarded by the HMI, rather than count HMI screen refreshes. `timeout_seconds` must exceed the normal source/HMI update interval; `poll_interval_seconds` controls checks. Optional `checks` contains objects such as `{"address": 101, "allowed_values": [1]}` (illustrative address only). All reads use the configured Modbus host, unit and FC03/FC04; no writes are performed.

The 70-second default heartbeat window is suitable for a counter forwarded every 30 seconds. Adapt it to your device. Diagnostic checks and the counter are separate Modbus reads, not an atomic snapshot. A heartbeat proves source activity, not the validity of every individual sensor; configure diagnostic guards for that purpose.

### Limits
This remains a scheduled publisher, not a continuous alarm monitor. A post changes only when a cycle publishes it. Recovery extends cycle duration; overlapping runs are prevented by existing locks. With heartbeat disabled, the post explicitly says source heartbeat is not checked. Enabling it rejects older status files without positive verification until the next successful collection.

### Validation
All 27 automated tests passed on Linux with Python 3.11. Tests cover signed measurements, fragmented Modbus replies, failed reads, recovery limits, counter changes/wrap/timeouts, diagnostic guards, compatibility and publication status. Tests use fixtures and mocked services, not live public posts.

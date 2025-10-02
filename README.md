# Raspberry Pi Real-Time CAN Decoder (DBC, config-driven)
## !! Currently only works on VCAN !!
A headless, per-frame **CAN decoder** for Raspberry Pi using SocketCAN + DBC.  
It reads from a configured CAN interface (e.g., `can0`), decodes each frame **as it arrives** using your DBC via `cantools`, and outputs **decoded data only** (no raw payload persisted) to a CSV file, the console, or both.

> Designed for MCP2515 (SPI) setups and SSH-only environments. No display required.

---

## Features

- **Config-driven** via YAML (`--config config.yaml`).
- **Decoded-only** logging (no raw data stored).
- **Selectable sinks**: CSV file (`to_file`) and/or console (`to_console`).
- **Two output formats**:
  - **Flat** (`decoded_flat: true`) → one row per message; signals in a compact JSON field.
  - **Tidy** (`decoded_flat: false`) → one row per signal.
- **XRCC/Battery addressing fallback**: tries **exact ID**, then a **masked command ID** (`cmd_id = id & 0xF80`) when appropriate.
- **Unknown handling**: log minimal `UNKNOWN` rows or **drop** them (`drop_unknown`).
- Periodic **flush** to limit data loss on power cuts (`flush_sec`).

---

## Repository layout

rpi_can_logger/
├─ live_parser.py              # Real-time, config-driven decoder (decoded only)
├─ config/
│  └─ config.yaml              # Your runtime configuration (edit this)
└─ README.md

````

(If you also keep a test transmitter like `send_fixed_dbc_message.py`, document it separately.)

---

## Requirements

- Python 3.9+
- Packages:
  ```bash
  python3 -m pip install --upgrade pip
  python3 -m pip install python-can cantools pyyaml
````

* SocketCAN enabled on the Pi (MCP2515 overlay + SPI enabled).

---

## Hardware notes (MCP2515 quick ref)

Raspberry Pi ↔ MCP2515 (TJA1050 transceiver):

```
Pi Header   Signal        MCP2515/TJA1050
#01         3V3           VCC (MCP2515)
#02         5V            VCC (TJA1050)
#06         GND           GND
#09         GND           CAN bus GND reference
#19         MOSI          SI
#21         MISO          SO
#23         SCLK          SCK/CLK
#24         CE0           CS
#32 (GPIO12)GPIO12        INT
```

Enable SPI & overlay (edit `/boot/config.txt` or `/boot/firmware/config.txt`):

```ini
dtparam=spi=on
dtoverlay=mcp2515,spi0-0,oscillator=16000000,interrupt=12
# (older alias)
# dtoverlay=mcp2515-can0,oscillator=16000000,spimaxfrequency=10000000,interrupt=12
```

---

## Bring up the CAN interface

```bash
sudo ip link set can0 down || true
sudo ip link set can0 up type can bitrate 500000
ip -details link show can0
```

(You can also automate this with a systemd pre-start or `subprocess` inside another wrapper if desired.)

---

## Configuration

Create/edit `config/config.yaml`:

```yaml
# ==== Required ====
dbc: "/home/pi/rpi_can_logger/config/ups_battery.dbc"

# ==== CAN ====
iface: "can0"

# ==== Sinks (choose one or both) ====
to_file: true
to_console: false

# ==== File options (used if to_file = true) ====
out_dir: "/media/usb/canlogs"
base_name: ""          # "" -> auto: canlog_YYYYMMDD_HHMMSS
flush_sec: 2.0         # CSV flush interval (seconds)

# ==== Formatting / policy ====
decoded_flat: true     # true: 1 row/message (signals JSON); false: 1 row/signal
drop_unknown: false    # true: skip frames not present in DBC
```

**Notes**

* `dbc` must point to a valid `.dbc` file. Absolute paths are safest.
* If `base_name` is `""`, the file name becomes `canlog_<timestamp>_decoded.csv`.

---

## Running the decoder

```bash
python3 live_parser.py --config config/config.yaml
```

### Optional CLI overrides (without editing YAML)

These override the corresponding YAML keys only when provided:

```bash
# Switch to console output only for a quick look
python3 live_parser.py --config config/config.yaml --to-console true --to-file false

# Use tidy rows (one line per signal)
python3 live_parser.py --config config/config.yaml --decoded-flat false

# Temporarily drop unknown IDs
python3 live_parser.py --config config/config.yaml --drop-unknown true

# Change interface/output folder just for this run
python3 live_parser.py --config config/config.yaml --iface can0 --out-dir /tmp/canlogs
```

Allowed truthy strings: `true/yes/y/1` and falsy: `false/no/n/0`.

---

## Output formats

### Flat (`decoded_flat: true`)

CSV header:

```
timestamp_iso, can_id_hex, message, xrcc, battery, signals_json, msg_comment
```

Example row:

```
2025-10-02T14:03:55, 0x5A1, BattStatus, 2, 3, {"Voltage":48.5,"Current":3.2,"SOC":76}, "<msg comment>"
```

### Tidy (`decoded_flat: false`)

CSV header:

```
timestamp_iso, can_id_hex, message, xrcc, battery, signal, value, signal_comment, msg_comment
```

Example rows (one per signal):

```
2025-10-02T14:03:55, 0x5A1, BattStatus, 2, 3, Voltage, 48.5, "V at pack bus", "<msg comment>"
2025-10-02T14:03:55, 0x5A1, BattStatus, 2, 3, Current, 3.2, "I (+ discharge)", "<msg comment>"
```

**Unknown frames**

* If `drop_unknown: false`, an `UNKNOWN` row is emitted **without raw bytes**.
* If `drop_unknown: true`, they’re skipped.

**Decode errors**

* Emitted as `DECODE_ERROR` rows with an error string (no raw payload).

---

## Behavior details

* The loop calls `bus.recv(timeout=1.0)`. If nothing arrives in 1s, it wakes to flush/housekeep and continues.
* Error frames (`is_error_frame`) are ignored.
* Flush interval (`flush_sec`) controls how often CSV buffers are flushed to reduce data loss risk.
  For stronger durability, you can add an optional `os.fsync()` after flush (trade-off: slower).

---

## License

Choose a license (e.g., MIT) and add a `LICENSE` file.

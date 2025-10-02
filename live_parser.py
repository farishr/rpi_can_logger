import argparse
import csv
import json
import signal
import sys
import time
from pathlib import Path
import can
import cantools
import yaml
from typing import Any, Dict, Tuple

# For clean exit from program:
STOP = False

def handle_signal(signum, frame):
    global STOP
    STOP = True

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

# Decoded File name generation
def make_decoded_path(out_dir: Path, base: str) -> Path:
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = base if base else f"canlog_{ts}"
    return out_dir / f"{base}.csv"

def open_decoded_csv(dec_path: Path, decoded_flat: bool):
    dec_f = dec_path.open("w", newline="")
    dec_w = csv.writer(dec_f)
    if decoded_flat:
        dec_w.writerow(["timestamp_iso", "can_id_hex", "message", "xrcc", "battery", "signals_json", "msg_comment"])
    else:
        dec_w.writerow(["timestamp_iso", "can_id_hex", "message", "xrcc", "battery", "signal", "value", "signal_comment", "msg_comment"])
    return dec_f, dec_w

def hex_id(msg_id: int) -> str:
    return f"0x{msg_id:X}"

def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r") as f:
        data = yaml.safe_load(f) or {}
    if "dbc" not in data or not data["dbc"]:
        print("[ERR] 'dbc' must be set in config.", file=sys.stderr)
        sys.exit(2)
    # Defaults (if missing)
    data.setdefault("iface", "vcan0")
    data.setdefault("to_file", False)
    data.setdefault("to_console", True)
    data.setdefault("out_dir", "./logs")
    data.setdefault("base_name", "")
    data.setdefault("flush_sec", 2.0)
    data.setdefault("decoded_flat", False)
    data.setdefault("drop_unknown", False)
    return data

def merge_overrides(cfg: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    """Allow optional CLI overrides on top of the file."""
    ov = dict(cfg)
    # Strings
    if args.iface: ov["iface"] = args.iface
    if args.out_dir: ov["out_dir"] = args.out_dir
    if args.base_name is not None: ov["base_name"] = args.base_name
    # Floats
    if args.flush_sec is not None: ov["flush_sec"] = float(args.flush_sec)
    # Bools (tri-state: None means 'don't override')
    if args.to_file is not None: ov["to_file"] = args.to_file
    if args.to_console is not None: ov["to_console"] = args.to_console
    if args.decoded_flat is not None: ov["decoded_flat"] = args.decoded_flat
    if args.drop_unknown is not None: ov["drop_unknown"] = args.drop_unknown
    # DBC (override path if passed)
    if args.dbc: ov["dbc"] = args.dbc
    return ov

def main():
    ap = argparse.ArgumentParser(description="Real-time per-frame CAN decoder with DBC (decoded-only, config-driven).")
    ap.add_argument("--config", required=True, help="Path to YAML config file")

    # Optional overrides (all are None by default; only applied if provided)
    ap.add_argument("--dbc", help="Override: DBC file path")
    ap.add_argument("--iface", help="Override: SocketCAN interface (e.g., can0)")
    ap.add_argument("--to-file", type=lambda s: s.lower() in ("1","true","yes","y"), help="Override: true/false")
    ap.add_argument("--to-console", type=lambda s: s.lower() in ("1","true","yes","y"), help="Override: true/false")
    ap.add_argument("--out-dir", help="Override: output directory")
    ap.add_argument("--base-name", help="Override: base file name ('' -> timestamped)")
    ap.add_argument("--flush-sec", type=float, help="Override: flush interval (seconds)")
    ap.add_argument("--decoded-flat", type=lambda s: s.lower() in ("1","true","yes","y"), help="Override: true/false")
    ap.add_argument("--drop-unknown", type=lambda s: s.lower() in ("1","true","yes","y"), help="Override: true/false")

    args = ap.parse_args()

    # Load + merge config
    cfg_path = Path(args.config)
    cfg = load_config(cfg_path)
    cfg = merge_overrides(cfg, args)

    if not cfg["to_file"] and not cfg["to_console"]:
        print("[WARN] Neither to_file nor to_console is enabled. Running decode dry-run (no output).", file=sys.stderr)


    # Load DBC
    db = cantools.database.load_file(cfg["dbc"])
    msgs_by_id = {m.frame_id: m for m in db.messages}
    print(f"[INFO] Loaded DBC with {len(msgs_by_id)} messages from: {cfg["dbc"]}")

    # Prepare sink(s)
    dec_f = dec_w = None
    if cfg["to_file"]:
        out_dir = Path(cfg["out_dir"]); out_dir.mkdir(parents=True, exist_ok=True)
        dec_path = make_decoded_path(out_dir, cfg["base_name"])          # Creating the the csv file to write into
        dec_f, dec_w = open_decoded_csv(dec_path, cfg["decoded_flat"])    
        print(f"[INFO] Writing DECODED to: {dec_path}")

    # Open CAN bus
    try:
        bus = can.interface.Bus(channel=cfg["iface"], interface="socketcan")
    except Exception as e:
        print(f"[ERR] Failed to open CAN interface '{cfg["iface"]}': {e}", file=sys.stderr)
        sys.exit(2)

    print(f"[INFO] CAN interface '{cfg["iface"]}' opened. Waiting for frames... (Ctrl+C to stop)")

    last_flush = time.monotonic()       # Getting the latest time

    def sink_decoded_row_flat(ts_iso, id_hex_str, msg_name, xrcc_num, batt_num, signals_dict, msg_comment):
        if cfg["to_file"]:
            dec_w.writerow([ts_iso, id_hex_str, msg_name, xrcc_num, batt_num,
                            json.dumps(signals_dict, separators=(",", ":")),
                            msg_comment])
        if cfg["to_console"]:
            print(f"{ts_iso} {id_hex_str} {msg_name} xrcc={xrcc_num} batt={batt_num} signals={signals_dict}")

    def sink_decoded_row_tidy(ts_iso, id_hex_str, msg_name, xrcc_num, batt_num, sig_name, value, sig_comment, msg_comment):
        if cfg["to_file"]:
            dec_w.writerow([ts_iso, id_hex_str, msg_name, xrcc_num, batt_num, sig_name, value, sig_comment, msg_comment])
        if cfg["to_console"]:
            suffix = f"  # {sig_comment}" if sig_comment else ""
            print(f"{ts_iso} {id_hex_str} {msg_name} xrcc={xrcc_num} batt={batt_num} {sig_name}={value}{suffix}")

    try:
        while not STOP:
            msg = bus.recv(timeout=1.0)
            now = time.monotonic()

            # Periodic flush (file sink only)
            if cfg["to_file"] and now - last_flush >= cfg["flush_sec"]:
                dec_f.flush()
                last_flush = now

            if msg is None:
                continue

            if getattr(msg, "is_error_frame", False):
                continue

            idhex = msg.arbitration_id
            id_hex_str = hex_id(idhex)
            data_bytes = bytes(msg.data)

            # Your addressing scheme
            batt_num = (idhex & 0x007)       # last 3 bits
            xrcc_num = ((idhex >> 3) & 0xF)  # bits 7..4
            cmd_id   = (idhex & 0xF80)       # fallback group
            ts_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(msg.timestamp))

            def emit_message(message_obj, decoded_dict):
                msg_name = message_obj.name
                msg_comment = getattr(message_obj, "comment", "") or ""
                if cfg["decoded_flat"]:
                    sink_decoded_row_flat(ts_iso, id_hex_str, msg_name, xrcc_num, batt_num, decoded_dict, msg_comment)
                else:
                    for sig in message_obj.signals:
                        if sig.name in decoded_dict:
                            val = decoded_dict[sig.name]
                            sig_comment = sig.comment or ""
                            sink_decoded_row_tidy(ts_iso, id_hex_str, msg_name, xrcc_num, batt_num,
                                                  sig.name, val, sig_comment, msg_comment)

            try:
                message_obj = msgs_by_id.get(idhex)
                if message_obj:
                    decoded = message_obj.decode(data_bytes, decode_choices=True, scaling=True)
                    emit_message(message_obj, decoded)
                else:
                    message_obj = msgs_by_id.get(cmd_id)
                    if message_obj:
                        decoded = message_obj.decode(data_bytes, decode_choices=True, scaling=True)
                        emit_message(message_obj, decoded)
                    else:
                        if not cfg["drop_unknown"]:
                            if cfg["decoded_flat"]:
                                sink_decoded_row_flat(ts_iso, id_hex_str, "UNKNOWN", xrcc_num, batt_num, {}, "")
                            else:
                                # Print a single tidy line marking unknown (no raw payload stored)
                                if cfg["to_console"]:
                                    print(f"{ts_iso} {id_hex_str} UNKNOWN xrcc={xrcc_num} batt={batt_num}")
                                if cfg["to_file"]:
                                    dec_w.writerow([ts_iso, id_hex_str, "UNKNOWN", xrcc_num, batt_num, "", "", "", ""])
            except Exception as e:
                # Emission for decode errors without raw leakage
                if cfg["decoded_flat"]:
                    if cfg["to_file"]:
                        dec_w.writerow([ts_iso, id_hex_str, "DECODE_ERROR", xrcc_num, batt_num,
                                        json.dumps({"error": str(e)}, separators=(",", ":")), ""])
                    if cfg["to_console"]:
                        print(f"{ts_iso} {id_hex_str} DECODE_ERROR xrcc={xrcc_num} batt={batt_num} error={e}")
                else:
                    if cfg["to_file"]:
                        dec_w.writerow([ts_iso, id_hex_str, "DECODE_ERROR", xrcc_num, batt_num, "error", str(e), "", ""])
                    if cfg["to_console"]:
                        print(f"{ts_iso} {id_hex_str} DECODE_ERROR xrcc={xrcc_num} batt={batt_num} error={e}")

            # Flush again after emission if interval elapsed during work
            if cfg["to_file"] and time.monotonic() - last_flush >= cfg["flush_sec"]:
                dec_f.flush()
                last_flush = time.monotonic()
    
    finally:
        try:
            if cfg["to_file"]:
                dec_f.flush(); dec_f.close()
        except Exception:
            pass
        try:
            bus.shutdown()
        except Exception:
            pass
        print("[INFO] Shutdown complete.")

if __name__ == "__main__":
    main()
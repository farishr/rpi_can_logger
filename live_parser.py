import argparse
import csv
import json
import signal
import sys
import time
from pathlib import Path
import can
import cantools

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


def main():
    ap = argparse.ArgumentParser(description="Real-time per-frame CAN decoder with DBC (decoded-only, selectable sinks).")
    ap.add_argument("--dbc", required=True, help="DBC file path")
    ap.add_argument("--iface", default="can0", help="SocketCAN interface (default: can0)")

    # Sink controls
    ap.add_argument("--to-file", action="store_true", help="Write decoded data to CSV")
    ap.add_argument("--to-console", action="store_true", help="Print decoded data to stdout")

    # File options
    ap.add_argument("--out-dir", default="./logs", help="Output directory (default: ./logs)")
    ap.add_argument("--base-name", default="", help="Base name for output file. If empty, use timestamped base.")
    ap.add_argument("--flush-sec", type=float, default=2.0, help="Flush interval for CSV (default: 2s)")

    # Formatting
    ap.add_argument("--decoded-flat", action="store_true",
                    help="One row per message with signals JSON. Default is tidy (one row per signal).")
    ap.add_argument("--drop-unknown", action="store_true",
                    help="If set, frames without a matching DBC entry are not written/printed.")

    args = ap.parse_args()

    if not args.to_file and not args.to_console:
        print("[WARN] Neither --to-file nor --to-console selected. Nothing will be emitted (decode-only dry run).", file=sys.stderr)


    # Load DBC
    db = cantools.database.load_file(args.dbc)
    msgs_by_id = {m.frame_id: m for m in db.messages}
    print(f"[INFO] Loaded DBC with {len(msgs_by_id)} messages from: {args.dbc}")

    # Prepare sink(s)
    dec_f = dec_w = None
    if args.to_file:
        out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
        dec_path = make_decoded_path(out_dir, args.base_name)          # Creating the the csv file to write into
        dec_f, dec_w = open_decoded_csv(dec_path, args.decoded_flat)    
        print(f"[INFO] Writing DECODED to: {dec_path}")

    # Open CAN bus
    try:
        bus = can.interface.Bus(channel=args.iface, interface="socketcan")
    except Exception as e:
        print(f"[ERR] Failed to open CAN interface '{args.iface}': {e}", file=sys.stderr)
        sys.exit(2)

    print(f"[INFO] CAN interface '{args.iface}' opened. Waiting for frames... (Ctrl+C to stop)")

    last_flush = time.monotonic()       # Getting the latest time

    def sink_decoded_row_flat(ts_iso, id_hex_str, msg_name, xrcc_num, batt_num, signals_dict, msg_comment):
        if args.to_file:
            dec_w.writerow([ts_iso, id_hex_str, msg_name, xrcc_num, batt_num,
                            json.dumps(signals_dict, separators=(",", ":")),
                            msg_comment])
        if args.to_console:
            print(f"{ts_iso} {id_hex_str} {msg_name} xrcc={xrcc_num} batt={batt_num} signals={signals_dict}")

    def sink_decoded_row_tidy(ts_iso, id_hex_str, msg_name, xrcc_num, batt_num, sig_name, value, sig_comment, msg_comment):
        if args.to_file:
            dec_w.writerow([ts_iso, id_hex_str, msg_name, xrcc_num, batt_num, sig_name, value, sig_comment, msg_comment])
        if args.to_console:
            suffix = f"  # {sig_comment}" if sig_comment else ""
            print(f"{ts_iso} {id_hex_str} {msg_name} xrcc={xrcc_num} batt={batt_num} {sig_name}={value}{suffix}")

    try:
        while not STOP:
            msg = bus.recv(timeout=1.0)
            now = time.monotonic()

            # Periodic flush (file sink only)
            if args.to_file and now - last_flush >= args.flush_sec:
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
                if args.decoded_flat:
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
                        if not args.drop_unknown:
                            if args.decoded_flat:
                                sink_decoded_row_flat(ts_iso, id_hex_str, "UNKNOWN", xrcc_num, batt_num, {}, "")
                            else:
                                # Print a single tidy line marking unknown (no raw payload stored)
                                if args.to_console:
                                    print(f"{ts_iso} {id_hex_str} UNKNOWN xrcc={xrcc_num} batt={batt_num}")
                                if args.to_file:
                                    dec_w.writerow([ts_iso, id_hex_str, "UNKNOWN", xrcc_num, batt_num, "", "", "", ""])
            except Exception as e:
                # Emission for decode errors without raw leakage
                if args.decoded_flat:
                    if args.to_file:
                        dec_w.writerow([ts_iso, id_hex_str, "DECODE_ERROR", xrcc_num, batt_num,
                                        json.dumps({"error": str(e)}, separators=(",", ":")), ""])
                    if args.to_console:
                        print(f"{ts_iso} {id_hex_str} DECODE_ERROR xrcc={xrcc_num} batt={batt_num} error={e}")
                else:
                    if args.to_file:
                        dec_w.writerow([ts_iso, id_hex_str, "DECODE_ERROR", xrcc_num, batt_num, "error", str(e), "", ""])
                    if args.to_console:
                        print(f"{ts_iso} {id_hex_str} DECODE_ERROR xrcc={xrcc_num} batt={batt_num} error={e}")

            # Flush again after emission if interval elapsed during work
            if args.to_file and time.monotonic() - last_flush >= args.flush_sec:
                dec_f.flush()
                last_flush = time.monotonic()
    
    finally:
        try:
            if args.to_file:
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
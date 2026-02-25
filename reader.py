#!/usr/bin/env python3
"""T-Mobilitat relay — DESFire EV2 + CIPURSE L"""
import httpx, json, sys

try:
    from t_mobilitat_gui import launch_gui

    HAS_GUI = True
except ImportError:
    HAS_GUI = False
from smartcard.System import readers
from protobuf_decoder.protobuf_decoder import Parser

URL = "https://motorcloud.atm.smarting.es:9032"
HDRS = {
    "user-agent": "grpc-java-okhttp/1.51.1",
    "content-type": "application/grpc",
    "te": "trailers",
    "system-version-access": "1",
    "grpc-accept-encoding": "gzip",
}

DESFIRE_NUMBERS = "85525bac2f6a1b77"
INFINEON_NUMBERS = "08e0db50173b6862"


# --- Protobuf / gRPC ---
def varint(n):
    out = []
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            break
    return bytes(out)


def pb(field, data):
    if isinstance(data, int):
        return varint(field << 3) + varint(data)
    if isinstance(data, str):
        data = data.encode()
    return varint(field << 3 | 2) + varint(len(data)) + data


def grpc(p):
    return b"\x00" + len(p).to_bytes(4, "big") + p


def pb_get(d, path):
    parts = [int(p) for p in path.split(".")]

    def walk(results, ps):
        if not ps:
            return []
        t, rest = ps[0], ps[1:]
        out = []
        for item in results:
            if item.get("field") != t:
                continue
            data = item.get("data")
            if not rest:
                out.append(data)
            elif isinstance(data, dict):
                out.extend(walk(data.get("results", []), rest))
        return out

    r = walk(d.get("results", []), parts)
    return r[0] if len(r) == 1 else r or None


def try_parse(resp, label=""):
    for skip in [1, 5, 2, 3, 4, 0]:
        try:
            p = Parser().parse(resp.hex()[skip * 2 :]).to_dict()
            num = pb_get(p, "3.2")
            if num is not None:
                return p, num
        except:
            continue
    print(f"  [!] parse failed for {label}")
    return None, None


# --- NFC ---
def apdu(conn, cmd):
    if isinstance(cmd, str):
        cmd = bytes.fromhex(cmd.replace(" ", ""))
    r, s1, s2 = conn.transmit(list(cmd))
    out = bytes(r + [s1, s2])
    print(f"  [>] {cmd.hex()}")
    print(f"  [<] {out.hex()}")
    return out


# --- API ---
def api(client, endpoint, payload):
    r = client.post(
        f"{URL}/{endpoint}", headers=HDRS, content=grpc(payload), timeout=10
    )
    r.raise_for_status()
    return r.content


def device_block(numbers, session_id=None):
    b = (
        pb(1, "70574c89ab71fd6d")
        + pb(2, bytes.fromhex(numbers))
        + pb(3, 1)
        + pb(4, "14")
        + pb(5, "hacked69")
        + pb(6, "moto 420")
    )
    if session_id:
        b += pb(11, pb(2, session_id) + pb(3, 1))
    b += pb(12, 1)
    return b


def sc_response(uuid, num, card_resp):
    return pb(1, uuid) + pb(2, pb(2, num) + pb(3, pb(1, card_resp)))


def detect_card_type(conn):
    """Probe card: SELECT DESFire AID, then confirm with GetVersion."""
    # Step 1: try DESFire app SELECT
    r, s1, s2 = conn.transmit(list(bytes.fromhex("00A4040007F053555341544D")))
    if s1 == 0x90 and s2 == 0x00:
        # Step 2: confirm — only real DESFire responds 91AF to GetVersion
        r2, s3, s4 = conn.transmit(list(bytes.fromhex("9060000000")))
        if s3 == 0x91 and s4 == 0xAF:
            print("[+] Probe: SELECT 9000 + GetVersion 91AF → DESFire")
            return "desfire"
        print(f"[+] Probe: SELECT 9000 but GetVersion {s3:02X}{s4:02X} → CIPURSE")
    else:
        print(f"[+] Probe: SELECT {s1:02X}{s2:02X} → CIPURSE")
    # Reset for CIPURSE
    conn.transmit(list(bytes.fromhex("00A40000020005")))
    return "cipurse"


def extract_cipurse_reads(rhex):
    """Extract all CIPURSE READ BINARY (04 B0) commands from server response."""
    cmds = []
    idx = 0
    while True:
        pos = rhex.find("04b0", idx)
        if pos == -1:
            break
        cmd_hex = rhex[pos : pos + 16]  # 8 bytes = 16 hex chars
        if len(cmd_hex) == 16:
            cmds.append(bytes.fromhex(cmd_hex))
        idx = pos + 16
    return cmds


def atr_to_ats(atr_hex):
    atr = bytes.fromhex(atr_hex)
    hist_len = atr[1] & 0x0F
    hist = atr[-(hist_len + 1) : -1]
    return bytes.fromhex("1078736000") + hist


def extract_json(r):
    raw = r.hex()
    idx = raw.find("7b22737573")
    if idx == -1:
        return None
    jb = bytes.fromhex(raw[idx:])
    return json.loads(jb[: jb.rfind(b"}") + 1])


def main():
    conn = readers()[0].createConnection()
    conn.connect()

    uid = apdu(conn, "FF CA 00 00 00")[:-2]
    atr = bytes(conn.getATR()).hex()
    card_type = detect_card_type(conn)
    ats = atr_to_ats(atr)

    print(f"\n[+] UID: {uid.hex()}")
    print(f"[+] ATR: {atr}")
    print(f"[+] Card type: {card_type.upper()}")
    if card_type == "desfire":
        print(f"[+] ATS: {ats.hex()}")
    print()

    with httpx.Client(http2=True, verify=False) as c:
        # 1. Open session
        print("[*] Opening session...")
        HDRS["session-id"] = "hello t-mobilitat"
        r = api(
            c,
            "DeviceContextService/openSession",
            pb(
                1,
                device_block(INFINEON_NUMBERS, "7cb43754-20a3-415e-92a8-2341391be515"),
            ),
        )
        sid = bytes.fromhex(r.hex()[18:90]).decode()
        HDRS["session-id"] = sid
        print(f"[+] Session: {sid}\n")

        # 2. Register card
        print("[*] Registering card...")
        card_numbers = DESFIRE_NUMBERS if card_type == "desfire" else INFINEON_NUMBERS
        card_info = pb(1, uid) + pb(2, ats) + pb(4, pb(1, 2) + pb(2, pb(1, 5)))
        r = api(
            c,
            "SmartcardService/executeDirectOperation",
            pb(1, device_block(card_numbers, sid)) + pb(2, 1) + pb(3, card_info),
        )
        p, num = try_parse(r, "register")
        uuid1 = pb_get(p, "1")
        print(f"[+] UUID: {uuid1}, Seq: {num}\n")

        # 3. Select app
        print("[*] Selecting application...")
        if card_type == "desfire":
            apdu(conn, "00 A4 04 00 07 F0 53 55 53 41 54 4D")
        else:
            apdu(conn, "00 A4 00 00 02 00 05")

        r = api(
            c,
            "SmartcardService/smartCardResponse",
            sc_response(uuid1, num, b"\x90\x00"),
        )
        p, num = try_parse(r, "select")

        # 4. Auth phase A
        print("\n[*] Auth phase A...")
        if card_type == "desfire":
            auth_a = apdu(conn, "90 71 00 00 08 03 06 00 00 00 00 00 00 00")
        else:
            auth_a = apdu(conn, "00 84 00 00 16")

        r = api(
            c, "SmartcardService/smartCardResponse", sc_response(uuid1, num, auth_a)
        )
        p, num = try_parse(r, "auth_a")

        # 5. Extract server auth command
        rhex = r.hex()
        if card_type == "desfire":
            idx = rhex.find("90af")
            if idx == -1:
                raise RuntimeError("No 90AF in server response")
            cmd = bytes.fromhex(rhex[idx : idx + 76])
        else:
            idx = rhex.find("008200")
            if idx == -1:
                raise RuntimeError("No MUTUAL AUTH (0082) in server response")
            cmd = bytes.fromhex(rhex[idx : idx + 88])

        # 6. Auth phase B
        print("\n[*] Auth phase B...")
        auth_b = apdu(conn, cmd)
        r = api(
            c, "SmartcardService/smartCardResponse", sc_response(uuid1, num, auth_b)
        )
        p, num = try_parse(r, "auth_b")

        if num is None:
            print("[!] Failed to get sequence after auth")
            print(f"[DEBUG] {r.hex()}")
            sys.exit(1)

        print(f"\n[+] ✓ Auth complete (seq={num})")

        # 7. Read files
        if card_type == "desfire":
            print("\n[*] Reading file 7 (256 bytes)...")
            f_a = apdu(conn, "90 AD 00 00 07 07 00 00 00 F8 00 00 00")
            f_b = apdu(conn, "90 AD 00 00 07 07 F8 00 00 08 00 00 00")
            file_data = f_a[:-2] + f_b[:-2]
            file_responses = [f_a, f_b]
            cipurse_files = []
        else:
            # Extract READ BINARY commands dynamically from server response
            read_cmds = extract_cipurse_reads(r.hex())
            if not read_cmds:
                raise RuntimeError("No CIPURSE READ BINARY commands in response")

            print(f"\n[*] Reading {len(read_cmds)} CIPURSE files...")
            file_responses = []
            cipurse_files = []
            for cmd in read_cmds:
                file_id = cmd[2]  # P1 = file ID
                resp = apdu(conn, cmd)
                file_responses.append(resp)
                cipurse_files.append((file_id, resp[:-2]))  # (id, data without SW)

        # 8. Send to server
        print("\n[*] Sending to server...")
        inner = pb(2, num)
        for resp in file_responses:
            inner += pb(3, pb(1, resp))
        payload = pb(1, uuid1) + pb(2, inner)
        r = api(c, "SmartcardService/smartCardResponse", payload)

        # 9. Parse JSON
        print("\n[*] Parsing response...")
        card_data = extract_json(r)
        if card_data:
            print(json.dumps(card_data, indent=2, ensure_ascii=False))
        else:
            print(f"[!] No JSON in response")
            print(f"[DEBUG] {r.hex()[:200]}")

        # 10. Print hex strings for decoder
        print(f"\n{'='*70}")
        print("  FILE DATA (copy to decoder)")
        print(f"{'='*70}")

        if card_type == "desfire":
            print(f"\n  File 7 ({len(file_data)} bytes):")
            print(f"  {file_data.hex()}\n")
        else:
            for file_id, fdata in cipurse_files:
                print(f"\n  File 0x{file_id:02X} ({len(fdata)} bytes):")
                print(f"  {fdata.hex()}")
            print()

        conn.disconnect()

    # 11. Launch GUI if available
    if card_data and HAS_GUI:
        print("[*] Launching GUI...")
        launch_gui(json.dumps(card_data, ensure_ascii=False))
    elif card_data and not HAS_GUI:
        print("[*] GUI not available (place t_mobilitat_gui.py alongside this script)")


if __name__ == "__main__":
    main()

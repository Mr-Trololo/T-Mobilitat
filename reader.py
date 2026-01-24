import httpx
from smartcard.System import readers
from smartcard.util import toHexString
from protobuf_decoder.protobuf_decoder import Parser
from typing import Any, List, Optional, Union

from t_mobilitat_gui import launch_gui


def int_to_varint(n: int) -> bytes:
    b = []
    while True:
        x = n & 0x7F
        n >>= 7
        b.append(x | 0x80 if n else x)
        if not n:
            break
    return bytes(b)


def varint_to_hex(n: int) -> str:
    return int_to_varint(n).hex()


def get_field_by_path(
    proto: dict, path: Union[str, List[int]]
) -> Optional[Union[Any, List[Any]]]:
    if isinstance(path, str):
        parts = [int(p) for p in path.split(".") if p != ""]
    else:
        parts = list(path)

    def find(results: List[dict], p: List[int]) -> List[Any]:
        if not p:
            return []
        target, rest = p[0], p[1:]
        out: List[Any] = []
        for item in results:
            if item.get("field") != target:
                continue
            data = item.get("data")
            if not rest:
                out.append(data)
            else:
                if isinstance(data, dict) and isinstance(data.get("results"), list):
                    out.extend(find(data["results"], rest))
                elif isinstance(data, list):
                    out.extend(find(data, rest))
        return out

    found = find(proto.get("results", []), parts)
    if not found:
        return None
    return found[0] if len(found) == 1 else found


class NFCSession:
    def __init__(self):
        self.reader = None
        self.connection = None
        self.connect()

    def connect(self):
        rlist = readers()
        if not rlist:
            raise RuntimeError("No NFC readers found.")
        self.reader = rlist[0]
        self.connection = self.reader.createConnection()
        self.connection.connect()
        print(f"[+] Connected to card via {self.reader}")

    def send_apdu(self, apdu: bytes) -> bytes:
        if not self.connection:
            raise RuntimeError("Not connected to a card.")
        apdu_list = list(apdu)
        response, sw1, sw2 = self.connection.transmit(apdu_list)
        print(f"[>] APDU sent: {toHexString(apdu_list)}")
        print(f"[<] Response: {toHexString(response)} SW: {sw1:02X} {sw2:02X}")
        return bytes(response + [sw1, sw2])

    def get_uid(self) -> str:
        resp = self.send_apdu(bytes.fromhex("FFCA000000"))
        uid_bytes = resp[:-2]
        return "".join(f"{b:02X}" for b in uid_bytes)

    def disconnect(self):
        if self.connection:
            self.connection.disconnect()
            print("[*] Disconnected from card.")

    def get_atr(self) -> str:
        # many pyscard CardConnection objects provide getATR()
        atr = bytes(self.connection.getATR())  # may raise if not supported
        print(f"[<] ATR: {atr.hex().upper()}")
        return atr.hex().upper()


def atr_to_ats(atr_hex: str) -> str:
    atr = bytes.fromhex(atr_hex)

    t0_byte = atr[1]
    num_historical_bytes = t0_byte & 0x0F

    # Extract historical bytes (last K bytes before TCK)
    hist_bytes = atr[-(num_historical_bytes + 1) : -1]

    # PC/SC discards the initial TL/T0 TB/TC from ATS
    # Reconstruct with known prefix for this card type
    prefix = bytes.fromhex("1078736000")

    ats = prefix + hist_bytes
    return ats.hex().upper()


def is_desfire_card(atr_hex: str, ats_hex: str) -> bool:
    """
    Detect if the card is a MIFARE DESFire card based on ATR and ATS.

    DESFire cards typically have:
    - ATS T0 byte (position 1) = 0x75 (DESFire D40) or 0x78 (DESFire EV1/EV2/EV3)
    - Historical bytes containing DESFire identifiers
    """
    atr = bytes.fromhex(atr_hex)
    ats = bytes.fromhex(ats_hex)

    # Check ATS T0 byte (second byte, position 1) for DESFire identifiers
    if len(ats) >= 2:
        t0_byte = ats[1]
        # 0x75 = DESFire D40
        # 0x78 = DESFire EV1/EV2/EV3
        if t0_byte == 0x75 or t0_byte == 0x78:
            return True

    # Check for DESFire identifier bytes anywhere in ATR/ATS
    if b"\x75" in atr or b"\x75" in ats:
        return True

    if b"\x78" in atr or b"\x78" in ats:
        return True

    return False


INFINEON_NUMBERS = "08e0db50173b6862"
DESFIRE_NUMBERS = "85525bac2f6a1b77"

INITIAL_COMMAND = bytes.fromhex(
    "00000000640a620a1037303537346338396162373166643664120808e0db50173b68621801220231342a086861636B6564363932086d6f746f203432305a28122437636234333735342d323061332d343135652d393261382d32333431333931626535313518016001"
)

BASE_HEADERS = {
    "user-agent": "grpc-java-okhttp/1.51.1",
    "content-type": "application/grpc",
    "te": "trailers",
    "system-version-access": "1",
    "grpc-accept-encoding": "gzip",
}

API_BASE_URL = "https://motorcloud.atm.smarting.es:9032"
API_TIMEOUT = 10.0


# --- Helper Functions ---
def send_post_request(
    client: httpx.Client, endpoint: str, headers: dict, content: bytes
) -> httpx.Response:
    url = f"{API_BASE_URL}/{endpoint}"
    response = client.post(url, headers=headers, content=content, timeout=API_TIMEOUT)
    response.raise_for_status()
    return response


def main():
    with httpx.Client(http2=True, verify=False) as client:
        # Step 1: Open session with the server
        print("[*] Opening session...")
        headers = BASE_HEADERS.copy()
        headers["session-id"] = "hello t-mobilitat"

        response = send_post_request(
            client, "DeviceContextService/openSession", headers, INITIAL_COMMAND
        )
        session_id = response.content.hex()[18:90]
        print(f"Session ID (hex): {session_id}")

        # Step 2: Connect to NFC card and get card info
        print("[*] Connecting to NFC card...")
        nfc_session = NFCSession()
        card_uid = nfc_session.get_uid()
        atr = nfc_session.get_atr()
        ats = atr_to_ats(atr)
        is_desfire = is_desfire_card(atr, ats)

        print(f"RATS: {ats}")
        print(f"Card UID: {card_uid}")
        if is_desfire:
            print("[*] Card type: MIFARE DESFire detected!")

        # Step 3: Execute direct operation
        print("[*] Executing direct operation...")
        card_numbers = DESFIRE_NUMBERS if is_desfire else INFINEON_NUMBERS
        command1_hex = (
            "000000008b0a620a10373035373463383961623731666436641208"
            + card_numbers
            + "1801220231342a086861636B6564363932086d6f746f203432305a281224"
            + session_id
            + "1801600110011a1b0a07"
            + card_uid
            + "1210"
            + ats
            + "2206080212020805"
        )

        headers["session-id"] = bytes.fromhex(session_id).decode("utf-8")
        response = send_post_request(
            client,
            "SmartcardService/executeDirectOperation",
            headers,
            bytes.fromhex(command1_hex),
        )

        # Parse response to extract UUID and num
        parsed_response = Parser().parse(response.content.hex()[2:])
        response_dict = parsed_response.to_dict()
        uuid1 = get_field_by_path(response_dict, "1")
        num = bytes.fromhex(varint_to_hex(get_field_by_path(response_dict, "3.2")))
        print(f"UUID1: {uuid1}, Num: {num.hex()}")

        # Step 4: First smartcard response
        print("[*] Sending first smartcard response...")
        cardresponse = (
            bytes.fromhex(f"00000000{(len(num)+47):02X}0a24")
            + uuid1.encode("latin1")
            + bytes.fromhex(f"12{(len(num)+7):02X}10")
            + num
            + bytes.fromhex("1a040a02")
            + bytes.fromhex("9000")
        )

        response = send_post_request(
            client, "SmartcardService/smartCardResponse", headers, cardresponse
        )
        parsed_response = Parser().parse(response.content.hex()[2:])
        num = bytes.fromhex(
            varint_to_hex(get_field_by_path(parsed_response.to_dict(), "3.2"))
        )
        print(f"Num (after server): {num.hex()}")

        # Step 5: Send APDU commands (select + authenticate A)
        print("[*] Authenticating with card (phase A)...")
        if is_desfire:
            nfc_session.send_apdu(b"\x00\xa4\x04\x00\x07\xf0\x53\x55\x53\x41\x54\x4d")
            resp_apdu = nfc_session.send_apdu(
                b"\x90\x71\x00\x00\x08\x03\x06\x00\x00\x00\x00\x00\x00\x00"
            )
        else:
            nfc_session.send_apdu(b"\x00\xa4\x00\x00\x02\x00\x05")
            resp_apdu = nfc_session.send_apdu(b"\x00\x84\x00\x00\x16")

        # Step 6: Second smartcard response with APDU result
        print("[*] Sending second smartcard response...")
        if is_desfire:
            cardresponse2 = (
                bytes.fromhex(f"00000000{(2+36+3+len(num)+4+18):02X}0a24")
                + uuid1.encode("latin1")
                + bytes.fromhex(f"12{(len(num)+23):02X}10")
                + num
                + bytes.fromhex("1a140a12")
                + resp_apdu
            )
        else:
            cardresponse2 = (
                bytes.fromhex(f"00000000{(2+36+3+len(num)+4+24):02X}0a24")
                + uuid1.encode("latin1")
                + bytes.fromhex(f"12{(len(num)+29):02X}10")
                + num
                + bytes.fromhex("1a1a0a18")
                + resp_apdu
            )

        response = send_post_request(
            client, "SmartcardService/smartCardResponse", headers, cardresponse2
        )
        print(f"[DEBUG] Response: {response.content.hex()[10:]}")

        # Step 7: Parse response and execute authenticate B
        print("[*] Authenticating with card (phase B)...")
        parsed_response = Parser().parse(response.content.hex()[10:])
        num = bytes.fromhex(
            varint_to_hex(get_field_by_path(parsed_response.to_dict(), "3.2"))
        )

        # Extract embedded command from server response
        response_hex = response.content.hex()
        if is_desfire:
            start = response_hex.find("90af")
            command_hex = response_hex[start : start + 76]
        else:
            start = response_hex.find("00820001")
            if start == -1 or len(response_hex) < start + 88:
                raise RuntimeError("No valid command sequence found in response")
            command_hex = response_hex[start : start + 88]

        command_apdu = bytes.fromhex(command_hex)
        print(f"[DEBUG] Command to card: {command_apdu.hex()}")
        auth_b_response = nfc_session.send_apdu(command_apdu)

        # Step 8: Third smartcard response with authentication B result
        print("[*] Sending third smartcard response...")
        if is_desfire:
            cardresponse3 = (
                bytes.fromhex(f"00000000{(2+36+3+len(num)+4+34):02X}0a24")
                + uuid1.encode("latin1")
                + bytes.fromhex(f"12{(1+len(num)+4+34):02X}10")
                + num
                + bytes.fromhex("1a240a22")
                + auth_b_response
            )
        else:
            cardresponse3 = (
                bytes.fromhex(f"00000000{(2+36+3+len(num)+4+18):02X}0a24")
                + uuid1.encode("latin1")
                + bytes.fromhex(f"12{(len(num)+23):02X}10")
                + num
                + bytes.fromhex("1a140a12")
                + auth_b_response
            )

        response = send_post_request(
            client, "SmartcardService/smartCardResponse", headers, cardresponse3
        )

        # Step 9: Read files from card
        print("[*] Reading card data files...")
        if is_desfire:
            file_data_1 = nfc_session.send_apdu(
                bytes.fromhex("90ad00000707000000f8000000")
            )
            file_data_2 = nfc_session.send_apdu(
                bytes.fromhex("90ad00000707f8000008000000")
            )
        else:
            file_data_1 = nfc_session.send_apdu(bytes.fromhex("04b0930002019000"))
            file_data_2 = nfc_session.send_apdu(bytes.fromhex("04b0940002019000"))

        # Parse final num from previous response
        parsed_response = Parser().parse(response.content.hex()[10:])
        final_num = bytes.fromhex(
            varint_to_hex(get_field_by_path(parsed_response.to_dict(), "3.2"))
        )
        print(f"[DEBUG] Final num: {final_num.hex()}")

        # Step 10: Final smartcard response with file data
        print("[*] Sending final smartcard response...")
        if is_desfire:
            body = (
                bytes.fromhex("0A24")
                + uuid1.encode("latin1")
                + bytes.fromhex("12")
                + int_to_varint(len(final_num) + 271)
                + bytes.fromhex("10")
                + final_num
                + bytes.fromhex("1Afd010Afa01")
                + file_data_1
                + bytes.fromhex("1A0c0a0a")
                + file_data_2
            )
        else:
            body = (
                bytes.fromhex("0A24")
                + uuid1.encode("latin1")
                + bytes.fromhex("12")
                + int_to_varint(len(final_num) + 305)
                + bytes.fromhex("10")
                + final_num
                + bytes.fromhex("1A95010A9201")
                + file_data_1
                + bytes.fromhex("1A95010A9201")
                + file_data_2
            )

        cardresponse4 = b"\x00" + len(body).to_bytes(4, "big") + body
        response = send_post_request(
            client, "SmartcardService/smartCardResponse", headers, cardresponse4
        )

        # Step 11: Parse and display card data
        print("[*] Parsing card data...")
        print(f"[DEBUG] Raw card data: {response.content.hex()}")

        parsed_data = Parser().parse(response.content.hex()[10:])
        data_dict = parsed_data.to_dict()
        card_data = data_dict["results"][1]["data"]["results"][2]["data"]["results"][1][
            "data"
        ]["results"][0]["data"]

        print(card_data)
        nfc_session.disconnect()

        # Launch GUI with card data
        launch_gui(card_data)


if __name__ == "__main__":
    main()

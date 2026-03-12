import time
from functools import reduce

import serial

# i think it's easier if i just make this act like the pyscard (smartcard) library
# what beautiful code huh :)?

COM_PORT = "COM21"


# list "readers"
def readers():
    return [scardPN532(COM_PORT)]


class scardPN532:
    def __init__(self, comport):
        self.com = comport

    # connect to reader
    def createConnection(self):
        self.reader = PN532(self.com)
        self.reader.wakeup()
        self.reader.SAM_configuration()

        return self

    # connect to card
    def connect(self):
        if self.reader.send_passive_target():
            print("Waiting for card...")
        else:
            raise RuntimeError("something went wrong talking to the reader")

        response = False
        while not response:
            response = self.reader.read_passive_target()
            time.sleep(0.5)

        print("Found card!")

        # ATQA SAK UID ATS
        self.uid = response[2]
        self.ats = response[3]

    # send APDU, return response
    def transmit(self, data):

        # [FF CA 00 00 00] but a list
        if data == [255, 202, 0, 0, 0]:
            # intercept and return the UID of the PICC
            # if you just send it to the PICC you just get a nice 92:82 (Security condition not satisfied)
            # Guess it's just like with standard DESfire cards where you need to be authenticated before it returns its UID
            # or it's just a random command :)
            return list(bytes.fromhex(self.uid)), 0x90, 0x00

        response = self.reader.call_function(0x40, [0x01, data])

        # data, s1, s2
        return (
            list(response[1:-2]),
            int.from_bytes(response[-2:-1]),
            int.from_bytes(response[-1:]),
        )

    # get ATR
    def getATR(self):
        # same as with the UID, our lovely PN532 already gives it to us on the connect step
        # so, undo all of that and calculate an ATR
        # https://learn.microsoft.com/en-us/windows-hardware/drivers/nfc/pc-sc-interface#atr-format-for-iso14443-4-cards

        cut_ats = bytes.fromhex(self.ats)[5:]
        size = len(cut_ats) & 0x0F

        atr = [0x3B, size, 0x80, 0x01, cut_ats, 0x00]
        return canonicalize_params(atr)

    def disconnect(self):
        # do absolutely nothing :)
        return True


# --- PN532 part ---
PN532_HOSTTOPN532 = 0xD4
PN532_PN532TOHOST = 0xD5

# PN532 Commands
PN532_COMMAND_GETFIRMWAREVERSION = 0x02
PN532_COMMAND_SAMCONFIGURATION = 0x14
PN532_COMMAND_INLISTPASSIVETARGET = 0x4A

PN532_WAKEUP = 0x55

PN532_SPI_STATREAD = 0x02
PN532_SPI_DATAWRITE = 0x01
PN532_SPI_DATAREAD = 0x03
PN532_SPI_READY = 0x01

PN532_ISO14443A = 0x00
PN532_ISO14443B = 0x03

PN532_ACK_FRAME = b"\x00\x00\xff\x00\xff\x00"


def millis():
    return int(time.time() * 1000)


def uint8_add(a, b):
    return ((a & 0xFF) + (b & 0xFF)) & 0xFF


def canonicalize_params(params, ignore_errors=False):
    if not params:
        return []

    ret = []
    for i, param in enumerate(params, 1):
        if isinstance(param, (list, tuple)):
            ret += canonicalize_params(param)
        elif isinstance(param, bytes):
            ret += list(param)
        elif isinstance(param, str):
            ret += list(param.encode())
        elif isinstance(param, int):
            ret.append(param & 0xFF)
        elif not ignore_errors:
            raise ValueError(
                "Param #{} is of unsupported type: {}".format(i, type(param))
            )

    return ret


class PN532:
    def __init__(self, comport, baudrate=115200):
        self.message = b""

        self.ser = serial.Serial(comport, baudrate)
        self.ser.timeout = 2

    @staticmethod
    def checksum(data):
        return ~reduce(uint8_add, data, 0xFF) & 0xFF

    def _send_command(self, command, *params):
        # Build frame to send

        params = canonicalize_params(params)

        # Build frame data with command and parameters.
        data = bytes([PN532_HOSTTOPN532, command & 0xFF] + params)

        assert 0 < len(data) < 255, "Data must be array of 1 to 255 bytes."

        length = len(data)
        frame = (
            bytes(
                [
                    0x00,  # - Preamble
                    0x00,  # - Start code
                    0xFF,  # - Start code2
                    length & 0xFF,  # - Command length
                    uint8_add(~length, 1),  # - Command length checksum
                ]
            )
            + data  # - Command bytes
            + bytes([self.checksum(data), 0x00])  # - Checksum and postamble
        )

        self.ser.flushInput()
        ack = False
        start_time = millis()
        while not ack:
            self.ser.write(frame)
            # print('>', frame)
            ack = self._ack_wait(1000)
            # time.sleep(0.3)
            if millis() - start_time > 5000:
                return False
        return True

    def _ack_wait(self, timeout):

        start_time = millis()
        current_time = start_time

        while current_time - start_time < timeout:
            # time.sleep(0.12)  # Stability on receive
            if self.ser.inWaiting() >= 6:
                # ONLY read 6 (lenght of the ack frame) to not eat other data
                buf = self.ser.read(6)

                if PN532_ACK_FRAME in buf:
                    return True

            current_time = millis()

        return False

    def _read_frame(self):
        """Read a response check it :3, false if no data"""
        # check if there's actually some data there
        if self.ser.inWaiting() == 0:
            return False

        # time.sleep(0.12)  # wait juuuuust a bit just in case
        response = self.ser.read(self.ser.inWaiting())

        if response[0] != 0x00:
            raise RuntimeError("Response frame does not start with 0x00!")

        # Swallow all the 0x00 values that preceed 0xFF.
        offset = 1
        while response[offset] == 0x00:
            offset += 1
            if offset >= len(response):
                raise RuntimeError("Response frame preamble does not contain 0x00FF!")
        if response[offset] != 0xFF:
            raise RuntimeError("Response frame preamble does not contain 0x00FF!")
        offset += 1
        if offset >= len(response):
            raise RuntimeError("Response contains no data!")

        # Check length & length checksum match.
        frame_len = response[offset]
        if (frame_len + response[offset + 1]) & 0xFF:
            raise RuntimeError("Response length checksum did not match length!")

        # Check frame checksum value matches bytes.
        checksum = reduce(
            uint8_add, response[offset + 2 : offset + 2 + frame_len + 1], 0
        )
        if checksum:
            raise RuntimeError("Response checksum did not match expected value!")

        # Return frame data (d5 command data).
        return response[offset + 2 : offset + 2 + frame_len]

    def wakeup(self):
        self.ser.write(b"\x55\x55\x00\x00\x00")

    def call_function(self, command, *params):
        """
        Calls function and returns response
        """
        # Send frame and wait for response.
        if not self._send_command(command, params):
            return None

        # you can lower this number if everything works gud :3
        time.sleep(0.10)
        # Read response bytes.
        response = self._read_frame()

        # Check that response is for the called function.
        if response:
            if response == "ack":
                return True

            if response[0] != PN532_PN532TOHOST or response[1] != command + 1:
                if response.hex() == "7f":
                    raise RuntimeError("PN532 reports Application Level Error")
                else:
                    raise RuntimeError(
                        "Received unexpected command response: " + response.hex()
                    )

            # Return response data.
            return response[2:]

        return response

    def get_firmware_version(self):
        """Call PN532 GetFirmwareVersion function and return a tuple with the IC,
        Ver, Rev, and Support values.
        """
        response = self.call_function(PN532_COMMAND_GETFIRMWAREVERSION)
        if response is None:
            raise RuntimeError(
                "Failed to detect the PN532!  Make sure there is sufficient power (use a 1 amp or greater power supply), the PN532 is wired correctly to the device, and the solder joints on the PN532 headers are solidly connected."
            )
        return (response[0], response[1], response[2], response[3])

    def SAM_configuration(self):
        """Configure SAM to read cards."""
        # Send SAM configuration command with configuration for:
        # - 0x01, normal mode
        # - 0x14, timeout 50ms * 20 = 1 second
        # - 0x01, use IRQ pin
        # Note that no other verification is necessary as call_function will
        # check the command was executed as expected.
        self.call_function(PN532_COMMAND_SAMCONFIGURATION, [0x01, 0x14, 0x01])

    def send_passive_target(self, card_baud=PN532_ISO14443A, init_data=[]):
        """
        Tells PN532 to get cards, returns true if ack, to get data call read_passive_target
        """
        if card_baud == PN532_ISO14443B and init_data == []:
            init_data = [0x00]  # listen for all card types (NFCB)

        response = self._send_command(
            PN532_COMMAND_INLISTPASSIVETARGET,
            1,  # amount of cards
            card_baud,
            init_data,
        )

        return response

    def read_passive_target(self, card_baud=PN532_ISO14443A):
        """
        Check if card is in field, return ATQA SAK UID ATS of card if so
        returns false if no card
        """

        # read frames
        response = self._read_frame()

        if response:
            if response[0] == 0x7F:
                raise RuntimeError("Application level error")

            if response[2] != 0x01:
                raise RuntimeError("More than one card detected!")

            if card_baud == PN532_ISO14443B:
                # Return ATQB and ATTRIB_RES of card.
                return [
                    response[4:16].hex(),
                    response[16 + response[16] :].hex(),
                ]

            # else, the normal NFCA things
            # Check only 1 card with up to a 7 byte UID is present.
            if response[7] > 7:
                raise RuntimeError("Found card with unexpectedly long UID!")
            # Return ATQA SAK UID ATS of card.
            return [
                response[4:6].hex(),
                response[6:7].hex(),
                response[8 : 8 + response[7]].hex(),
                response[8 + response[7] :].hex(),
            ]

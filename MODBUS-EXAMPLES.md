# Read-only Modbus examples

[Home](README.md) · [Register reference](MODBUS-REGISTERS.md) · [CLI guide](NETWORK-SCRIPTS.md)

These examples use **synthetic numbers** and illustrate addressing and decoding. They do not change inverter settings. For an actual connection, verify the interface, serial and model first. Run Python examples from the repository root; on Windows use `py -3` instead of `python3`.

## 1. Read the two PV trackers

Save the following as `private/read_pv.py`, replace the example host/unit and expected serial, and run `python3 private/read_pv.py`. This uses the project's input-only transport, so inherited write methods are also blocked.

```python
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd() / "scripts"))
from sh10rt_lan import ReadOnlyModbus, number

client = ReadOnlyModbus("192.168.1.100", unit=1, timeout=3)
expected_serial = "YOUR_SERIAL"
if client.identity() != expected_serial:
    raise RuntimeError("Unexpected inverter; verify the interface before reading.")

# This helper accepts one-based logical addresses and subtracts one internally.
raw = client.read(5011, 4)
words = dict(zip(range(5011, 5015), raw))
for tracker, address in ((1, 5011), (2, 5013)):
    voltage = number(words, address, .1)
    current = number(words, address + 1, .1)
    watts = None if voltage is None or current is None else round(voltage * current, 1)
    print({"mppt": tracker, "voltage_v": voltage, "current_a": current, "calculated_w": watts})
```

For WiNet **Modbus forwarding**, use its verified host/unit and construct the client with `timeout=5, pause=1.1`. That is not authenticated WiNet HTTP access. Use `values` for a terminal report. Avoid competing poll loops against the same interface.

An example response `[3500, 40, 3000, 20]` means:

| Tracker | Voltage | Current | Calculated power |
| --- | --- | --- | --- |
| MPPT 1 | 350.0 V | 4.0 A | 1,400 W |
| MPPT 2 | 300.0 V | 2.0 A | 600 W |

`V × A` is calculated tracker power. It is not an independently measured value for each physical string, and need not exactly match a separately sampled inverter total.

## 2. Understand the TCP frame

For the same four-register read, a synthetic Modbus TCP request is:

```text
00 01  00 00  00 06  01  04  13 92  00 04
 TID   protocol length unit FC  address count
```

- Transaction ID `0x0001` pairs the response with the request.
- Protocol ID `0x0000` identifies Modbus; length 6 counts bytes after the length field, including the unit.
- Unit 1 is the selected inverter unit, not the inverter's serial number.
- Function `0x04` reads input registers. Address `0x1392` is decimal **5010**, corresponding to logical register 5011.
- Count 4 requests four 16-bit words. TCP uses an MBAP header; do not append a serial RTU CRC.

A corresponding synthetic response is:

```text
00 01  00 00  00 0B  01  04  08  0D AC  00 28  0B B8  00 14
 TID   protocol length unit FC bytes   four register values
```

The data byte count is 8. The MBAP length is 11: one unit byte, one function byte, one data-count byte and eight data bytes. A TCP `recv()` can return part of a message; the project's transport reads the declared length and verifies transaction, protocol, unit and function. Framing follows the [Modbus Organization specifications](https://www.modbus.org/modbus-specifications), including the TCP/IP messaging guide.

## 3. Decode sign and word order

These calculations require no network access:

```python
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd() / "scripts"))
from sh10rt_lan import number

# Two-word energy counter: low word first, then high word.
assert number({13003: 0xE240, 13004: 0x0001}, 13003, .1, wide=True) == 12345.6

# Signed battery current: 0xFF9C represents -100 raw, or -10.0 A.
assert number({5631: 0xFF9C}, 5631, .1, signed=True) == -10.0

# Signed backup power: 0xFFFFFF06 represents -250 W.
assert number({5726: 0xFF06, 5727: 0xFFFF}, 5726, signed=True, wide=True) == -250

# The same bit pattern is interpreted according to its declared type.
assert number({1: 0xFFFF}, 1) is None
assert number({1: 0xFFFF}, 1, signed=True) == -1
assert number({1: 0x7FFF}, 1, signed=True) is None
```

Do not swap the bytes inside each 16-bit word when applying the 32-bit word-order rule. Arrays such as the three phase voltages remain separate values; they are not combined like a U32.

## 4. Decode a flag word

```python
# Synthetic example, not a fault reading from a real installation.
input_word = 13072
raw = 0x2000
bits = [bit for bit in range(16) if raw & (1 << bit)]
assert bits == [13]
print({"input_word": input_word, "raw_hex": hex(raw), "word_bits": bits})

# The meter communication bit is in the high word of its U32 group.
low_word, high_word = 0, 0x4000
alarm_group = low_word | (high_word << 16)
assert alarm_group & (1 << 30)
```

The first example matches the selected input-13072 bit-13 label in the [fault reference](MODBUS-REGISTERS.md#selected-fault-and-alarm-bits). It is a bit flag, not a numeric iSolarCloud code. The second shows why bit 14 of word 13051 is bit 30 of the group starting at 13050.

## 5. Separate state from a setting

A synthetic inverter can return input 13000 = `16` and holding 13000 = `206`:

| Read | Meaning |
| --- | --- |
| FC04, logical 13000 | Current operating state: Initial Standby |
| FC03, logical 13000 | Software control setting: Stop |

Changing a function code changes the register space. The input-only example above deliberately cannot read holding settings. Use CLI `status` to inspect Start/Stop, and the guarded [Start preview](NETWORK-SCRIPTS.md#3-preview-the-intended-start-action--no-write) if appropriate. Merely discovering a device never authorizes a Start command or a settings change.

## 6. Use the CSV offline

```python
import csv
from pathlib import Path

with Path("reference/modbus-registers.csv").open(newline="") as file:
    for row in csv.DictReader(file):
        if row["group"] == "PV and AC":
            print(row["name"], row["logical_address"], row["pdu_address"], row["data_type"])
```

Filter by register space and target as well as address. The same number can identify an inverter measurement, a holding setting or a different unit's field. Keep actual read captures, IPs and identities under `private/`; public examples should remain synthetic.

## 7. Load the JSON catalog

```python
import json
from pathlib import Path

catalog = json.loads(Path("reference/modbus-registers.json").read_text(encoding="utf-8"))
assert catalog["schema_version"] == 1
voltage = next(row for row in catalog["registers"]
               if row["target"] == "inverter"
               and row["register_space"] == "input"
               and row["logical_address"] == 5011)
assert voltage["pdu_address"] == 5010
assert voltage["register_count"] == 1
assert voltage["read_function"] == 4
assert voltage["multiplier"] == 0.1

flag = next(row for row in catalog["flags"]
            if row["input_word"] == 13072 and row["word_bit"] == 13)
assert flag["word_mask"] == 8192
assert flag["word_mask_hex"] == "0x2000"
```

This loads reference metadata only. It does not poll hardware or translate an entry into a write command. Check `target`, `register_space`, type, availability and identity before using it in an integration.

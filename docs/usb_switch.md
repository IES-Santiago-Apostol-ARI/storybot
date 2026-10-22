# ACR122U power switch

Lets the Jetson cut the NFC reader's USB power from a GPIO, so a reader that
comes up stuck after boot can be recovered without opening the box.

## Why

On some boots the ACR122U's firmware comes up answering each CCID command one
(or more) commands late. pcscd's first read then times out
(`LIBUSB_ERROR_TIMEOUT` → `ACS ACR122U PICC Interface init failed`), the
reader still beeps on taps, but no story starts. It happens on warm reboots and
on cold boots after a full mains power cut, with or without `usbreset`.

Only removing the reader's 5 V while the system is running clears it (a
physical unplug/replug). Nothing done over USB helps: `usbreset`, unbind/bind,
clearing the endpoints, the CCID abort sequence, and `uhubctl` port power-off.
The carrier board's hub reports the port as off but never really cuts VBUS.
This circuit does the replug electrically.

## Design

- **Default ON.** With the GPIO low, floating, or the Jetson not driving it
  (boot, crash, service stopped), the reader is powered. Driving the GPIO
  **high** cuts the reader's power. A software fault can therefore never leave
  the reader permanently dead.
- **High-side switch on VBUS only.** GND, D+ and D- pass straight through.
  Never switch GND on a USB device: it would try to power itself through the
  data lines.
- **GPIO:** 40-pin header **pin 33** (`PH.00`, `gpiochip0` line 43), free on
  this robot. Already in use: 7, 15, 29 and 31 (buttons), 19 (LED strip SPI),
  39 (LED GND).

## Schematic

```
                    VBUS_IN (red wire, Jetson side of the cut)
                         │
          ┌──────────────┼──────────────────────┐
          │              │                      │
         R3 10k         R5 10k                  │ S
          │              │                   ┌──┴──┐
          │      node G ─┼───────────────── G│ Q3  │  P-MOSFET
          │              │                   └──┬──┘  (AO3401A / IRLML6402 /
  node A ─┤              │ C                    │ D     SI2301, see parts)
          │            ┌─┴─┐                    │
          │   R4 10k   │Q2 │ NPN                ├──────────────► VBUS_OUT
          └───/\/\/────┤B  │ 2N3904             │               (red wire, reader side)
          │            └─┬─┘                    │
          │ C            │ E                   R6 2.2k (bleeder)
        ┌─┴─┐            │                      │
 pin 33 │Q1 │ NPN        │                      │
 ──R1──►┤B  │ 2N3904     │                      │
   1k   └─┬─┘            │                      │
     │    │ E            │                      │
    R2    │              │                      │
    10k   │              │                      │
     │    │              │                      │
 ────┴────┴──────────────┴──────────────────────┴──── GND (black wire + header pin 34)
```

| Ref | Part | Notes |
|-----|------|-------|
| Q1, Q2 | NPN 2N3904 (or BC547, BC337) | Any small-signal NPN |
| Q3 | P-channel MOSFET, logic level: **AO3401A**, IRLML6402, SI2301 | Must specify R<sub>DS(on)</sub> at V<sub>GS</sub> = −4.5 V or lower. SOT-23 parts go on a SOT-23-to-DIP adapter. Avoid IRF9540/IRF9530-class parts: they need −10 V to switch fully. |
| R1 | 1 kΩ | GPIO base resistor |
| R2 | 10 kΩ | Holds Q1 off while the GPIO floats at boot (beats the pad's weak internal pull-up) |
| R3, R5 | 10 kΩ | Pull-ups to VBUS_IN |
| R4 | 10 kΩ | Q2 base resistor |
| R6 | 2.2 kΩ | Drains VBUS_OUT quickly when off, so the reader really resets (≈2 mA while on) |
| C1 (optional) | 10 µF | Across VBUS_OUT–GND near the reader, if it browns out when powering up |

### How it works

| Pin 33 | Q1 | node A | Q2 | gate (node G) | Q3 | Reader |
|--------|----|--------|----|---------------|----|--------|
| low / floating | off | 5 V | on | ≈ 0 V (V<sub>GS</sub> = −5 V) | **on** | **powered** |
| high (3.3 V) | on | ≈ 0 V | off | 5 V (V<sub>GS</sub> = 0) | **off** | **unpowered** |

Two NPN stages are needed because a 3.3 V GPIO cannot pull a P-MOSFET gate up
to 5 V on its own. Inverting twice also makes "GPIO not driven" mean "reader
on".

## Building it

1. Take a short USB-A male → USB-A female extension cable (the reader plugs
   into the female end, the male end into the Jetson's port).
2. Strip the outer jacket in the middle and **cut only the red wire** (VBUS).
   Leave black (GND), green and white (data) and the shield untouched.
3. Red wire, Jetson side → VBUS_IN. Red wire, reader side → VBUS_OUT.
4. Tap the black wire for the circuit's GND, and also run a wire to a header
   GND pin (pin 34, next to pin 33) so the GPIO and the circuit share ground.
5. Pin 33 → R1.
6. Insulate everything (heat-shrink) and strain-relieve the cable: the box is
   fragile and this is the part that would get yanked.

### Simpler alternative: relay module

If you'd rather not solder transistors: a **1-channel 5 V relay module with
optocoupler, high-level trigger** (check the IN input accepts 3.3 V).

- Module VCC → header pin 2 or 4 (5 V), GND → pin 6, IN → pin 33.
- Red wire Jetson side → relay **COM**, red wire reader side → relay **NC**
  (normally closed). The reader then stays powered unless pin 33 is driven high.

It clicks and draws ~70 mA while energised, but that's only for the few
seconds of a power cycle.

## Testing

With the reader working (tap a card first to check), run:

```bash
sudo gpioset --mode=time --sec=3 gpiochip0 43=1
```

During those 3 seconds the reader's LED must go dark and
`lsusb -d 072f:2200` must show nothing. Afterwards the line is released, the
reader powers back on, and pcscd and the app pick it up again by themselves
(`pcsc_scan -r` lists it within a few seconds).

If the LED stays on, VBUS isn't really cut: check Q3's orientation (source to
VBUS_IN) and that the gate goes to 5 V while the command runs.

## Software (to do once wired)

- `deploy/storybot-reset-nfc.sh`: replace the `uhubctl`/`usbreset` steps with
  a GPIO power cycle (pin 33 high for 2–3 s) before pcscd starts.
- NFC service: if pcscd still has no reader while the ACR122U is on the bus,
  power-cycle it through pin 33 (a few attempts, spaced out), so a stuck reader
  recovers without a reboot.

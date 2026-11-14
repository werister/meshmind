# Wiring the Pi: Lights, Button and Tiny Screen (Easy Version)

What we build: your Raspberry Pi talks to a white plug-board
(breadboard). On the board: 2 lights (LEDs), 1 click-button and the
tiny Nokia phone screen. The screen will later show temperature and
what the Pi is doing. The fan stays exactly where it is for now.

New words (30 seconds):
- Breadboard = white LEGO plate with secret tunnels inside. Wires
  plugged into connected holes share electricity automatically.
- Rail = the long red (+) and blue (-) lines = rivers of power.
- GND (ground) = the drain where electricity flows home. Safe.
- 3V3 / 5V = gentle power / strong power. The screen only likes gentle!
- GPIO = a light switch the Pi can flip by itself (on / off).
- Resistor = a narrow bridge: slows electricity so LEDs don't burn out.

> Works with every variant of your pieces: do the 3 checks in §0,
> then follow WORDS and NUMBERS, not positions.

## 0. Look at your pieces first (2 minutes)

1. SCREEN: find the 8 tiny words printed at its edge (like name tags).
   Usually: RST CE DC DIN CLK VCC BL GND — but yours may sit in a
   different order, and that is fine! In §3.2 you match WORDS.
   Only 7 words and no BL? Fine too — skip every BL step.
2. WHITE BOARD: find the biggest printed number (30? 63?). Our plan
   only uses rows 1–27, so both sizes work. Then look at the red and
   blue lines: a gap in the middle? If yes, say so — we add one
   little bridge wire there.
3. TEMPERATURE THINGY: black blob with 3 legs and tiny text? Or a small
   blue/white box? Just describe it later (§6). The Pi can already
   feel its own heat without it.

## 1. Your white board, drawn

Power rivers run ALONG the board. Letter holes share DOWN each number.
Nothing crosses the middle gap.

```
  (+) rail o---o---o---o---o---o---o---o---  red river (gentle power)
  (-) rail o---o---o---o---o---o---o---o---  blue river (drain/GND)
                1   5   10  15  20  25  30   <- numbers on YOUR board
              +---+---+---+---+---+---+---+
           a  | o | o | o | o | o | o | o |
           b  | o | o | o | o | o | o | o |   a-b-c-d-e under ONE
           c  | o | o | o | o | o | o | o |   number = joined together
           d  | o | o | o | o | o | o | o |   (secret tunnel)
           e  | o | o | o | o | o | o | o |
              +---+---+---+---+---+---+---+
              ===== middle gap: NO tunnel across =====
              +---+---+---+---+---+---+---+
           f  | o | o | o | o | o | o | o |
           g  | o | o | o | o | o | o | o |   f-g-h-i-j under ONE
           h  | o | o | o | o | o | o | o |   number = joined together
           i  | o | o | o | o | o | o | o |
           j  | o | o | o | o | o | o | o |
              +---+---+---+---+---+---+---+
  (-) rail o---o---o---o---o---o---o---o---
  (+) rail o---o---o---o---o---o---o---o---
```

Trick to remember: numbers are "rooms", letters are "doors".
All 5 doors of one room lead to the same room.

## 2. The Pi's pin rows (`*` = we use it)

40 pins in 2 rows. Pin 1 gives gentle power (look for tiny P1 / square
pad near the SD card edge). Fan pins (4 and 6) stay untouched!

```
   3V3   (1)  (2)  5V            strong-power side (fan red on pin 4)
   GPIO2 (3)  (4)  5V          * fan red stays here, do not touch
   GPIO3 (5)  (6)  GND         * fan black stays here, do not touch
 * GPIO4 (7)  (8)  GPIO14        button wire goes here
     GND (9) (10)  GPIO15     * pin 9: blue river on the board
 * GPIO17(11)(12)  GPIO18        light 1 wire goes here
 * GPIO27(13)(14)  GND           light 2 wire goes here
   GPIO22(15)(16)  GPIO23        (empty for now)
     3V3 (17)(18)  GPIO24     * pin 17: spare gentle power
 * GPIO10(19)(20)  GND           screen data wire (DIN) goes here
   GPIO9 (21)(22)  GPIO25     * screen helper wire (DC) goes here
 * GPIO11(23)(24)  GPIO8      * screen clock (CLK) + screen select (CE)
     GND (25)(26)  GPIO7         (empty for now)
   (27-40 empty for now; 27-28 are reserved, never touch)
```

## 3. Wire by wire (Pi OFF while you plug!)

Order: rivers (§3.1) → screen (§3.2) → lights (§3.3) → button (§3.4).
M-F wire = Pi pin to board. M-M wire = board to board.

### 3.1 The two rivers (first!)

| From Pi        | To board   | Wire | Color wish |
|----------------|------------|------|------------|
| gentle (pin 1) | red (+)    | M-F  | red        |
| drain (pin 9)  | blue (-)   | M-F  | black/blue |

Why pin 9 and not 6? Pin 6 is busy holding the fan. All drain pins
are the same drain, so pin 9 is equally good.

### 3.2 The tiny screen (8 name tags, gentle power ONLY!)

Push the screen's 8 legs into holes `f1`–`f8`, in whatever order YOUR
printed words come in. Each leg then owns its number: you can plug the
Pi wire into `j` of the same number (same room!).

Example if your words read `RST CE DC DIN CLK VCC BL GND`:

| Word on screen | Leg sits in | Wire to Pi / river         |
|----------------|-------------|----------------------------|
| RST (restart)  | f1          | M-F: pin 18 → j1           |
| CE (select me) | f2          | M-F: pin 24 → j2           |
| DC (words?/pic)| f3          | M-F: pin 22 → j3           |
| DIN (data in)  | f4          | M-F: pin 19 → j4           |
| CLK (heartbeat)| f5          | M-F: pin 23 → j5           |
| VCC (food!)    | f6          | M-M: i6 → red river (3V3!) |
| BL (back glow) | f7          | M-M: i7 → red river        |
| GND (drain)    | f8          | M-M: i8 → blue river       |

Your words in another order? Same table, just your numbers.
No BL word? Skip that row. VCC and BL get GENTLE power (red river =
3V3). Strong power (5V) kills the screen forever. Double-check these
two with fresh eyes before booting.

### 3.3 The two lights (each needs its narrow bridge!)

Long leg = hungry (+), short leg = drain (-). Always a resistor
between Pi and long leg, or the light burns out.

Light 1 (green = "Pi feels good"):

```
  pin 11 --M-F--> a18 ..(same room).. c18 --[resistor]-- c20
  long leg  --> e20        (room 20: shares with c20 ✓)
  short leg --> e21   ..   c21 --M-M--> blue river
```

Light 2 (red = "busy / hot"), same game shifted right:

```
  pin 13 --M-F--> a24 .. c24 --[resistor]-- c26
  long leg  --> e26   short leg --> e27 .. c27 --M-M--> blue river
```

Resistor: any stripy tube from the book's light chapter (220–1000 Ω
all fine — bigger number = dimmer light, still fine).

### 3.4 The click-button (sits on the gap like a bridge)

Push 2 legs above the gap (`e10, e12`) and 2 below (`f10, f12`).
Clicking connects top to bottom for a moment.

```
  pin 7 --M-F--> a10   (room 10: shares with e10 ✓)
  i10 --M-M--> blue river   (room f-j/10: shares with f10 ✓)
```

Later the Pi turns on an invisible helper (pull-up) so the button
reads OFF until you click it. No resistor needed.

## 4. What we used (count check)

M-F wires (Pi → board): 2 rivers + 5 screen + 2 lights + 1 button = 10
(you own 30). M-M wires (board → board): 3 screen + 2 lights + 1 button
= 6 (you own 30). Resistors: 2. Lights: 2. Button: 1. Fan: untouched
on pins 4 + 6 — wiggle-check it sits tight when you are done.

## 5. The fan button dream (LATER — one part missing)

Your fan drinks ~10x more than a Pi switch-pin can give, so the Pi
cannot hold it directly — it would faint (brown-out) or break. We
need one helper part first (~€1: a transistor called 2N2222 or BC547,
plus a diode 1N4007 and a 1k resistor). Then:

```
   5V (pin 2/4) o------+------------------o fan red
                       |
                  diode _V_  (stripe points UP to 5V)
                       |_|
                       +------------------o fan black
                       |
                       +----[C]  transistor: [B] --[1k]--o pin 12
                                          [E] --o drain (GND)
```

Translation: the fan keeps drinking straight from 5V, and the
transistor is a gate the Pi opens/closes from pin 12. Pin 12 can even
half-open the gate (dimmer for fans = quiet nights). Shopping list
first, wires later — say the word and I draw the exact rows.

## 6. Safety rules (read once, out loud is fine)

1. Pi OFF while plugging. Look twice, boot once.
2. Screen + lights + button = gentle world. The ONLY strong power in
   this build is the fan, which never touches the board.
3. Every light keeps its resistor. Long leg toward the Pi side.
4. Screen food (VCC) and drain (GND): read the words, then read again.
   Mixed up = dead screen.
5. First boot after wiring: watch and sniff for a minute. A good
   build stays cold except the Pi itself (warm is normal, ~40–50 °C).

## 7. The temperature thingy (after you describe it)

- Black blob, 3 legs, tiny text `DS18B20`? → 3 easy wires, super exact.
- Small blue/white box (`DHT11`/`DHT22`)? → 3 wires + a tiny program.
- No markings? Send a photo description (color, shape, words on it).
Until then: the Pi feels its own heat already (right now: 44 °C) —
that is what the screen will show first anyway.

## 8. What happens after wiring (I do this part)

1. I switch on the Pi's screen-language (SPI) + one reboot.
2. I install 3 free programs (screen driver + helpers).
3. I write the show program: temperature + how busy the Pi is + what
   it is working on, green light = happy, red light = busy/hot,
   button = next page. Then it starts alone on every boot.

## 9. Before you boot: the checklist

- [ ] §0 done (screen words order / biggest board number / sensor look)
- [ ] Red river ← pin 1, blue river ← pin 9
- [ ] Screen: 8 wires matched by WORD, food+glow on gentle, drain on blue
- [ ] Lights: resistor in the path, long legs toward Pi side
- [ ] Button bridges the gap, pin 7 side + drain side correct
- [ ] Fan still on pins 4 + 6, nothing else on strong power
- [ ] Nothing in pins 27/28, no wire crossing the middle gap by accident

## 10. Session notes 2026-11-14 (hardware)

- Orientation gotcha: the header was first read 180° flipped. Ground truth
  used: spinning fan on TRUE pins 4 (5V) + 6 (GND); counting outward from
  there. The square solder dot (belly, pin 1) settles any future doubt.
- Fan moved 3V3→5V (pin 1→4); spins properly now. Black stays pin 6.
- Board: 30-row half-size confirmed (photo), no rail splits seen, resistor
  value OK (100Ω–1kΩ range), pins 1/9/11 placement photo-verified.
- LED never lit in any configuration → board retired as faulty (contacts).
  The wireframe above is still correct; re-run on a fresh board or direct
  wiring before trusting it end to end.
- Display NOT wired yet (kept out deliberately until power was certain).
  Next attempt goes direct Pi→display, skipping the board.

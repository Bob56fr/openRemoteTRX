# Reports for the Hamlib developers (draft)

Drafts prepared from measurements made with an Icom IC-7300MK2 while building TRX Remote (openRemoteTRX).
Where to send: the mailing list `hamlib-developer@lists.sourceforge.net` (see https://github.com/Hamlib/Hamlib, README);
the repository also has a GitHub issue tracker: check CONTRIBUTING.md before choosing. One subject per message.
Before sending: attach the full `rigctld -vvvvv` log of a failing run, and re-check items 2 and 3 against the
current master branch.

---

## 1. `async=1` on Windows: replies shift, wrong frequency returned as success, `T 0` fails (IC-7300MK2)

**Setup**
- Hamlib 4.7.2, Windows 11, rigctld, model 3094 (IC-7300MK2), USB CI-V port A (COM8), 115200 baud, CI-V address B6h,
  "CI-V USB Echo Back" ON on the radio.
- `rigctld -m 3094 -r COM8 -s 115200 -C async=1,multicast_data_addr=127.0.0.1,multicast_data_port=4572,multicast_cmd_addr=0.0.0.0`

**What happens**
1. During `rig_open`, every read fails immediately with `port_read_sync_data(): WaitForMultipleObjects() error`
   (the async reader thread does not seem to be running yet).
2. Hamlib then concludes "USB echo off", although echo is ON on the radio.
3. From then on, replies are shifted against requests: `cmd x25 != buf x03`, `unknown async? read again`.
4. A wrong frequency is returned **as a success**: `f` answers `65190` while the radio is on 6 519 000 Hz.
5. `T 0` fails: `icom_check_ack: command timed out (0x14)`, `RPRT -5`.
6. With echo turned OFF on the radio, rigctld does not answer at all.

**Without `async=1`**, with the same radio, port and speed, everything works (frequency, mode, PTT, levels).

**Why it matters**: a frequency read that is wrong but reported as a success, and a PTT-off command that fails, are
serious for remote-control software (we refuse to transmit when in doubt, but other programs may not).

**Expected**: either async works on Windows, or `rig_open` fails cleanly when the async reader cannot be started;
the echo detection should not run before the reader is ready.

Attached: full `rigctld -vvvvv` log (to add).

---

## 2. IC-7300MK2 (model 3094): IP+ not declared, manual notch frequency without range

**Setup**: Hamlib 5.0.0~git 2026-10-19T18:09:55Z SHA=fa0ed6d6a, Debian 13, `rigctl -m 3094 -u` (no radio needed).

**Observed in `dump_caps`**
- `Get functions` / `Set functions`: `NB COMP VOX TONE TSQL SBKIN FBKIN ANF NR MON MN LOCK RIT SCOPE TUNER XIT
  TRANSCEIVE SPECTRUM SPECTRUM_HOLD SEND_MORSE SEND_VOICE_MEM OVF_STATUS` — **no `AIP`** (IP+), although the radio
  has an IP+ key (CI-V command to be confirmed in the IC-7300 CI-V reference).
- `Set level: ... NOTCHF_RAW(0.000000..0.000000/0.000000)`: the manual notch position has an empty range, so a client
  cannot offer a sensible control for it.
- Inconsistent attenuator description: `Attenuator: 20dB` but `Set level: ATT(0..12/0)`. A client that trusts the
  range cannot set the only real value (20 dB). Same pattern for the preamp: `Preamp: 1dB 2dB` (which are in fact
  P.AMP 1 and 2) next to `PREAMP(0..20/10)`.
- Bandwidths for USB/LSB/PKTUSB/PKTLSB: `Normal 2.4 kHz, Narrow 1.8 kHz, Wide 3.0 kHz` only, while the radio's IF filter
  can be set up to 3.6 kHz in SSB. (We are measuring which widths `M USB <width>` actually applies; results to add.)

**Request**: declare `AIP` for the IC-7300 family if it is supported by the CI-V command set, and give `NOTCHF_RAW`
(or `NOTCHF`) a usable range for this model.

---

## 3. (Minor) PTT read-back sometimes served from cache

With rigctld (model 3094, no async), `rig_get_ptt` sometimes returns immediately (`elapsed=0ms`) without
`icom_get_ptt` in the log. For safety software that re-reads PTT to confirm the radio really left transmission,
knowing whether a value comes from the cache matters. Is there a supported way to force a fresh read (cache
timeout setting for PTT)?

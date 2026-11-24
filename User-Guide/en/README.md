# Commissioning an openRemoteTRX station: operator guide

This guide takes you, step by step, from unpacking to the first link from outside. It applies to any transceiver
known to Hamlib; what is specific to one model (USB driver, menus, ports) is in its **transceiver sheet**:

- [Icom IC-7300MK2](postes/ic7300mk2.md): **validated** on a real transceiver;
- [Yaesu FTDX10](postes/ftdx10.md): prepared, **validation in progress**.

For another transceiver: its manual, the “Depending on your brand” table of the [quick start](demarrage-rapide.md),
and the tests of part 3, which serve as validation: do them all, on a dummy load, and report the result
(part 8, “Asking for help”). Status of each transceiver tested: https://bob56fr.github.io/openRemoteTRX/postes/

> **In a hurry?** The [quick start](demarrage-rapide.md) takes you from the connected transceiver to the web page in
> a quarter of an hour, transceiver TOT included. Come back to the parts below at the first problem.

## The path

| Part | What you do | Approximate time |
|---|---|---|
| [Quick start](demarrage-rapide.md) | the essentials for the impatient, safety tests included | 15 min |
| [0. Before you start](00-avant-de-commencer.md) | hardware, regulations, choosing Debian, Raspberry Pi or Windows | 15 min of reading |
| [1. Prepare the transceiver](01-preparer-le-poste.md) | cabling, USB driver, transceiver menus | 30 min |
| [2. Install the station](02-installer-la-station.md) | software on the PC or the Raspberry Pi | 20 min (Pi: 1 h with the SD card) |
| [3. Integrate the TRX and test it](03-integrer-et-essayer-le-trx.md) | wizard, receive then transmit tests, safety tests | 1 h 30 |
| [4. Use on the local network](04-utilisation-sur-le-lan.md) | web page, phone, Android app | 30 min |
| [5. Use remotely](05-utilisation-a-distance.md) | VPN or exposed port, test over 4G | 1 h |
| [6. Unattended station](06-station-sans-surveillance.md) | alerts, restart after a power cut, protections | 30 min |
| [7. Day-to-day operation](07-exploitation-au-quotidien.md) | start, monitor, update, back up | to read |
| [8. Troubleshooting](08-depannage.md) | error codes, common problems, asking for help | when needed |
| [9. Optional features](09-fonctions-facultatives.md) | visitors, DX Cluster, FreeDV, SELCALL, SWR… | as you wish |
| [Glossary](glossaire.md) | the project's words: who is what | when needed |
| [10. Checklist](10-recapitulatif.md) | know where you stand | |

Transceiver sheets: [Icom IC-7300MK2](postes/ic7300mk2.md), [Yaesu FTDX10](postes/ftdx10.md). Diagram of the
station's building blocks: part 0, “How it is organised”.

## How to read this guide

- The **openRemoteTRX Console menus** are given by their number: “menu 2.1” = theme 2 (Transceiver and hardware),
  menu 1. On Windows, the shortcut Start menu > **openRemoteTRX** opens the same console (part 2). The console opens
  in **full screen**: themes on the left with their icon (arrows and Enter), help for the selected menu on the right;
  you can also type the number in the text console (`trx-console --texte`).
- A **“Safety”** box marks a point that concerns transmission: do not skip it.
- What changes with the system is arranged in **tabs** Debian / Raspberry Pi / Windows: choose yours once, it is
  remembered for the whole page. On GitHub, the tabs are shown one below the other.
- This guide also exists as a web page, with a checklist you tick online, and as a **PDF** to print
  (link “Download as PDF” at the top of the page): https://bob56fr.github.io/openRemoteTRX/guide/en/

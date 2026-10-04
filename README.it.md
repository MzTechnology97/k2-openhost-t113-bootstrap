# Slot B K2-OpenHost per il T113 della K2 Pro

[English](README.md) · **Italiano**

> [!WARNING]
> **Solo per utenti esperti, a proprio rischio.** K2-OpenHost invalida la garanzia del produttore e può danneggiare la stampante in modo irreparabile, mandare in brick il firmware o, in caso di malfunzionamento, causare un incendio. Gli autori non si assumono alcuna responsabilità per danni a cose o persone.
> In modalità OpenHost le **telecamere dell'ugello e della camera** non possono essere gestite dal T113 e vanno ricablate direttamente sull'host Linux esterno; la **porta USB esterna** della stampante non può essere usata per stampare e smette completamente di funzionare in modalità gadget.
> Leggi l'[esclusione di responsabilità e i limiti hardware](https://github.com/MzTechnology97/K2-OpenHost/blob/main/docs/it/DISCLAIMER.md) prima di usarlo.

> **Stato: costruito e verificato offline, mai avviato su una stampante.** Niente di tutto questo ha ancora girato sull'hardware reale.

Il T113 della K2 Pro ha due slot di sistema, A e B: due partizioni del kernel (`bootA`/`bootB`) e due filesystem di root (`rootfsA`/`rootfsB`). Un aggiornamento OTA di Creality scrive lo slot inattivo e cambia due variabili di U-Boot. Questo pacchetto usa lo stesso meccanismo per mettere un sistema K2-OpenHost nello **slot B** e lasciare **lo slot A esattamente com'è**, come riserva.

## Cos'è lo slot B

Il sistema Creality originale dello slot A (1.1.0.94), con queste modifiche:

| Modifica | Perché |
| --- | --- |
| Livello scrivibile in `/mnt/UDISK/.k2openhost/overlay` | `rootfs_data` è la partizione overlay dello slot A: lo slot B non la monta, non la controlla e non la formatta mai. |
| UDISK non viene mai formattato, controllato o cancellato | UDISK contiene i dati dello slot A. Lo script di avvio originale che formatta UDISK/`rootfs_data` quando non sembrano ext4 e azzera le partizioni elencate in `parts_clean` crea solo i link `/dev/by-name`; il montaggio automatico non lancia `e2fsck`; lo slot B aggiunge solo la sua cartella `.k2openhost`. |
| Servizio `k2oh-gadget` | Mette la USB0 in modalità device e crea tre funzioni Generic Serial (`0525:a4a6`, interfacce 00/01/02). |
| Servizio `k2oh-bridge` | Un processo bridge per bus: `ttyGS0↔ttyS2` Main MCU, `ttyGS1↔ttyS3` Nozzle MCU, `ttyGS2↔ttyS5` RS-485/CFS/motori, 230400 8N1. È il bridge validato sulla stampante di riferimento, riavviato da procd. |
| Disattivati: Klipper, klipper_mcu, Moonraker, nginx, app Creality di interfaccia e cloud (`app`), ADB, telecamera WebRTC, OTA da chiavetta, ripristino di fabbrica (`wipe_data`) | Klipper gira sull'host esterno; ADB prenderebbe il controller USB; un OTA avviato dallo slot B sovrascriverebbe lo slot A; il ripristino di fabbrica cancella quasi tutto UDISK. |
| `chamber_cam_power.sh` non fa nulla | Sulla K2 Pro il suo `restart` legge `usbc0/usb_host`, che riporta la USB0 in modalità host e fa cadere tutti e tre i canali. |
| Comando `k2oh-slot` | Mostra e cambia lo slot di avvio. |

Restano: il kernel originale (ha già i driver gadget USB), `mcu_update` (avvia le applicazioni di Main e Nozzle MCU a ogni avvio, vedi sotto), `board_init`, la rete (Ethernet DHCP), SSH, i log. Qualsiasi telecamera va collegata all'host esterno.

## File

| File | Gira su | Cosa fa |
| --- | --- | --- |
| `build-slot-b.sh` | Linux (per esempio il CM5) | Costruisce `bootB.img` e `rootfsB.squashfs` da `kernel` e `rootfs` dell'OTA originale. |
| `install-slot-b.sh` | La stampante, slot A | Controlla, salva il vecchio slot B e l'ambiente U-Boot, scrive lo slot B e lo rilegge. Non cambia slot. |
| `rootfs/` | — | File aggiunti al filesystem originale. |

### Costruzione

Servono `fakeroot` e `squashfs-tools` (`apt-get download squashfs-tools && dpkg -x squashfs-tools_*.deb tools` funziona senza root). Estrai `kernel` e `rootfs` dall'originale `CR0CN200400C10_ota_img_V1.1.0.94.img` (un archivio cpio), poi:

```bash
./build-slot-b.sh --kernel kernel --rootfs rootfs --out out
```

Lo script rifiuta altre versioni originali senza `--allow-other-base`, controlla che i servizi siano disattivati e che `rootfs_data` non venga toccata, e scrive `SHA256SUMS` e `manifest.txt`.

### Installazione (non ancora provata)

Copia `out/` sulla stampante (per esempio in `/mnt/UDISK/k2oh-slotb`) e, da root sullo slot A:

```sh
sh install-slot-b.sh --check   # solo controlli
sh install-slot-b.sh           # scrive e verifica lo slot B
/mnt/UDISK/.k2openhost/bin/k2oh-slot boot-b && reboot
```

`boot-b` è un **avvio di prova**. All'inizio dell'avvio dello slot B, prima di qualsiasi altra cosa, il prossimo avvio viene riportato sullo slot A. Se lo slot B non parte, spegni e riaccendi la stampante e torna allo slot A. Quando lo slot B funziona, esegui `k2oh-slot commit` su di esso per tenerlo. `k2oh-slot boot-a` torna allo slot A in qualsiasi momento.

Le `authorized_keys` SSH dello slot A vengono copiate nello slot B. La password di root dello slot B è quella originale.

## Aggiornamento del firmware delle MCU

Il firmware delle periferiche sta nell'immagine di sistema, in `/usr/share/klipper/fw/F012/*.bin` per la K2 Pro. A ogni avvio il servizio originale `mcu_update`:

1. fa l'handshake con Main MCU (`ttyS2`) e Nozzle MCU (`ttyS3`) nel loader Creality e ne legge la versione;
2. riscrive ogni MCU la cui versione è **diversa** dal `.bin` corrispondente, più vecchia o più nuova;
3. aggiorna il motore dell'estrusore passando dalla modalità trasparente della scheda ugello, e i motori, il nastro e l'RFID su RS-485 con `mcu_util_485`. Il CFS viene aggiornato solo quando il server OTA lo avvia con `CFS=1` e `/tmp/cfs_update.json`, dopo aver fermato Klipper e spento e riacceso l'alimentazione delle MCU (`mcu_reset.sh`);
4. avvia le applicazioni delle MCU (`startup app`). Questo passo serve a ogni avvio, per questo lo slot B tiene il servizio.

Il `motor_updater.py` di Jacob10383 fa lo stesso in Python all'avvio, con il firmware incluso nella sua immagine: P2P a 115200 per Main/Nozzle MCU, RS-485 per motori e CFS, esclusi nastro e RFID. I protocolli sono documentati in [K2-OpenHost Firmware Tools](https://github.com/MzTechnology97/k2-openhost-firmware-tools).

Conseguenze per lo slot B:

- Lo slot B ha gli stessi file firmware dello slot A, quindi avviare l'uno o l'altro non riscrive nulla.
- Passare a una nuova versione Creality vuol dire mettere i suoi `.bin` nello slot B (il suo livello scrivibile è su UDISK, quindi lo slot A non viene toccato) ed eseguire la sequenza originale con i bridge e il Klipper dell'host fermi. Lo fa `k2oh-mcu-fw` (sotto).
- **Lo slot A riscrive i suoi file più vecchi al suo prossimo avvio**, perché lo script originale riscrive a ogni differenza.
- L'host esterno non può aggiornare passando dai bridge così come sono: i loader parlano a 115200, i bridge tengono le UART a 230400 e il collegamento seriale gadget non trasporta i cambi di velocità. Gli aggiornamenti si fanno sul T113.

### `k2oh-mcu-fw`

Gira sullo slot B, da root.

| Comando | Cosa fa |
| --- | --- |
| `k2oh-mcu-fw list` | Elenca le versioni OTA della K2 Pro nell'indice firmware pubblico di Creality (`crealitycloud.com`, senza account e senza inviare dati della stampante). |
| `k2oh-mcu-fw download [VERSIONE]` | Scarica una versione dal CDN Creality (di default l'ultima), controlla il filesystem di root con l'elenco MD5 contenuto nell'immagine, tiene solo `/usr/share/klipper/fw/F012` e `/usr/share/klipper/fw/cfs` in `/mnt/UDISK/.k2openhost/mcu-fw/<versione>/` con un manifest SHA-256, e cancella l'immagine. Il filesystem di root viene letto direttamente (il kernel del T113 non ha dispositivi loop), non viene montato nulla. |
| `k2oh-mcu-fw status` | Mostra la versione di ogni scheda (dall'ultimo `mcu_update`) e il file con cui verrebbe aggiornata. |
| `k2oh-mcu-fw stage VERSIONE` | Sostituisce i file firmware dello slot B con una versione scaricata e mostra quali file cambiano. Lo slot B li scrive al suo prossimo avvio. |
| `k2oh-mcu-fw unstage` | Rimette i file originali dello slot B. |
| `k2oh-mcu-fw apply` | Aggiorna subito: ferma i bridge, spegne e riaccende le MCU, esegue `mcu_update` originale, riavvia i bridge, mostra il log e le nuove versioni. |

`apply` non parte se Klipper sull'host esterno è attivo. Lo verifica tramite Moonraker con `--moonraker http://<host>:7125` o con `MOONRAKER_URL=` in `/mnt/UDISK/.k2openhost/host.conf`; altrimenti serve `--host-stopped`. Chiede di scrivere `flash`. Dopo, riavvia Klipper.

**Il CFS viene scaricato ma non aggiornato.** Il percorso originale aggiorna il CFS solo con `/tmp/cfs_update.json`, scritto dal server OTA di Creality (sembra elencare le unità CFS per UUID). Il formato esatto non è stato ricostruito, e tirarlo a indovinare per un'operazione di scrittura non è accettabile.

Provato solo offline: l'estrazione coincide byte per byte con `unsquashfs`, e `list`, `download` (1.1.7.0 dal CDN Creality), `status`, `stage` e `unstage` sono stati eseguiti con il Python 3.9 del T113 in un chroot sul CM5. `apply` non è ancora stato eseguito su una stampante.

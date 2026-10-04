# Bootstrap T113 di K2-OpenHost

[English](README.md) · **Italiano**

> [!WARNING]
> **Solo per utenti esperti, a proprio rischio.** K2-OpenHost invalida la garanzia del produttore e può danneggiare la stampante in modo irreparabile, mandare in brick il firmware o, in caso di malfunzionamento, causare un incendio. Gli autori non si assumono alcuna responsabilità per danni a cose o persone.
> In modalità OpenHost le **telecamere dell'ugello e della camera** non possono essere gestite dal T113 e vanno ricablate direttamente sull'host Linux esterno; la **porta USB esterna** della stampante non può essere usata per stampare e smette completamente di funzionare in modalità gadget.
> Leggi l'[esclusione di responsabilità e i limiti hardware](https://github.com/MzTechnology97/K2-OpenHost/blob/main/docs/it/DISCLAIMER.md) prima di usarlo.

> **Stato: costruito e provato offline, non ancora avviato su una stampante.** Ogni parte descritta qui è stata verificata sul CM5 di riferimento: build, confronti file per file, binari ARM e Python della stampante in un chroot, download reali da Creality e GitHub. La scrittura dello slot B, il suo avvio e l'aggiornamento delle MCU non sono ancora stati eseguiti sull'hardware.

> [!IMPORTANT]
> **Versione del firmware.** Questo lavoro è stato preparato e provato sul firmware originale della K2 Pro **1.1.0.94**, la versione della stampante di riferimento. Le versioni Creality più recenti sono accettate: lo slot B viene costruito solo se gli script di avvio che modifica sono identici a quelli verificati (vale per la 1.1.7.0), e l'installer avvisa e chiede conferma. **Su firmware diversi dalla 1.1.0.94 il corretto funzionamento del bootstrap e della modalità USB gadget (OTG) del T113 non è garantito.**

Questo repository fa parte di [K2-OpenHost](https://github.com/MzTechnology97/K2-OpenHost):

| Repository | Ruolo |
| --- | --- |
| **k2-openhost-t113-bootstrap** (questo) | Il lato stampante: il sistema dello slot B per il T113, il suo installer, `k2oh-slot`, `k2oh-setup`, `k2oh-mcu-fw`. |
| [k2-openhost-installer-helper](https://github.com/MzTechnology97/k2-openhost-installer-helper) | L'host esterno. Il suo menu (sezione T113) clona questo repository ed esegue tutto il bootstrap via SSH. |
| [kalico-k2pro](https://github.com/MzTechnology97/kalico-k2pro) | Kalico per la K2 Pro sull'host esterno. |
| [k2-pro-custom-firmware](https://github.com/MzTechnology97/k2-pro-custom-firmware) | Fork del firmware K2 di Jacob10383: sorgente e storia degli extra K2; rimanda qui per il lato T113 di OpenHost. |
| [k2-openhost-firmware-tools](https://github.com/MzTechnology97/k2-openhost-firmware-tools) | Ricerca sul firmware delle periferiche e sonde in sola lettura (protocolli, formato di `cfs_update.json`). |

Il bootstrap trasforma la scheda T113 della stampante in un bridge K2-OpenHost pronto all'uso:
- gadget USB con i tre bus della K2;
- HelixScreen sullo schermo della stampante, collegato al Moonraker dell'host esterno;
- uno strumento manuale per aggiornare il firmware Creality di MCU, motori e CFS.

Va nello **slot B**. Lo **slot A**, il sistema che la stampante usa oggi, non viene mai scritto e resta a un comando o a uno spegnimento di distanza.

## Indice

1. [Come funziona](#come-funziona)
2. [Requisiti](#requisiti)
3. [Installazione passo per passo](#installazione-passo-per-passo)
4. [Avvio di prova, conferma, ritorno](#avvio-di-prova-conferma-ritorno)
5. [Cosa gira nello slot B](#cosa-gira-nello-slot-b)
6. [Aggiornare il firmware di MCU, motori e CFS](#aggiornare-il-firmware-di-mcu-motori-e-cfs)
7. [Perché lo strumento Creality e non quello di Jacob](#perché-lo-strumento-creality-e-non-quello-di-jacob)
8. [Risoluzione dei problemi](#risoluzione-dei-problemi)
9. [Rimozione](#rimozione)
10. [Riferimento](#riferimento)

## Come funziona

Il T113 ha due slot di sistema: due partizioni del kernel (`bootA`, `bootB`) e due filesystem di root (`rootfsA`, `rootfsB`). Gli aggiornamenti OTA di Creality scrivono lo slot inattivo e cambiano due variabili di U-Boot, `boot_partition` e `root_partition`. Il bootstrap usa esattamente lo stesso meccanismo.

```text
                          eMMC del T113
 ┌───────────┬───────────┬─────────────┬─────────────┬──────────────┬────────────────────┐
 │ bootA     │ bootB     │ rootfsA     │ rootfsB     │ rootfs_data  │ UDISK (27 GB)      │
 │ kernel    │ kernel    │ sistema     │ sistema     │ modifiche    │ condivisa: dati    │
 │ originale │ originale │ originale   │ K2-OpenHost │ dello slot A │ slot A+.k2openhost │
 └───────────┴───────────┴─────────────┴─────────────┴──────────────┴────────────────────┘
   slot A ─────────────────── non toccato ────────────────────┘         livello scrivibile
                                                                        dello slot B
```

Lo slot B è un **sistema Creality originale**: di default la stessa versione dello slot A, altrimenti l'ultima dell'indice Creality o quella che scegli. Viene scaricato dal CDN Creality sul tuo host e modificato solo dove serve a K2-OpenHost. Questo progetto non ridistribuisce nessun file Creality.

Lo slot B tiene il suo livello scrivibile in `/mnt/UDISK/.k2openhost/overlay`:
- non monta, non controlla e non formatta mai `rootfs_data` dello slot A;
- non formatta, non controlla e non cancella mai UDISK.

Tutta l'installazione parte dall'host esterno (`helper.sh`, menu **T113**), via SSH verso la stampante:

```text
host esterno (helper.sh)                               T113 della stampante, slot A attivo
 1. chiede l'IP della stampante, trova il proprio
 2. controlla stampante e slot A via SSH (sola lettura) ▶ modello K2 Pro, slot, U-Boot, versione
 3. scarica l'OTA Creality (versione dello slot A), verifica l'MD5
 4. costruisce bootB.img + rootfsB.squashfs
 5. scarica HelixScreen per la K2
 6. carica tutto, verifica gli SHA-256 ───────────────▶ /mnt/UDISK/k2oh-slotb
 7. lancia install-slot-b.sh ─────────────────────────▶ salva env e vecchio slot B,
                                                         scrive lo slot B, lo rilegge,
                                                         salva IP host, Wi-Fi, chiavi SSH
 8. avvio di prova ───────────────────────────────────▶ avvia lo slot B una volta
                                                         primo avvio: installa HelixScreen
```

## Requisiti

| Cosa | Dettaglio |
| --- | --- |
| Stampante | **Solo Creality K2 Pro** (modello Creality `F012`, scheda `CR0CN200400C10`, verificati sulla stampante), slot A con firmware originale (preparato e provato sulla **1.1.0.94**; versioni più recenti accettate con avviso, senza garanzia), accesso root SSH attivo (password originale `creality_2024`). |
| Rete | Stampante e host sulla stessa rete (Ethernet o Wi-Fi) per l'installazione. Poi HelixScreen usa la rete per raggiungere Moonraker. |
| Host esterno | Installato con questo helper (Kalico, Moonraker, Mainsail), basato su Debian, con internet, circa 1 GB libero. |
| Cavo | Porta Micro-USB di servizio della stampante verso una porta USB dell'host. |
| Telecamere | Collegate all'host (in modalità gadget non possono passare dal T113). |
| UDISK della stampante | Circa 1,5 GB liberi (backup del vecchio slot B, immagini, HelixScreen). |

## Installazione passo per passo

1. **Sulla stampante:** attiva l'accesso root dalle impostazioni dello schermo se serve, e annota il suo indirizzo IP (schermo: impostazioni di rete).
2. **Sull'host**, nella cartella dell'helper:

   ```bash
   ./helper.sh
   ```

   scegli **23) Install the T113 bootstrap** (oppure `./helper.sh t113 install`).
3. **Conferma** l'avviso, poi inserisci:
   - l'**IP della stampante**;
   - l'**IP dell'host** come lo vede la stampante. L'helper propone l'indirizzo dell'interfaccia che raggiunge la stampante: premi Invio per accettarlo.

   Entrambi vengono salvati in `~/.k2-openhost-installer-helper/t113.conf`.
4. **Accedi** con la password di root della stampante quando richiesto. La connessione SSH resta aperta, quindi la scrivi una volta sola.
5. L'helper **controlla la stampante** (sola lettura):
   - deve essere una **Creality K2 Pro**: modello `F012` e scheda `CR0CN200400C10`, letti dalla stampante stessa;
   - lo slot A deve essere quello attivo e l'ambiente di avvio deve puntare su di esso;
   - la versione del firmware dello slot A viene letta e mostrata.

   Se una sola condizione non è rispettata l'installazione si ferma prima di scrivere qualsiasi cosa. `install-slot-b.sh` ripete gli stessi controlli sulla stampante, e `k2oh-mcu-fw` si rifiuta di funzionare su altri modelli.
6. Propone la **versione Creality da cui costruire lo slot B**: quella dello slot A se Creality la elenca ancora, altrimenti l'ultima; puoi scriverne un'altra. Una versione diversa dalla 1.1.0.94 mostra un avviso (bootstrap e modalità OTG non garantiti) e richiede conferma. Se la versione è diversa da quella dello slot A, ogni slot riscrive le schede con i propri file all'avvio.
7. Sull'host installa `fakeroot` e `squashfs-tools` (sudo), clona questo repository e **scarica quell'OTA Creality** (130–145 MB) dal CDN Creality. Controlla kernel e rootfs con l'elenco MD5 contenuto nell'immagine, poi **costruisce lo slot B**. La build si ferma se manca una delle modifiche previste o se gli script di avvio originali che lo slot B modifica sono diversi da quelli verificati.
8. Rispondi **sì** per installare HelixScreen (consigliato): l'helper scarica da GitHub l'ultima versione per la K2.
9. I file vengono **caricati** in `/mnt/UDISK/k2oh-slotb` sulla stampante e verificati con SHA-256.
10. Sulla stampante parte `install-slot-b.sh --check`: non viene ancora scritto nulla.
11. **Conferma** per scrivere lo slot B. La stampante:
    - salva l'ambiente U-Boot e il vecchio slot B in `/mnt/UDISK/.k2openhost/backup/<data>/`;
    - scrive `bootB` e `rootfsB` e li rilegge;
    - prepara il livello scrivibile dello slot B: copia le `authorized_keys` SSH e le reti Wi-Fi salvate dello slot A, salva l'IP dell'host in `/mnt/UDISK/.k2openhost/k2openhost.conf` e tiene l'archivio di HelixScreen per il primo avvio.
12. Lo slot A resta quello di avvio predefinito. Prosegui con l'avvio di prova.

## Avvio di prova, conferma, ritorno

| Azione | Menu | Comando | Cosa fa |
| --- | --- | --- | --- |
| Avvio di prova | 25 | `./helper.sh t113 boot-b` | Imposta lo slot B per il prossimo avvio come prova e riavvia la stampante. |
| Tenere lo slot B | 26 | `./helper.sh t113 commit` | Da lanciare quando lo slot B funziona: diventa quello predefinito. |
| Tornare allo slot A | 27 | `./helper.sh t113 boot-a` | Slot A al prossimo avvio, poi riavvio. |
| Stato | 24 | `./helper.sh t113 status` | Slot attivo, prossimo avvio, prova, setup, HelixScreen. |

**Come ti protegge l'avvio di prova:** all'inizio dell'avvio dello slot B, prima di qualsiasi servizio, l'ambiente di avvio viene già riportato sullo slot A. Se lo slot B si blocca, va in errore o non riesci a raggiungerlo, **spegni e riaccendi la stampante e torna allo slot A**. Solo `commit`, eseguito su uno slot B funzionante, lo rende predefinito.

Sulla stampante le stesse azioni sono `k2oh-slot status | boot-b | commit | boot-a` (dallo slot A: `/mnt/UDISK/.k2openhost/bin/k2oh-slot`).

Dopo l'avvio di prova:

1. Collega il cavo Micro-USB di servizio all'host, se non lo è già.
2. Controlla che Klipper sull'host si colleghi (Mainsail mostra la stampante pronta). L'host aspetta fino a 60 s i tre canali gadget.
3. Controlla lo schermo: al primo avvio viene installato HelixScreen (circa un minuto), già puntato sul tuo host.
4. Esegui **26) Keep slot B**.

## Cosa gira nello slot B

| Parte | Dettaglio |
| --- | --- |
| `k2oh-gadget` | Mette la USB0 in modalità device e crea tre funzioni Generic Serial (`0525:a4a6`, interfacce 00/01/02), come si aspettano le regole udev dell'host. |
| `k2oh-bridge` | Un processo bridge per bus, riavviato da procd: `ttyGS0↔ttyS2` Main MCU, `ttyGS1↔ttyS3` Nozzle MCU, `ttyGS2↔ttyS5` RS-485/CFS/motori, 230400 8N1. È il bridge validato sulla stampante di riferimento. |
| `mcu_update` (originale) | Resta: a ogni avvio avvia le applicazioni di Main e Nozzle MCU (si accendono nel loader Creality), e riscrive ogni scheda la cui versione è diversa dai file firmware dello slot B. |
| `k2oh-wifi` | Avvia `wpa_supplicant` e `udhcpc` come faceva il `wifi-server` Creality, con le reti copiate dallo slot A. L'Ethernet funziona come nell'originale. |
| `k2oh-firstboot` / `k2oh-setup` | Primo avvio: installa HelixScreen dall'archivio preparato e lo collega a `HOST_IP:7125`. Riprova a ogni avvio finché non riesce. `k2oh-setup --host <IP>` cambia l'host in seguito (menu 28). |
| HelixScreen | L'interfaccia touch sullo schermo della stampante, collegata al Moonraker dell'host. |
| Disattivati | Klipper, klipper_mcu, Moonraker e nginx Creality, app di interfaccia e cloud (`app`), ADB (prenderebbe il controller USB), telecamera WebRTC, OTA da chiavetta (un OTA dallo slot B sovrascriverebbe lo slot A), ripristino di fabbrica `wipe_data` (cancella quasi tutto UDISK). |
| `chamber_cam_power.sh` | Non fa nulla: sulla K2 Pro il suo `restart` riporta la USB0 in modalità host e fa cadere tutti e tre i canali. |
| Protetti | `rootfs_data` dello slot A non viene mai montata, controllata o formattata. UDISK viene solo montato (niente `mkfs`, niente `e2fsck`, `parts_clean` ignorato). |

La password di root dello slot B è quella originale (`creality_2024`), anche se hai cambiato quella dello slot A.

## Aggiornare il firmware di MCU, motori e CFS

Gli aggiornamenti del firmware sono **manuali, apposta**. Si eseguono dallo slot B, a stampante ferma.

### La via breve: ultima versione

Dall'host: voce **30) Update MCU firmware** (`./helper.sh t113 mcu-fw update`), oppure sulla stampante:

```sh
k2oh-mcu-fw update          # aggiungi --cfs per includere le unità CFS
```

Cerca l'**ultima** versione nell'indice Creality, la scarica (tiene solo i file firmware), la prepara nello slot B, mostra quali schede cambierebbero e chiede **"Flash the boards now?"**. Se rispondi no non viene scritto nulla adesso: i file preparati vengono scritti al prossimo avvio dello slot B, oppure con `k2oh-mcu-fw apply`, oppure scartati con `k2oh-mcu-fw unstage`. Se rispondi sì esegue `apply` con tutti i suoi controlli (prima ferma Klipper sull'host).

### Cosa si aggiorna

Il set firmware della K2 Pro in una versione Creality (`/usr/share/klipper/fw/F012` e `fw/cfs`):

| Scheda | Bus | File di esempio (1.1.7.0) |
| --- | --- | --- |
| Main MCU | ttyS2, diretto | `mcu0_120_G32-mcu0_001_000.bin` |
| Nozzle MCU | ttyS3, diretto | `noz0_130_G30-noz0_021_000.bin` |
| Motore estrusore | attraverso la scheda ugello | `mot2_022_C30-mot2_002_081.bin` |
| Motori X/Y closed-loop | RS-485 | `motor/mot2_023_C30-mot2_002_081.bin` |
| Schede nastro e RFID | RS-485 | `belt/…`, `rfid/rfd0_010_G21-rfd0_000_010.bin` |
| Unità CFS | RS-485 | `cfs/cfs0_050_G32-cfs0_000_153.bin` (un file per variante hardware) |

### Passo per passo

Sulla stampante (`ssh root@<stampante>`), oppure dall'host con `./helper.sh t113 mcu-fw <comando>`:

1. **Guarda cosa ha rilasciato Creality:**

   ```sh
   k2oh-mcu-fw list
   ```

   Legge l'indice firmware pubblico di Creality: niente account, nessun dato della stampante inviato.
2. **Scarica una versione** (di default l'ultima):

   ```sh
   k2oh-mcu-fw download 1.1.7.0
   ```

   - L'immagine OTA (circa 145 MB) arriva dal CDN Creality.
   - Il suo rootfs viene controllato con l'elenco MD5 contenuto nell'immagine e letto direttamente: il T113 non ha dispositivi loop, non viene montato nulla.
   - Si tengono solo i file firmware, in `/mnt/UDISK/.k2openhost/mcu-fw/1.1.7.0/` con un manifest SHA-256, e l'immagine viene cancellata.
3. **Preparala:**

   ```sh
   k2oh-mcu-fw stage 1.1.7.0
   k2oh-mcu-fw status
   ```

   Sostituisce i file firmware dello slot B ed elenca le schede che cambierebbero.
4. **Ferma Klipper sull'host:**

   ```bash
   sudo systemctl stop klipper
   ```

   Durante l'aggiornamento l'alimentazione delle MCU viene spenta e riaccesa.
5. **Aggiorna:**

   ```sh
   k2oh-mcu-fw apply            # Main, Nozzle, estrusore, motori, nastro, RFID
   k2oh-mcu-fw apply --cfs      # lo stesso, poi le unità CFS
   ```

   `apply` non parte se il Moonraker dell'host indica Klipper `ready` o `startup` (legge `MOONRAKER_URL` da `k2openhost.conf`), e chiede di scrivere `flash`. Poi:
   1. ferma i bridge;
   2. spegne e riaccende le MCU (`mcu_reset.sh`);
   3. esegue `mcu_update` di Creality;
   4. con `--cfs` esegue il passaggio CFS descritto sotto;
   5. riavvia i bridge e mostra il log e le nuove versioni.
6. **Riavvia Klipper sull'host:**

   ```bash
   sudo systemctl start klipper
   ```

   `k2oh-mcu-fw unstage` rimette i file originali dello slot B.

**Nota:** lo slot A riscrive i file della sua versione al suo prossimo avvio, perché lo script originale aggiorna a ogni differenza di versione. Avviare lo slot A dopo un aggiornamento riporta le schede alla versione precedente.

### Come funziona il passaggio CFS

Lo strumento Creality aggiorna un CFS solo se è elencato in `/tmp/cfs_update.json`. Il formato è stato ricostruito da `mcu_util_485`:

```json
{"CFSs": [{"uuid": "xx xx xx xx xx xx xx xx xx xx xx xx", "fw": "/usr/share/klipper/fw/cfs/cfs0_050_G32-cfs0_000_153.bin"}]}
```

- `uuid` è l'identificativo unico (UniID) a 12 byte dell'unità, in esadecimale minuscolo separato da spazi. Lo strumento confronta esattamente i primi 35 caratteri.
- `fw` è il file che apre.

`apply --cfs` non tira mai a indovinare nessuno dei due valori:

1. Il primo passaggio (punto 5) spegne e riaccende le MCU. Lo strumento Creality trova ogni CFS nel suo loader e scrive UniID e identità del loader (`cfs0_050_G32-cfs0_000_113`) in `/tmp/.485_mcu_version`.
2. Per ogni unità, `k2oh-mcu-fw` sceglie il file con la **variante hardware esattamente corrispondente**. È importante: nella 1.1.7.0 le varianti G30 e G32 hanno firmware diversi (150 e 153). Le unità senza esattamente un file corrispondente, o già aggiornate, vengono saltate.
3. Scrive `/tmp/cfs_update.json`, spegne e riaccende di nuovo ed esegue `CFS=1 mcu_update`, come fa il server OTA Creality. `mcu_util_485` scrive solo sulle unità il cui UniID coincide.

Se il primo passaggio non trova nessun CFS in modalità loader, non viene scritto nulla. Un CFS rimasto in modalità loader viene riavviato dallo stack Box di Kalico (`box_addr`) al successivo avvio di Klipper.

## Perché lo strumento Creality e non quello di Jacob

Il `motor_updater.py` di Jacob10383 è una reimplementazione aperta e accurata degli stessi protocolli, e un ottimo riferimento. Per la K2 Pro lo slot B usa gli strumenti Creality:

- **Sono gli strumenti validati per questo hardware.** `mcu_util`, `mcu_util_485` e `/etc/init.d/mcu_update` sono nel firmware della K2 Pro e girano a ogni avvio e a ogni OTA originale. Usarli riproduce esattamente un aggiornamento ufficiale, compresi i suoi comportamenti noti in caso di errore e di ripristino.
- **Sono già nello slot B**, alla stessa versione dello slot A: i due slot aggiornano allo stesso modo e non c'è codice in più da mantenere.
- **Corrispondono alla topologia della K2 Pro.** `motor_updater.py` è pensato per stampanti "K2/K2-Plus":
  - si aspetta quattro motori RS-485, mentre la K2 Pro ne ha due più l'estrusore che passa dalla scheda ugello;
  - salta le schede nastro e RFID;
  - gestisce l'alimentazione (`gpio140`, "kernel boots with rail OFF") secondo il kernel di Jacob, non quello originale.
- **Gestiscono il CFS come fa Creality**, con `cfs_update.json` e la sequenza originale di spegnimento e riaccensione, più la scelta esatta della variante hardware descritta sopra.

Cosa manca agli strumenti Creality: sono binari chiusi, registrano meno informazioni e riscrivono a ogni differenza, anche verso versioni più vecchie. `motor_updater.py` dà un controllo più fine (`--versions-only`, `--one <uuid>`). Resta un'opzione da valutare più avanti, anche insieme al lavoro di K2-OpenHost Firmware Tools.

## Risoluzione dei problemi

| Sintomo | Cosa fare |
| --- | --- |
| La stampante non torna dopo l'avvio di prova | Spegni e riaccendi: torna allo slot A. Dallo slot A guarda `/mnt/UDISK/.k2openhost/setup.log`. |
| Klipper sull'host non si collega | `./helper.sh doctor` controlla i tre canali. Sulla stampante: `logread \| grep -E "k2oh\|bridge"`, `cat /sys/kernel/config/usb_gadget/g1/UDC`. |
| Lo schermo resta sul logo di avvio | `k2oh-setup status`, `cat /mnt/UDISK/.k2openhost/setup.log`; rilancia `k2oh-setup`. |
| HelixScreen non raggiunge Moonraker | IP dell'host sbagliato: menu 28 o `k2oh-setup --host <IP>`. Verifica che la stampante raggiunga l'host sulla porta 7125. |
| Nessuna rete nello slot B via Wi-Fi | Lo slot A non aveva reti salvate, o sono state aggiunte dopo: imposta il Wi-Fi da HelixScreen, oppure copia `/etc/wifi/wpa_supplicant/wpa_supplicant.conf`. |
| `apply` si rifiuta di partire | Ferma Klipper sull'host (`sudo systemctl stop klipper`). |
| Un aggiornamento si è interrotto a metà | Rilancia `k2oh-mcu-fw apply`: lo strumento Creality ricomincia ogni trasferimento dall'inizio. Leggi `/tmp/mcu_update.log`. |

## Rimozione

1. `./helper.sh t113 boot-a` (menu 27): la stampante torna allo slot A come prima.
2. Facoltativo, dallo slot A: `rm -rf /mnt/UDISK/.k2openhost` cancella livello scrivibile, backup e firmware scaricati dello slot B. Le partizioni dello slot B restano com'erano finché un OTA Creality non le riscrive.

## Riferimento

### File di questa cartella

| File | Gira su | Cosa fa |
| --- | --- | --- |
| `build-slot-b.sh` | host | Costruisce `bootB.img` e `rootfsB.squashfs` da `kernel` e `rootfs` originali; avvisa sulle versioni diverse dalla 1.1.0.94 e si rifiuta se gli script di avvio originali che modifica sono diversi (`--force-preinit` per forzare dopo una verifica). |
| `fetch-stock-ota.py` | host | Elenca le versioni Creality, ne scarica una (o l'ultima), verifica l'MD5, tiene `kernel` e `rootfs`. |
| `install-slot-b.sh` | stampante, slot A | `--check` / scrittura dello slot B, backup, file di setup. |
| `rootfs/` | — | File aggiunti al filesystem originale. |
| [`scripts/t113.sh`](https://github.com/MzTechnology97/k2-openhost-installer-helper/blob/main/scripts/t113.sh) (installer helper) | host | I comandi T113 dell'helper; clona questo repository in `~/k2-openhost-t113-bootstrap`. |

### Percorsi sulla stampante

| Percorso | Contenuto |
| --- | --- |
| `/mnt/UDISK/.k2openhost/overlay/` | Livello scrivibile dello slot B. |
| `/mnt/UDISK/.k2openhost/k2openhost.conf` | `HOST_IP`, `MOONRAKER_URL`, archivio HelixScreen. |
| `/mnt/UDISK/.k2openhost/setup.log` | Log del setup al primo avvio. |
| `/mnt/UDISK/.k2openhost/backup/<data>/` | Ambiente U-Boot e slot B precedente. |
| `/mnt/UDISK/.k2openhost/mcu-fw/<versione>/` | Set firmware scaricati. |
| `/mnt/UDISK/.k2openhost/bin/k2oh-slot` | Cambio slot, usabile dallo slot A. |

### Costruzione a mano

```bash
python3 fetch-stock-ota.py --list                 # versioni nell'indice Creality
python3 fetch-stock-ota.py 1.1.0.94 stock         # oppure "latest"
./build-slot-b.sh --kernel stock/kernel --rootfs stock/rootfs --base-version 1.1.0.94 --out out
```

`build-slot-b.sh` richiede `fakeroot` e `squashfs-tools`. Funziona anche senza root: `apt-get download squashfs-tools && dpkg -x squashfs-tools_*.deb tools`, poi `--tools tools/usr/bin`.

### Cosa è stato provato

| Prova | Risultato |
| --- | --- |
| Elenco file dello slot B rispetto allo squashfs originale | solo le modifiche previste; tutti gli altri file identici, permessi compresi |
| Download dell'OTA originale dal CDN Creality | MD5 di kernel e rootfs 1.1.0.94 identici alla base validata |
| Versione più recente 1.1.7.0 | script di avvio modificati dallo slot B identici alla 1.1.0.94, stessi servizi, kernel 5.4.61 con gadget seriale e gestore OTG; lo slot B si costruisce con l'avviso "non provata". Non avviato. |
| Script con BusyBox e Python 3.9 della stampante (chroot) | controlli di sintassi superati |
| Bridge con pseudo-terminali | 10 KB binari nei due sensi, 0 CPU a riposo, arresto pulito |
| Estrazione di `k2oh-mcu-fw` rispetto a `unsquashfs` | 15 file firmware identici byte per byte |
| `k2oh-mcu-fw list/download/stage/unstage/status` | 1.1.7.0 scaricata da Creality, preparata e ripristinata |
| Protezione di `apply` | rifiutato con il Klipper dell'host attivo |
| Piano CFS con unità simulate | variante esatta scelta; unità aggiornate, non valide e sconosciute saltate |
| `k2oh-setup` con il vero installer HelixScreen (chroot) | HelixScreen installato, host Moonraker impostato; l'avvio del servizio richiede il sistema reale |
| Controllo del modello (K2 Pro `F012`, scheda `CR0CN200400C10`) | letto dalla stampante di riferimento in sola lettura |
| Scrittura dello slot B, avvio di prova, aggiornamento | **non ancora eseguiti sull'hardware** |

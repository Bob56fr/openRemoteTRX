# 2. Instalar la estación

La instalación nunca controla el transceptor: puede quedarse encendido y conectado. Elige tu sistema en las pestañas
de abajo; la elección vale para toda la página. Al final, **openRemoteTRX Console** se abre y propone el asistente de
configuración: es la parte 3.

<!-- onglets -->
#### Debian

**Debian 12 o 13, con escritorio.**

1. Descarga `trx-remote-debian-X.Y.Z.zip` (parte 0) en **Descargas**, clic derecho > «Extraer aquí».
2. En la carpeta obtenida: clic derecho en una zona vacía > «Abrir en un terminal», luego:

   ```
   sudo bash install.sh
   ```

   Se pide tu contraseña de sesión (no se muestra nada al teclear: es normal). El script instala
   Hamlib, Python, los módulos, la cuenta de servicio y los servicios de la estación.
3. Al final, **cierra la sesión y vuelve a entrar** (los permisos de tu cuenta cambian).
4. Abre **openRemoteTRX Console** desde el menú de aplicaciones (o teclea `trx-console` en un terminal).

**Hamlib y los transceptores recientes.** Debian 13 incluye Hamlib 4.6, que no conoce los transceptores recientes (IC-7300MK2…):
`install.sh` instala por sí solo la versión 4.7 de los **backports oficiales** de Debian. En Debian 12, si tu transceptor
falta en `rigctl -l`, la instalación te lo dice: lanza entonces `sudo bash compiler-hamlib.sh` en la misma carpeta
(compilación del último Hamlib, de 10 a 30 minutos).

**Sin escritorio (servidor)**, todo se hace por SSH: copia el zip, luego

```
unzip -q trx-remote-debian-*.zip && cd trx-remote-debian-*/ && sudo bash install.sh
```

cierra la conexión SSH, vuelve a conectarte y teclea `trx-console`.

#### Raspberry Pi

**Raspberry Pi 4 o 5, Raspberry Pi OS de 64 bits.** La Pi usa el **mismo paquete** que Debian.

> **La Pi como estación.** Ya en servicio en casa de un probador beta, pero su carga todavía no se ha medido con todo en
> marcha (receptor SDR, FreeDV, varios visitantes): empieza por las funciones básicas. Una Pi 3 o más antigua
> es demasiado lenta para el audio en directo.

**El hardware.**

| Elemento | Consejo |
|---|---|
| La Pi | Pi 4 con **4 GB** (2 GB como mínimo), o Pi 5 |
| Alimentación | la fuente **oficial** (Pi 4: USB-C 5,1 V 3 A; Pi 5: 5 V 5 A). Un cargador de teléfono provoca subtensiones: la Pi se ralentiza y el USB del transceptor se desconecta |
| Refrigeración | disipador con ventilador, o caja ventilada: sin ella, la Pi se ralentiza hacia 80 °C |
| Almacenamiento | tarjeta SD de 32 GB «High Endurance» clase A2, o mejor un **SSD en USB 3** (la Pi arranca desde él, y dura más que una tarjeta que escribe día y noche) |
| Red | cable Ethernet aconsejado; el Wi-Fi funciona, con más cortes del audio |

**1. Preparar la tarjeta**, en tu PC, con **Raspberry Pi Imager** (raspberrypi.com/software):

1. Dispositivo: tu modelo de Pi. Sistema: **Raspberry Pi OS (64-bit)** si una pantalla va a quedar conectada; si no,
   *Raspberry Pi OS (other)* > **Raspberry Pi OS Lite (64-bit)**, sin escritorio, todo se hará desde tu PC.
2. Personalización, **antes** de escribir la tarjeta: un nombre (por ejemplo `trx-pi`), una cuenta y su **contraseña**
   (imprescindible para instalar), la zona horaria y el teclado, el Wi-Fi solo si no hay cable, y **SSH
   activado** (preferentemente con clave pública).
3. Escribe la tarjeta, ponla en la Pi, conecta la red, el transceptor y luego la alimentación. El primer arranque tarda
   de 2 a 3 minutos (la Pi se reinicia una vez sola).
4. Busca la dirección de la Pi en la lista de dispositivos de tu router y **resérvala** (reserva DHCP, parte 4.1).

**2. Actualizar el sistema**, en un terminal de la Pi (con escritorio) o desde tu PC (sin escritorio:
`ssh -l <cuenta> <direccion-del-pi>`):

```
sudo apt update && sudo apt full-upgrade -y && sudo reboot
```

**3. Instalar la estación.**

- **Con escritorio**: exactamente como en Debian (pestaña Debian): zip descargado y extraído, `sudo bash install.sh`
  en un terminal abierto en la carpeta, luego cerrar sesión y volver a entrar.
- **Sin escritorio**, desde tu PC (PowerShell en Windows, terminal en Linux o macOS), en la carpeta del zip
  descargado:

  ```
  scp -o User=<cuenta> trx-remote-debian-X.Y.Z.zip <direccion-del-pi>:
  ssh -t -l <cuenta> <direccion-del-pi>
  ```

  luego, en la Pi:

  ```
  sudo apt install -y unzip
  unzip -q trx-remote-debian-X.Y.Z.zip && cd trx-remote-debian-X.Y.Z && sudo bash install.sh
  ```

  Al final, teclea `exit` y vuelve a conectarte (`ssh -t -l <cuenta> <direccion-del-pi>`): los permisos de tu cuenta han
  cambiado. Luego `trx-console`.

**Lo que la instalación hace además en una Pi.**

- Muestra el modelo y señala una Pi demasiado antigua, una memoria demasiado pequeña o una **subtensión** (alimentación
  demasiado débil): corrige antes de seguir.
- Raspberry Pi OS 13 incluye Hamlib 4.6: instala la 4.7 de los backports oficiales de Debian (transceptores recientes como
  el IC-7300MK2). En Raspberry Pi OS 12, si tu transceptor falta en `rigctl -l`: `sudo bash compiler-hamlib.sh` (de 10
  a 30 minutos en una Pi).
- Pone en marcha el **watchdog de hardware** de la Pi: si el sistema se bloquea más de 15 segundos, la Pi
  se reinicia sola, y la estación vuelve a arrancar en recepción.
- Con escritorio, añade la fuente de los pictogramas de openRemoteTRX Console.

**4. Comprobar la alimentación y la temperatura**, tras unos minutos de funcionamiento:

```
vcgencmd get_throttled; vcgencmd measure_temp
```

Esperado: `throttled=0x0` y menos de 70 °C. Cualquier otro valor de `throttled` = alimentación demasiado débil o
sobrecalentamiento: cambia la alimentación o añade un ventilador. Una vez la estación en marcha, su supervisor
te enviará una alerta (parte 6) si la Pi se ralentiza, si la memoria o el disco se llenan.

<details>
<summary>Trabajar sin pantalla a diario</summary>

- **openRemoteTRX Console por SSH**: `ssh -t -l <cuenta> <direccion-del-pi> trx-console` (el `-t` es imprescindible:
  la consola hace preguntas). Windows Terminal muestra bien los marcos, los colores y el código QR del menú 4.1.
- **Más cómodo: la consola en el navegador.** Una vez, menú **4.6** (parte 7.5); después
  `https://<direccion-del-pi>:8444/` desde el PC, la tableta o el teléfono, sin SSH.
- **Panel**: `ssh -t -l <cuenta> <direccion-del-pi> trx-monitor`, o el panel de constantes vitales
  en el navegador (parte 7.1).
- **Apagar la Pi**: `sudo poweroff`, luego espera a que el LED verde deje de parpadear antes de cortar
  la alimentación (un corte brusco puede dañar la tarjeta SD).

</details>

#### Windows

**Windows 10 u 11, 64 bits.**

1. Instala **Hamlib de 64 bits** (`hamlib-w64-X.Y.Z.exe`, versión **4.7** o más reciente: los transceptores recientes como
   el IC-7300MK2 no existen antes) desde https://github.com/Hamlib/Hamlib/releases, en la carpeta propuesta.
2. Copia `trx-remote-windows-X.Y.Z.zip` en el PC. Clic derecho > Propiedades > marca **Desbloquear** > Aceptar.
3. Clic derecho > Extraer todo, luego doble clic en **`installer.cmd`**. Si Windows muestra «Windows protegió
   su PC»: Más información > Ejecutar de todas formas.
4. Acepta la petición de administrador y responde a las preguntas (Python se instala si falta, con tu acuerdo).
5. Ajustes de Windows imprescindibles:
   - red de casa con perfil **Privado** (el cortafuegos solo abre la estación en las redes privadas);
   - **suspensión e hibernación desactivadas** (Configuración > Sistema > Energía);
   - *Configuración > Privacidad > Micrófono*: acceso permitido a las aplicaciones de escritorio (si no, el audio recibido del
     transceptor es un silencio);
   - tarjeta de sonido del transceptor (*Configuración > Sistema > Sonido*, salida «Altavoces» del transceptor): **volumen a 100**,
     **mejoras de audio desactivadas**, formato 16 bits 48000 Hz; el nivel de transmisión se dosifica en el transceptor (Icom:
     USB MOD Level). Un volumen reducido (38 visto en un PC) da una transmisión sin potencia. Su nombre («2- USB Audio
     Device»…) cambia si el cable del transceptor pasa a otra toma USB: rehacer entonces el menú 2.6.

El manual completo (`notice-windows.html`) está en el paquete.

**openRemoteTRX Console en Windows.** La instalación crea **un solo acceso directo**: menú Inicio >
**openRemoteTRX**. Abre openRemoteTRX Console, con los mismos menús numerados que en Debian: esta guía
se aplica tal cual (1.1 arrancar, 2.1 configuración, 6.1 diagnóstico…). Diferencias:

- **Actualizaciones** (menús 7.1 a 7.3): en Windows, extrae el nuevo zip y lanza su `installer.cmd`; la
  configuración se conserva. Vuelta atrás: vuelve a lanzar el `installer.cmd` de la versión anterior.
- **Indicador junto al reloj**: menú 8.4 (lanzarlo, o lanzarlo en cada inicio de sesión).
- **Desinstalar**: Configuración > Aplicaciones > **openRemoteTRX** > Desinstalar (la configuración se conserva salvo si
  pides borrarla).
- La configuración está en `C:\ProgramData\trx-remote\station.toml`; los comandos (`trx-console`, `trx-setup`,
  `trx-monitor`…) también se lanzan en un terminal abierto **después** de la instalación.
<!-- /onglets -->

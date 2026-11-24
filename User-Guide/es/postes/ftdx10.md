# Ficha del transceptor: Yaesu FTDX10

> **Preparado, todavía no validado en un transceptor real.** Ajustes sacados del *CAT Operation Reference Manual* del FTDX10
> (Yaesu, edición 2308-F), del manual del driver USB (2205-E) y de las capacidades de Hamlib. El primer operador
> que haga las pruebas de la [parte 3](../03-integrer-et-essayer-le-trx.md) valida esta ficha: gracias por
> informar del resultado.

## Identidad para la estación

| | |
|---|---|
| Número Hamlib | **1042** («FTDX10») |
| Enlace | USB, puerto «**Enhanced COM Port**», **38400** baudios |
| PTT | por **CAT** (la estación envía la orden de transmisión por el puerto USB) |
| Tarjeta de sonido | «USB Audio CODEC» (recepción y transmisión) |
| Leído por la estación | frecuencia, modo, filtros, S-metro, potencia, ALC, ROE, tensión, VFO A / B, split, clarificador |
| No disponible | espectro HF del transceptor (Yaesu no envía los datos de la pantalla por CAT: solo se muestra el espectro de audio); temperatura del transceptor (el umbral de temperatura de la estación no tiene efecto) |

## Driver USB (Windows)

1. **Cable USB desconectado.** Descarga el driver «CP210x Universal Windows Driver» (enlace en el sitio de Yaesu, o
   directamente en Silicon Labs) y descomprímelo.
2. Clic derecho en el archivo **`silabser.inf`** > (Windows 11: «Mostrar más opciones») > **Instalar**.
3. Conecta el cable USB, enciende el transceptor: Windows termina la instalación (a veces pide reiniciar). El driver
   de la tarjeta de sonido es el de Windows, nada que hacer.
4. Administrador de dispositivos > Puertos (COM y LPT): dos líneas «Silicon Labs Dual CP210x USB to UART Bridge»:
   **Enhanced COM Port (COMx)** para la estación, Standard COM Port (COMy) sin usar. Un «!» o una cruz en una
   línea: desinstala y vuelve a instalar el driver.

En Debian: ningún driver. Los nombres estables de los puertos están en `/dev/serial/by-id/` (`…CP2105…-if00-port0` =
Enhanced, `…-if01-port0` = Standard); el asistente propone directamente el correcto.

## Menús que ajustar

Rutas tal como aparecen en el menú de ajustes del transceptor (ver el manual de uso del FTDX10 para
abrirlo). Los ajustes «MODE» se hacen **para cada modo** que quieras usar en fonía.

### Enlace CAT: OPERATION SETTING > GENERAL

| Menú | Valor | Por qué |
|---|---|---|
| CAT RATE | **38400 bps** | misma velocidad que en la estación (propuesta por el asistente) |
| CAT TIME OUT TIMER | **1000 msec** | valor propuesto por el asistente |
| CAT RTS | **ENABLE** | Hamlib usa el control de flujo RTS/CTS en este transceptor |
| TX TIME OUT TIMER | **3** (minutos) | segunda seguridad del propio transceptor, más allá del tiempo máximo de la estación (90 s) |

(`232C RATE` y `232C TIME OUT TIMER` se refieren a la toma RS-232C: sin efecto por el USB.)

### Voz por el USB: RADIO SETTING > MODE SSB, MODE AM, MODE FM, MODE PSK/DATA

| Menú (en cada modo) | Valor | Por qué |
|---|---|---|
| SSB / AM / FM / DATA **MOD SOURCE** | **REAR** | la modulación viene de la parte trasera del transceptor, no del micrófono frontal |
| **REAR SELECT** | **USB** | la parte trasera = el USB (y no la toma DATA) |
| **RPTT SELECT** | **DAKY** | el PTT «trasero» se queda en la toma DATA, donde no hay nada conectado; **nunca RTS ni DTR** |
| RPORT GAIN | a ajustar (parte 3) | nivel de la voz que llega por el USB: a ajustar con el ALC |
| SSB / AM / FM / DATA OUT LEVEL | valor de fábrica | nivel de la toma RTTY/DATA trasera solamente: **sin efecto en el audio USB** (prueba del 2026-11-19). Audio recibido demasiado débil: ganancia del menú **2.9** de openRemoteTRX Console |

Sin «MOD SOURCE = REAR» en BLU, el asistente limita la transmisión a los modos de datos (DATA-U, DATA-L): la página no
podrá transmitir en USB / LSB.

> **Seguridad: RPTT SELECT y PC KEYING.** Yaesu advierte que, cuando el PTT pasa por las líneas del puerto USB, *«el
> transceptor puede pasar a transmisión al arrancar el ordenador»*. La estación no usa estas líneas: deja
> **RPTT SELECT = DAKY** en cada modo y **CW SETTING > MODE CW > PC KEYING = OFF**.

### Otros ajustes aconsejados

| Menú | Valor | Por qué |
|---|---|---|
| Tecla **VOX** del frontal | **apagada** | con la voz por el USB, un sonido parásito del PC podría hacer transmitir al transceptor |
| OPERATION SETTING > TX GENERAL > HF MAX POWER (y 50M, 70M, AM) | la potencia que te permites | límite del propio transceptor, que la estación no puede superar |
| OPERATION SETTING > TX GENERAL > EMERGENCY FREQ TX | **DISABLE** | ninguna transmisión en la frecuencia de emergencia |

## Correspondencia de los modos

| Página web / Hamlib | Pantalla del FTDX10 |
|---|---|
| USB / LSB | USB / LSB |
| PKTUSB / PKTLSB | DATA-U / DATA-L |
| FM / PKTFM | FM / DATA-FM |
| AM | AM |
| CW / CWR | CW-U / CW-L |

## Puntos que comprobar durante las pruebas (validación de esta ficha)

Para anotar en el informe de la [parte 3](../03-integrer-et-essayer-le-trx.md):

1. El diagnóstico (menú 6.1) encuentra el transceptor; frecuencia y modo siguen cuando giras el VFO.
2. Piloto **VFO A / VFO B** de la página cuando pulsas A/B en el transceptor.
3. Transmisión con carga ficticia: la página ve potencia, **ALC** y ROE; el nivel de ALC a plena voz (el umbral
   de alerta del ALC todavía no se ha medido en un Yaesu).
4. Split activado en el transceptor: la página lo muestra, la transmisión sale en la frecuencia correcta.
5. Transmisión con el micrófono del transceptor: la página muestra «operador local» y bloquea el PTT a distancia.
6. Ningún paso a transmisión al arrancar el PC ni al conectar el cable.

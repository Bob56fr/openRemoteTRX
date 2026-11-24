# Inicio rápido

Para impacientes: tu transceptor en el navegador en un cuarto de hora. El resto de la guía explica cada paso en
detalle; vuelve a ella ante el primer problema.

## Necesitas

- un transceptor conocido por Hamlib, conectado al PC: un cable USB para la mayoría de los equipos recientes (control y audio),
  si no una interfaz tipo Digirig o SignaLink;
- un PC con **Debian 12 o 13** o **Windows 10 / 11** de 64 bits, o una **Raspberry Pi 4 o 5** (Raspberry Pi OS
  de 64 bits, alimentación oficial), encendido permanentemente cerca del transceptor y conectado al router;
- una **carga ficticia** para la primera transmisión;
- un teléfono o un PC con un navegador reciente.

## 0. Primero, el TOT del transceptor (2 min)

> **Seguridad.** El **TOT** (*Time Out Timer*) es el temporizador que corta la transmisión tras un tiempo máximo.
> Ajusta el del transceptor **antes que todo lo demás**.

**¿Por qué?** A distancia, no ves tu transceptor. Si el PC de la estación se bloquea, si el cable USB se desconecta o
si un programa falla durante una transmisión, ya nadie puede devolver el transceptor a recepción: seguiría
transmitiendo una portadora, molestaría en la frecuencia, se calentaría, y tú seguirías siendo responsable.

**Para qué sirve.** La estación tiene su propio TOT (90 s por defecto) y un supervisor que la vigila. El TOT del transceptor
es la **última barrera**: está en el propio transceptor, corta incluso cuando el PC, el cable o la estación están
averiados.

**Cómo.** En el menú del transceptor, busca «Time-Out Timer» («Time-Out Timer (CI-V)» en Icom) o «TX TIME OUT TIMER» y elige **3 minutos**:
más largo que el TOT de la estación, nunca corta una transmisión normal.

La ruta del menú según tu marca está en la tabla de abajo. En el IC-7300MK2, la estación vuelve a leer este ajuste en
cada conexión y te avisa si está en OFF.

## Según tu marca

Lo que cambia de un transceptor a otro, en una línea; el detalle está en la ficha del transceptor cuando la tiene.

| | Icom | Yaesu | Kenwood | Xiegu |
|---|---|---|---|---|
| Driver USB (Windows) | «Icom USB Driver», versión **1.80 o superior** | Silicon Labs **CP210x**; puerto «Enhanced» para el control | driver del fabricante | driver del fabricante |
| TOT del transceptor | MENU > SET > Function > Time-Out Timer (CI-V) | OPERATION SETTING > GENERAL > TX TIME OUT TIMER | manual del transceptor | manual del transceptor |
| Voz por el USB | MENU > SET > Connectors > DATA MOD = **USB** (transmisión en USB-D / LSB-D) | MOD SOURCE = **REAR** y REAR SELECT = **USB**, en cada modo | manual del transceptor | manual del transceptor |
| Estado | **validado** (IC-7300MK2) | **en curso** (FTDX10) | todavía sin probar | todavía sin probar |
| Ficha | [IC-7300MK2](postes/ic7300mk2.md) | [FTDX10](postes/ftdx10.md) | — | — |

En Linux (Debian, Raspberry Pi), no hay ningún driver que instalar. Para un transceptor todavía sin probar: instala el driver USB desde el sitio de su
fabricante, y haz las tres pruebas del paso 5 con especial cuidado.

## 1. Instalar (5 min)

Descarga el paquete de la última versión: https://github.com/Bob56fr/openRemoteTRX/releases

<!-- onglets -->
#### Debian

Extrae `trx-remote-debian-X.Y.Z.zip`, abre un terminal en la carpeta obtenida y luego

```
sudo bash install.sh
```

Cierra la sesión y vuelve a entrar al final.

#### Raspberry Pi

Tarjeta preparada con Raspberry Pi Imager (Raspberry Pi OS de 64 bits, SSH activado) y sistema actualizado: parte 2, pestaña
Raspberry Pi. Luego el **mismo paquete que Debian**: con escritorio, exactamente como en Debian; sin escritorio, desde
tu PC:

```
scp -o User=<cuenta> trx-remote-debian-X.Y.Z.zip <direccion-del-pi>:
ssh -t -l <cuenta> <direccion-del-pi>
```

y en la Pi: `unzip -q trx-remote-debian-X.Y.Z.zip && cd trx-remote-debian-X.Y.Z && sudo bash install.sh`.
Vuelve a conectarte al final.

#### Windows

1. Instala primero **Hamlib de 64 bits** 4.7 o más reciente (`hamlib-w64-X.Y.Z.exe`):
   https://github.com/Hamlib/Hamlib/releases
2. Clic derecho en `trx-remote-windows-X.Y.Z.zip` > Propiedades > **Desbloquear**, luego Extraer todo y doble clic en
   **`installer.cmd`**.
3. Red de casa con perfil **Privado**, **suspensión desactivada**.
<!-- /onglets -->

## 2. Configurar (5 min)

Abre **openRemoteTRX Console** (Debian: menú de aplicaciones o `trx-console`; Raspberry Pi sin escritorio:
`ssh -t -l <cuenta> <direccion-del-pi> trx-console`; Windows: menú Inicio > **openRemoteTRX**),
luego el **menú 2.1** (el asistente). El transceptor solo se lee: ninguna transmisión. Lo que importa:

| Pregunta | Respuesta |
|---|---|
| Modelo | teclea el nombre del transceptor (p. ej. `ic-7300`, `ftdx10`), elige en la lista |
| Puerto y velocidad | el puerto del transceptor; la velocidad ajustada en el menú CAT del transceptor |
| PTT | **CAT** si el asistente lo propone |
| Tarjetas de sonido | la del transceptor, en recepción y en transmisión |
| Bandas permitidas | las bandas de **tu licencia**, nada más. Lista vacía = solo recepción |
| Duración máxima de una transmisión (TOT de la estación) | **90** segundos (propuesto, 120 como máximo) |
| Acceso de red | «Red local o VPN, en HTTPS» (propuesto) |
| Cuenta | un usuario; Intro en la contraseña genera una robusta: **anótala** |

Para el resto, Intro conserva el valor propuesto.

## 3. Arrancar y comprobar (2 min)

1. **Menú 1.1**: la estación arranca, transceptor en recepción.
2. **Menú 6.1** (diagnóstico): corrige cada línea en **fallo** antes de seguir; la línea dice qué hacer.

## 4. Conectarse (1 min)

1. En el teléfono o en un PC de casa: `https://<direccion-de-la-estacion>:8443` (dirección mostrada en la cabecera de TRX
   Console).
2. Aviso del certificado: «Avanzado» y luego «Continuar». Es normal (certificado hecho por tu estación); para
   no verlo más: menú 4.4.
3. Conéctate con la cuenta del asistente. Sin sonido: toca el botón del sonido, el navegador lo había bloqueado.

Reserva la dirección del PC en tu router (reserva DHCP): si cambia, el certificado deja de valer.

## 5. Antes de la primera transmisión: tres pruebas (3 min)

> **Seguridad.** Carga ficticia conectada, potencia reducida, una banda de tu licencia. El **PTT es un conmutador**: una
> pulsación para transmitir, una pulsación para volver a recepción. Después de cada prueba, mira la **pantalla del transceptor**, no
> solo la página.

| Prueba | Resultado esperado |
|---|---|
| Durante una transmisión, botón **STOP** | recepción inmediata |
| Durante una transmisión, cierra la pestaña (o corta el Wi-Fi del teléfono) | recepción en unos 2 s |
| Frecuencia fuera de tus bandas, luego PTT | transmisión **rechazada**, mensaje en la página |

Si falla una sola prueba: **no transmitas**, detén la estación (menú 1.2) y lee la parte 8. Las nueve pruebas completas están
en la parte 3.5: hazlas antes de transmitir con antena.

## Y después

- **Aplicación Android**: menú 4.1, código QR para escanear (aplicación en prueba por invitación, parte 0).
- **Desde el exterior** (4G, otra red): VPN o puerto abierto, parte 5.
- **Alertas en el teléfono**: menú 3.5, con una alerta de prueba.
- **Un problema**: menú 6.1, luego el informe del menú 6.3 para adjuntar a una petición de ayuda (parte 8).
- **Todos los menús de la consola**: https://bob56fr.github.io/openRemoteTRX/console/es/

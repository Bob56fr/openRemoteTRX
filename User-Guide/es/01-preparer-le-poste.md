# 1. Preparar el transceptor

Estación **apagada**, nada conectado: es el momento de ajustar el transceptor. El detalle de los menús de tu transceptor está
en su ficha ([Icom IC-7300MK2](postes/ic7300mk2.md), [Yaesu FTDX10](postes/ftdx10.md)); para otro transceptor,
su manual y la tabla «Según tu marca» del [inicio rápido](demarrage-rapide.md). Esta parte dice en qué
orden hacer las cosas.

## 1.1 Instalar el driver USB (solo Windows)

En Windows, el driver USB del transceptor (el de su fabricante: «Icom USB Driver», Silicon Labs CP210x en
Yaesu…) se instala **antes** de conectar el cable USB; si no, Windows puede instalar un driver equivocado. El nombre, la
versión mínima y el procedimiento están en la ficha del transceptor, «Driver USB», o si no en el sitio del fabricante.

En Debian y en una Raspberry Pi, nada que instalar: el núcleo reconoce el transceptor por sí solo.

## 1.2 Conectar

1. Antena desconectada, **carga ficticia** en la toma de antena utilizada.
2. Cable USB entre el transceptor y el PC.
3. Enciende el transceptor (pulsación larga en ON/OFF).

El PC ve entonces uno o dos **puertos serie** y una **tarjeta de sonido**. La ficha del transceptor dice cuál sirve para el control
(IC-7300MK2: el primero, el segundo sirve para el espectro HF; FTDX10: el «Enhanced COM Port», el «Standard» no se
usa).

<!-- onglets -->
#### Debian

Nada que anotar: el asistente reconoce él mismo el puerto correcto. Para verlo: `ls -l /dev/serial/by-id/` en un
terminal (un nombre estable por puerto, que no cambia de una toma USB a otra).

#### Raspberry Pi

Como en Debian. Conecta el cable del transceptor **directamente** a un puerto USB de la Pi (los puertos azules USB 3 también sirven);
un hub, solo si tiene su propia alimentación: la Pi no suministra corriente suficiente a varios dispositivos.

#### Windows

Administrador de dispositivos > Puertos (COM y LPT): anota el número COM del puerto de control.
<!-- /onglets -->

## 1.3 Ajustar los menús del transceptor

Ajusta los menús enumerados en la ficha de tu transceptor, sección «Menús que ajustar» (si no, su manual). Son
imprescindibles:

- **velocidad del CAT** idéntica a la de la estación (elegida en el asistente);
- **voz por el USB**: si no, el transceptor modula con su propio micrófono, es decir, con el ruido de la habitación. En un Icom
  (IC-7300MK2): MENU > SET > Connectors > MOD Input > **DATA MOD = USB** (la estación solo transmite en modo datos);
  el transceptor solo acepta la toma USB en DATA MOD **o** DATA OFF MOD. Con el segundo puerto configurado, la estación lo
  comprueba en cada conexión y te avisa si no está en USB;
- **ninguna línea RTS/DTR** para el PTT ni la CW: si no, el transceptor puede pasar a transmisión al arrancar el PC;
- **VOX apagado**: un VOX en marcha hace transmitir al transceptor con un ruido de la habitación, sin ninguna orden. La estación lo comprueba en cada conexión de un operador y lo **apaga** si está en marcha (mensaje en el registro de la página, código ORT-5034). En algunos transceptores sigue en marcha en un modo aunque esté apagado en otro (visto en el IC-7300MK2: apagado en modo datos, todavía en marcha en fonía);
- **acoplador de antena integrado** (si la antena pasa por él): la sintonía debe arrancar sola al conmutar a TX
  en una frecuencia nueva. En el IC-7300MK2: MENU > SET > Function > Tuner, **[TUNER] Switch = Auto** (estado del
  acoplador memorizado por banda) y **PTT Start = ON**. Responde «sí» a la pregunta del acoplador del asistente: la
  estación comprobará estos ajustes en cada conexión y te avisará si son incorrectos (nunca los cambia). Fuera
  de las bandas de radioaficionado, el transceptor no garantiza la sintonía con el PTT. Durante una transmisión, si la ROE supera 2
  más de un segundo, la página muestra una banda roja y pita (no corta);
- **temporizador de transmisión del transceptor** (TX TIME OUT TIMER): una segunda seguridad, independiente de la estación.
  Ajústalo (3 min aconsejados): si la estación, la red o el PC caen durante una transmisión, es él quien corta.
  Para un transceptor cuya lectura está cualificada (IC-7300MK2), la estación lo lee en cada conexión y te avisa si
  está en OFF; para los demás, no puede comprobarlo.

> **Seguridad.** Una seguridad de más no cuesta nada: ajusta también una **potencia máxima** razonable en el
> transceptor (HF MAX POWER). La estación no puede superarla, pase lo que pase.

## 1.4 Sonido del PC

La tarjeta de sonido del transceptor **nunca** debe ser el sonido predeterminado del PC; si no, los sonidos del escritorio van al
transceptor (y el escritorio ocupa la tarjeta):

<!-- onglets -->
#### Debian

*Configuración > Sonido*: en salida los altavoces del PC, en entrada su micrófono.

#### Raspberry Pi

Sin escritorio (Raspberry Pi OS Lite): nada que hacer, ningún programa toma la tarjeta del transceptor. Con escritorio: como
en Debian, en los ajustes de sonido de la barra superior. La tarjeta de sonido de la propia Pi («Headphones», «HDMI») no
sirve a la estación.

#### Windows

*Configuración > Sistema > Sonido*: en salida los altavoces del PC, en entrada su micrófono; en «Más opciones de
sonido», la tarjeta del transceptor no es ni «Dispositivo predeterminado» ni «Dispositivo de comunicación predeterminado»;
combinación de sonidos «Sin sonidos». El detalle está en el manual de Windows incluido en el paquete.
<!-- /onglets -->

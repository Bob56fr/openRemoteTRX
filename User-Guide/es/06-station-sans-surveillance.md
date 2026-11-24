# 6. Una estación sin vigilancia

Una estación controlada a distancia funciona la mayor parte del tiempo sin nadie al lado. Esta parte prepara este caso.

## 6.1 Las alertas en tu teléfono (ntfy)

El supervisor de la estación puede enviarte notificaciones: transmisión cortada por seguridad, avería, bloqueo de seguridad,
memoria o disco casi llenos, corte del enlace, y un mensaje «Estación en servicio» sin sonido cada
hora (si deja de llegar, la estación o su conexión está averiada).

1. Instala la aplicación **ntfy** en el teléfono.
2. Elige un **nombre de tema largo e imposible de adivinar** (por ejemplo 20 letras y cifras al azar):
   en el servidor público ntfy.sh, cualquiera que conozca el nombre lee los mensajes.
3. Suscríbete a este tema en la aplicación ntfy.
4. En la estación, menú **3.5** «Alertas en el teléfono»: opción 1, pega la dirección
   `https://ntfy.sh/<tu-tema>`, guarda, acepta el reinicio. La pantalla nunca muestra la dirección completa.
5. Comprueba: opción 4, «Enviar ahora una alerta de prueba»; el teléfono debe sonar enseguida (código ORT-8025).
   Después, el mensaje «Estación en servicio» llega cada hora (opción 3 para cambiar este ritmo).

Cada alerta lleva un código «ORT-NNNN» con un enlace a su explicación (parte 8). Dos alertas llegan al
reiniciar tras una parada que no fue limpia: **ORT-8030** (Debian, Raspberry Pi: la máquina se detuvo
bruscamente, corte de corriente o bloqueo) y **ORT-8031** (solo el supervisor se detuvo); cada una da
la hora de la última señal de vida. Una parada normal (menú 1.2, apagado del PC) no envía nada.

## 6.2 El bloqueo de seguridad

Tras averías repetidas que los reinicios no han resuelto, el supervisor **pone la estación en bloqueo de seguridad**: transceptor
en recepción, acceso cortado, alerta enviada. El bloqueo de seguridad **sobrevive a los reinicios**: hay que encontrar la causa
(menús 6.1 y 6.2), y luego levantarlo con el menú **1.4**.

## 6.3 Tras un corte de corriente

| Elemento | Qué ajustar |
|---|---|
| PC | en la BIOS / UEFI: «Restore on AC power loss» = **Power On** (el nombre varía según la placa base) |
| Raspberry Pi | nada: se reinicia en cuanto vuelve la corriente |
| Estación Debian o Raspberry Pi | nada: arranca con la máquina, sin abrir sesión |
| Estación Windows | arranca al **abrir la sesión**: sin inicio de sesión automático, se queda detenida |
| Transceptor | la mayoría de los transceptores **no** se vuelven a encender solos. La estación sabe encenderlo por CAT (menú **2.8**, fuera de servicio por defecto, con una prueba de apagar / volver a encender): tu conexión desde la página o la aplicación lo vuelve a encender |
| Router | se vuelve a encender solo; comprueba que la VPN también |

Un **SAI** para el PC, el router y la alimentación del transceptor evita la mayoría de estos casos.

## 6.4 Protecciones del material

- **Rayos**: una estación aislada de toda presencia humana está expuesta. Pararrayos en el cable de antena, y
  antena puesta a tierra o desconectada si se prevé tormenta.
- **Potencia**: el límite del transceptor (HF MAX POWER, parte 1) sigue siendo la última barrera.
- **Temporizador del transceptor** (TX TIME OUT TIMER): ajustado a 3 min, corta aunque todo lo demás haya fallado.
- **Temperatura**: el supervisor vigila el procesador del PC y alerta cuando se mantiene por encima de 70 °C
  durante un minuto (un pico de unos segundos no cuenta); la alerta dice qué programas calentaban.
  En Debian y en una Pi, el historial de las últimas 24 h (una medida cada 10 s) se adjunta al informe de
  diagnóstico (menú 6.3). En una Pi, el ventilador es imprescindible. La temperatura del transceptor no la puede leer la
  estación en los transceptores probados (IC-7300MK2, FTDX10): ventilación correcta alrededor del transceptor.
- **Operador local**: si alguien usa el transceptor en el lugar, la transmisión a distancia queda bloqueada durante
  su transmisión y luego 2 minutos; la estación nunca lo corta por este motivo. Una transmisión con el micrófono la corta
  el TOT absoluto (135 s), salvo si el operador ha tocado el transceptor (volumen, frecuencia, modo, salida del modo DATA…) en
  los 2 minutos antes de hablar o mientras habla: la estación lo sabe presente y le deja hablar hasta
  5 minutos (`local_tx_max_s`), con una simple alerta entre ambos. El temporizador del transceptor, si está ajustado más
  corto, corta antes. Estos ajustes están en el menú **3.4** «Operador presente»: conserva «estación compartida»;
  si no, un micrófono mantenido pulsado lleva al bloqueo de seguridad.

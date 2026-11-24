# 3. Integrar el TRX y probarlo

> **Seguridad.** Durante toda esta parte: **carga ficticia** en la toma de antena, **potencia reducida**
> (10 W por ejemplo), nadie cerca de la antena desconectada.

## 3.1 El asistente de configuración (menú 2.1)

El transceptor solo se consulta **en lectura**: ninguna transmisión durante el asistente. No se guarda nada si
abandonas a mitad de camino. Los valores propios de tu transceptor están en su ficha:

| Pregunta | Respuesta |
|---|---|
| Modelo del transceptor | teclea su nombre (`ic-7300`, `ftdx10`…) y elige en la lista (número Hamlib en la ficha: IC-7300MK2 = 3094, FTDX10 = 1042). Para algunos transceptores, el asistente recuerda los menús que comprobar (parte 1) |
| Puerto serie del CAT | el puerto de **control** (Debian y Raspberry Pi: propuesto directamente; Windows: el COM anotado en la parte 1) |
| Velocidad | **idéntica** a la velocidad CAT ajustada en el transceptor |
| Método de PTT | **CAT** (propuesto) |
| ¿La voz sale por el USB? | **sí**, si el transceptor modula por el USB en fonía (parte 1); si no, la transmisión se limitará a los modos de datos |
| Tarjetas de sonido (recepción, transmisión) | la del **transceptor** para ambas (su nombre está en la ficha) |
| Espectro HF por un segundo puerto | el **segundo puerto** del transceptor si lo tiene (Icom IC-7300MK2…); si no, **ninguno** |
| Bandas permitidas para transmitir | las bandas de **tu licencia**, solamente. Lista vacía = solo recepción |
| Acceso de red | «**Red local o VPN, en HTTPS con un certificado generado aquí**» (recomendado) |
| Cuentas | un usuario (letras, cifras, `_`, `-`) y una **contraseña larga** (Intro = se genera una contraseña robusta: anótala); Intro con un usuario vacío para terminar |
| Potencia máxima del transceptor | la de tu transceptor (a menudo **100** vatios) |
| Duración máxima de una transmisión (TOT) | **90** segundos (valor por defecto, máximo 120) |
| Repetición de grabaciones | **no** (respuesta por defecto) |

Al final, el asistente muestra la dirección que abrir (`https://<direccion-de-la-estacion>:8443`) y la **huella del
certificado** (útil para la aplicación Android, parte 4).

## 3.2 El diagnóstico (menú 6.1)

Lo revisa todo sin modificar nada: cada línea está **OK**, **a vigilar** o en **fallo**, con el
procedimiento a seguir. Corrige cada fallo antes de seguir (menú 8.1 para un ajuste, o vuelve a lanzar el asistente).

Fallos frecuentes en esta etapa: puerto equivocado (el segundo puerto del transceptor en lugar del de control; Yaesu:
Standard en lugar de Enhanced), velocidad del transceptor distinta de la del asistente, tarjeta de sonido del transceptor tomada por el
escritorio (parte 1.4); en una Raspberry Pi, una alimentación demasiado débil («subtensión», parte 2).

## 3.3 La prueba guiada del transceptor (menú 2.2)

La estación está detenida durante la prueba.

1. **Opción 1, solo recepción**: enlace CAT, audio recibido, cambio de frecuencia y de modo, anchos de filtro.
   Escucha que el audio recibido es limpio y a un nivel correcto (si no: ajuste del transceptor indicado en su ficha, luego ganancia del audio recibido en el menú 2.9).
2. **Opción 2, recepción y luego transmisión**: carga ficticia, potencia reducida. Cada paso a transmisión pide
   teclear `TRANSMITIR` (o `EMETTRE`).

Copia el **resumen final** mostrado en pantalla: sirve para el informe de validación.

## 3.4 Arrancar la estación y ajustar la modulación

1. Menú **1.1**: la estación arranca (el transceptor siempre se devuelve a recepción al arrancar). Repite un diagnóstico
   (menú 6.1) unos segundos más tarde.
2. Abre la página `https://<direccion-de-la-estacion>:8443` desde un teléfono o un PC de la red (detalles y
   aviso del certificado: parte 4), conéctate.
3. Banda permitida, carga ficticia, modo de fonía que tu transceptor modula por el USB (USB o LSB; en un Icom, USB-D
   o LSB-D, parte 1): pulsa el **PTT** (conmutador: una pulsación para transmitir, una pulsación para volver a
   recepción), habla normalmente unos segundos, pulsa de nuevo.
4. Mira el **ALC** en la página: debe moverse con los picos de voz sin quedarse al máximo. Ajusta el nivel
   de entrada USB del transceptor hasta obtener este resultado (Icom: **USB MOD Level**; Yaesu: **RPORT GAIN** en el menú
   del modo utilizado; el nombre exacto está en la ficha del transceptor).

## 3.5 Las pruebas de seguridad

Hazlas **todas**, con carga ficticia, antes de cualquier transmisión con antena. Cada una debe terminar con la vuelta del
transceptor a recepción (compruébalo en la pantalla del transceptor, no solo en la página).

| # | Prueba | Resultado esperado |
|---|---|---|
| 1 | Durante una transmisión, botón **STOP** de la página | vuelta a recepción inmediata |
| 2 | Transmitir sin tocar nada | cuenta atrás y pitido 10 s antes del final, vuelta a recepción a los **90 s** |
| 3 | Durante una transmisión, cortar el Wi-Fi del teléfono (o cerrar la pestaña) | vuelta a recepción en unos **2 s** |
| 4 | Durante una transmisión desde el teléfono, bloquear la pantalla | vuelta a recepción |
| 5 | Ajustar una frecuencia fuera de tus bandas permitidas, pulsar PTT | transmisión **rechazada**, mensaje en la página |
| 6 | Transmitir **con el micrófono del transceptor** (sin la estación) | la página muestra el operador local y bloquea el PTT a distancia durante la transmisión y luego 2 minutos |
| 7 | Durante una transmisión, tecla **STOP TX** del panel (menú 1.3) | vuelta a recepción |
| 8 | Durante una transmisión, detener la estación (menú 1.2) | vuelta a recepción |
| 9 | Reiniciar el PC (o la Pi), transceptor encendido | el transceptor **nunca** pasa a transmisión durante el arranque |

Una prueba que no da el resultado esperado: **no uses la estación para transmitir**, detenla (menú 1.2) y
pide ayuda (parte 8) con el informe del menú 6.3.

## 3.6 Para ir más lejos (opcional)

- **Cualificación del transceptor** (menú 8.3, `trx-qualif`): para un experto que quiere comprobar todo lo que Hamlib
  declara para tu transceptor. Empieza por la opción 2 (exploración sin transmisión); el informe producido es valioso para
  validar la ficha del transceptor. La opción 6 («maleta de cualificación») lo encadena todo para un miembro del equipo que viene a
  cualificar el transceptor: lectura del transceptor antes y después (lo que hay que restablecer a mano), exploración, cualificación,
  las pruebas de seguridad del § 3.5 cronometradas, y un informe zip para entregar a los desarrolladores.
- **Perfil de transceptor** (menú 2.3): guarda la configuración con un nombre («IC-7300 casa») para volver a cargarla más
  tarde si cambias de transceptor.

## 3.7 Informar de la validación

Si tu transceptor todavía no está validado (lista: https://bob56fr.github.io/openRemoteTRX/postes/), tu resultado
cuenta: abre un ticket «Informar de un error» (aunque todo vaya bien, título «<tu transceptor>: pruebas de puesta en
servicio») con el resumen de la prueba guiada, el resultado de las 9 pruebas de seguridad y, si tiene una ficha, los puntos
que esta dice que hay que comprobar.

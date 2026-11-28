# 8. Solución de problemas

## 8.1 El primer reflejo

1. **Diagnóstico** (menú 6.1): dice qué va mal y qué hacer.
2. **Registro** (menú 6.2): los mensajes empiezan por un código «ORT-NNNN».
3. Cada código tiene su página de explicación (causa, qué hacer): https://bob56fr.github.io/openRemoteTRX/erreurs/
   (campo de búsqueda: teclea el código).

## 8.2 Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| El diagnóstico no encuentra el transceptor | transceptor apagado; puerto equivocado (el segundo puerto del transceptor, o «Standard» en Yaesu); velocidad del transceptor distinta de la del asistente; driver ausente (Windows) | encender; repetir el menú 2.5 con el puerto de control; ajustar la velocidad (ficha del transceptor) |
| No hay audio recibido | tarjeta de sonido del transceptor tomada por el escritorio; micrófono prohibido a las aplicaciones (Windows); nivel demasiado bajo (ajuste del transceptor, ganancia del menú 2.9) | parte 1.4; parte 2, pestaña Windows; ficha del transceptor |
| La transmisión sale pero no se modula nada | el transceptor toma la voz de su micrófono, no del USB, en este modo (Icom: DATA MOD; Yaesu: MOD SOURCE y REAR SELECT) | ficha del transceptor, «Voz por el USB» |
| Solo pueden transmitir los modos DATA | el asistente anotó que la voz no pasa por el USB | ajustar el transceptor, luego volver a lanzar el asistente y responder «sí» |
| ALC al máximo, audio saturado | nivel de entrada USB del transceptor demasiado alto (Icom: USB MOD Level; Yaesu: RPORT GAIN) | parte 3.4 |
| El transceptor pasa a transmisión al arrancar el PC | una línea RTS o DTR del puerto USB controla la transmisión (Icom: USB SEND / USB Keying; Yaesu: RPTT SELECT, PC KEYING) | **desconectar el USB**, poner estos ajustes en OFF (ficha del transceptor) |
| Raspberry Pi lenta, audio entrecortado, USB del transceptor que se desconecta | alimentación demasiado débil o sobrecalentamiento (`vcgencmd get_throttled` distinto de `throttled=0x0`) | alimentación oficial, ventilador (parte 2, pestaña Raspberry Pi) |
| «Micrófono no disponible» en la página | página abierta en HTTP | abrir la dirección en **https://** |
| Página inaccesible desde el teléfono | estación detenida; dirección cambiada; red con perfil Público (Windows) | menú 1.1; parte 4.1; parte 2, pestaña Windows |
| Conectado pero sin audio a distancia | el UDP no pasa (puerto abierto en el router) | VPN (parte 5) |
| Cortes cada 15 a 30 s | dos dispositivos con el mismo perfil VPN | un perfil por dispositivo |
| Transmisión cortada sola | duración máxima alcanzada, teléfono que deja de responder, frecuencia fuera de bandas, operador local | normal: el motivo se muestra en la página y en el registro |
| Ya nada responde, alerta «estación en bloqueo de seguridad» | averías repetidas | parte 6.2 |
| Prueba del transceptor rechazada: «ORT-9313 … la estación está en marcha» | la prueba necesita el transceptor para ella sola | detener la estación (menú 1.2), repetir la prueba, reiniciar la estación |
| Una herramienta se detiene con «ORT-9312 … error inesperado» | defecto del software en un caso no previsto (transceptor nuevo, tarjeta de sonido…) | el mensaje indica el archivo de detalle (carpeta `plantages`): adjuntarlo a la petición de ayuda (parte 8.3) |

## 8.3 Pedir ayuda

1. Menú **6.3**: crea un informe de diagnóstico (zip en el Escritorio, o en la carpeta de la cuenta en una Pi sin escritorio) **sin ninguna contraseña** (tanto en Windows como en Debian). Desde la consola web, el botón
   **«Descargar el informe»** lo recupera directamente en tu PC o tu teléfono. Las trazas de las herramientas detenidas por un error
   (código ORT-9312) están en la carpeta `plantages` de la carpeta de estado de la estación, y el informe las adjunta.
   Para leerlo tú mismo: menú **6.6**, que da el enlace del **analizador**; ahí depositas el zip y el análisis se
   hace en tu navegador (el informe no se envía a ningún sitio).
2. Desde la página web: sección «Informar de un problema» (texto revisado antes del envío).
3. Abre un ticket en https://github.com/Bob56fr/openRemoteTRX/issues con el formulario **en español**
   («Informar de un error»), describe lo que hacías, lo que esperabas, lo que ocurrió, y adjunta el informe.
4. **Recibir ayuda a distancia** (monitorización entre estaciones, menú **6.5**, que hay que activar primero: parte 9): la persona que
   te ayuda crea un código de 10 caracteres y te lo dicta; tecléalo en la opción 4, luego comparen de viva voz las **6
   cifras** mostradas en ambos lados. Distintas: responde «no», el enlace se borra. Elige después lo que
   envías («Diagnóstico» aconsejado; frecuencia y modo solo si quieres). Ve entonces el estado de tu estación
   y sus códigos de error, **enmascarados** (ni contraseña, ni dirección, ni número de serie), y puede **pedirte** el modo
   asistencia (noticias cada 30 segundos, durante un tiempo limitado): eres tú quien acepta (opción 7). No
   puede **mandar nada** en tu estación. Lo detienes todo cuando quieras (opción 9). También puede
   pedirte tu **informe de diagnóstico** (el del punto 1, totalmente enmascarado); también puedes enviarlo
   tú mismo (opción 10). Por su parte, recibe una alerta en su teléfono si tu estación deja de dar
   noticias. **Lejos de tu estación**, todo se hace también en la página web, sección «Monitorización»: botón
   «Recibir ayuda: tengo un código», comparación de las 6 cifras, elección de lo que se envía, respuesta a las peticiones, fin.
5. **Mostrar tu pantalla a la persona que te ayuda** (pantalla compartida, menú **6.7**, nada que activar, funciona
   incluso antes de configurar la estación): en la consola de texto (terminal o SSH, Debian o Raspberry Pi), opción 1.
   La consola muestra un código de 10 caracteres: díctalo y pulsa Intro. La persona que te ayuda abre el menú 6.7,
   opción 2 (en su PC, Windows incluido) y escribe el código: ve tu consola en directo, cifrada de extremo a extremo
   por el relé de rf-diy.com. **No puede escribir nada**: eres tú quien escribe lo que te dice (por teléfono, por
   ejemplo). **Ctrl+]** detiene la compartición (tu consola sigue); salir de la consola lo detiene todo; 2 horas como
   máximo. También en línea de órdenes: `trx-console --partage` (tú) y `trx-console --voir CÓDIGO` (ella). Su ventana
   debe ser al menos tan grande como la tuya (el título de su ventana se lo indica).

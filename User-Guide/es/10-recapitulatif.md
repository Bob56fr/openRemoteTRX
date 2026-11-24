# 10. Resumen: ¿en qué punto estás?

Marca a medida que avanzas. En la página web de la guía, las casillas se marcan en línea y quedan marcadas en tu
navegador; en GitHub, imprime esta página o copia la lista.

## 0. Antes de empezar

- [ ] Condiciones del tráfico a distancia comprobadas para mi licencia
- [ ] Carga ficticia disponible para las pruebas
- [ ] Sistema elegido (Debian recomendado, Raspberry Pi o Windows) y paquete descargado

## 1. Preparar el transceptor

- [ ] Driver USB del fabricante instalado antes de conectar el cable (Windows)
- [ ] Puerto de control del transceptor localizado (ficha del transceptor)
- [ ] Velocidad CAT del transceptor anotada, menús de la ficha del transceptor ajustados
- [ ] Voz por el USB ajustada en cada modo utilizado
- [ ] Ninguna línea RTS / DTR del puerto USB controla la transmisión
- [ ] VOX apagado, temporizador de transmisión del transceptor a 3 min, potencia máxima ajustada
- [ ] Tarjeta de sonido del transceptor retirada del sonido predeterminado del PC

## 2. Instalar la estación

- [ ] Software instalado (install.sh o installer.cmd)
- [ ] Sesión reabierta (Debian, Raspberry Pi); perfil de red Privado y suspensión desactivada (Windows)
- [ ] Raspberry Pi: alimentación oficial, ventilador, `throttled=0x0`

## 3. Integrar el TRX y probarlo

- [ ] Asistente terminado (modelo de mi transceptor, puerto de control, PTT por CAT, bandas de mi licencia)
- [ ] Diagnóstico sin fallos
- [ ] Prueba guiada solo en recepción superada
- [ ] Prueba guiada con transmisión superada con carga ficticia
- [ ] Estación arrancada, página abierta, modulación ajustada con el ALC (nivel de entrada USB del transceptor)
- [ ] Prueba 1: STOP corta la transmisión
- [ ] Prueba 2: corte a los 90 s, aviso 10 s antes
- [ ] Prueba 3: enlace cortado durante la transmisión, vuelta a recepción
- [ ] Prueba 4: pantalla bloqueada durante la transmisión, vuelta a recepción
- [ ] Prueba 5: transmisión rechazada fuera de mis bandas
- [ ] Prueba 6: transmisión con el micrófono del transceptor, PTT a distancia bloqueado
- [ ] Prueba 7: STOP TX del panel
- [ ] Prueba 8: parada de la estación durante la transmisión
- [ ] Prueba 9: ningún paso a transmisión al arrancar el PC (o la Pi)
- [ ] Resultado de las pruebas comunicado, si mi transceptor todavía no está validado (ticket «<mi transceptor>: pruebas de puesta en servicio»)

## 4. Usar en la red local

- [ ] Dirección IP reservada para el PC de la estación en el router
- [ ] Página web abierta en https, certificado aceptado, micrófono permitido
- [ ] Una cuenta por dispositivo (menú 4.3), contraseñas largas
- [ ] Aplicación Android emparejada con el código QR (menú 4.1), prueba de transmisión y STOP

## 5. Usar a distancia

- [ ] Elección hecha: VPN (recomendado) o puerto abierto
- [ ] Un perfil VPN por dispositivo
- [ ] Desde la 4G: página, audio recibido, transmisión con carga ficticia, STOP
- [ ] Desde la 4G: modo avión durante la transmisión, vuelta a recepción

## 6. Estación sin vigilancia

- [ ] Alertas ntfy recibidas (tema largo y secreto), mensaje «Estación en servicio» visto
- [ ] PC ajustado para volver a encenderse tras un corte de corriente (una Pi lo hace sola)
- [ ] SAI, pararrayos, ventilación del transceptor
- [ ] Sé reactivar la estación en bloqueo de seguridad (menú 1.4) tras haber encontrado la causa

## 7. Explotación diaria

- [ ] Sé arrancar, detener y vigilar la estación
- [ ] Sé actualizar y volver a la versión anterior
- [ ] Configuración y certificado copiados en otro sitio
- [ ] Perfil del transceptor guardado (menú 2.3)

## Estación en servicio

- [ ] Primera transmisión con antena, en mis bandas, con identificación

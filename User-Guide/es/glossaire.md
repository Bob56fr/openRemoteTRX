# Glosario

Las palabras de la guía, ordenadas por tema. El esquema de los bloques está en la
[parte 0](00-avant-de-commencer.md#cómo-está-organizado).

## El material

| Término | Qué es |
|---|---|
| **Transceptor**, **TRX** | tu emisor-receptor de radio (también «equipo») |
| **PC de la estación** | el ordenador colocado junto al transceptor, encendido permanentemente, que hace funcionar la estación: un PC con Debian o Windows, o una Raspberry Pi |
| **Raspberry Pi** | pequeño ordenador en una placa, de bajo consumo; la Pi 4 (4 GB) o la Pi 5 con Raspberry Pi OS de 64 bits puede servir de PC de la estación |
| **Watchdog de hardware** | un chip de la Raspberry Pi que la reinicia si el sistema se bloquea más de 15 s; activado por la instalación |
| **Estación** | el conjunto transceptor + PC + software openRemoteTRX; «arrancar la estación» = arrancar sus servicios |
| **CAT** | *Computer Aided Transceiver*: el control del transceptor por el ordenador (frecuencia, modo, transmisión…) |
| **Enhanced COM Port** / **Standard COM Port** | los dos puertos serie que algunos Yaesu (FTDX10…) crean en el PC a través de su cable USB: el primero sirve para el CAT, el segundo (líneas RTS/DTR) no lo usa la estación |
| **Tarjeta de sonido del transceptor** | la tarjeta de sonido integrada en el transceptor, vista por el PC a través del cable USB («USB Audio CODEC» en Yaesu, «USB Audio Device» en el IC-7300MK2): audio recibido hacia el PC, voz hacia el transceptor |
| **Carga ficticia** | resistencia de 50 Ω que sustituye a la antena: el transceptor transmite sin radiar. Obligatoria para todas las pruebas |
| **ALC** | indicador del transceptor que muestra si la modulación es demasiado fuerte; sirve para ajustar el nivel de la voz |
| **ROE** (SWR) | relación de ondas estacionarias: adaptación de la antena. La estación sabe medirla en una banda |
| **VFO A / VFO B** | las dos frecuencias de trabajo del transceptor; la página muestra cuál está activo |
| **Split** | recepción en una frecuencia, transmisión en otra |

## El software de la estación

| Término | Qué es |
|---|---|
| **openRemoteTRX** | el nombre del proyecto; la aplicación Android lleva este nombre, la estación también se llama «openRemoteTRX» |
| **Hamlib** | la biblioteca libre que sabe hablar con unos 300 modelos de transceptores; cada modelo tiene un **número** (IC-7300MK2 = 3094, FTDX10 = 1042) |
| **rigctld** | el programa de Hamlib que mantiene el enlace con el transceptor; solo escucha en el propio PC, nunca en la red |
| **Pasarela** (`trx-gateway`) | el corazón de la estación: sirve la página web, comprueba las cuentas, transporta el audio y **decide la transmisión** |
| **Supervisor** (`trx-supervisor`) | el guardián independiente: vigila la pasarela, rigctld y el PC; **solo puede cortar** una transmisión, reiniciar un servicio o poner la estación en bloqueo de seguridad; envía las alertas |
| **openRemoteTRX Console** (`trx-console`) | el cuadro de mando de la estación en un terminal: instalar, configurar, arrancar, probar, actualizar, solucionar problemas (menús numerados «2.1», «2.2»…) |
| **Asistente de configuración** (`trx-setup`) | las preguntas que crean la configuración (menú 2.1); solo consulta el transceptor en lectura |
| **Panel** (`trx-monitor`) | el estado en directo en un terminal (menú 1.3); una sola acción: STOP TX |
| **Panel de constantes vitales** | página de solo lectura (puerto 8450, Debian y Raspberry Pi) para una pantalla pequeña junto al transceptor o un teléfono |
| **Indicador** | el piloto de la estación en la barra superior (Debian) o junto al reloj (Windows); solo lectura |
| **Prueba guiada** (`trx-hwtest`) | la prueba paso a paso del transceptor real (menú 2.2) |
| **Cualificación** (`trx-qualif`) | la exploración completa de lo que Hamlib declara para un transceptor (menú 8.3), para expertos |
| **`station.toml`** | el archivo de configuración de la estación: transceptor, puertos, cuentas, bandas permitidas, seguridades |
| **Perfil de transceptor** | una configuración de transceptor guardada con un nombre, para cambiar de transceptor (menú 2.3) |
| **Módulo** | una función opcional que funciona junto a la pasarela (DX Cluster, presencia de grupo…) |
| **Actualización firmada** | los paquetes Debian están firmados: la actualización por Internet (menú 7.1) rechaza un paquete cuya firma no corresponde; un zip sin firmar (menú 7.3) pide una confirmación |

## Lado del usuario

| Término | Qué es |
|---|---|
| **Página web** | la interfaz de la estación en un navegador, en la dirección `https://<direccion-de-la-estacion>:8443` |
| **Aplicación Android** | la aplicación openRemoteTRX: lo mismo que la página, más la transmisión con la pantalla apagada, los auriculares, el coche |
| **Android Auto** | la visualización de la aplicación en la pantalla del coche: escucha, memorias, PTT, sin gráficos |
| **Modo conducción** | la pantalla reducida de la aplicación en el coche: sin PTT táctil |
| **Cuenta de operador** | usuario + contraseña que permiten controlar el transceptor y transmitir; **una por dispositivo** (`PC`, `S25`…), gestionadas en el menú 4.3 |
| **Visitante** | cuenta solo en recepción: escucha y ve la pantalla, ninguna orden |
| **Emparejamiento** | la adición de la estación en la aplicación, mediante el **código QR** del menú 4.1 |

## La seguridad de transmisión

| Término | Qué es |
|---|---|
| **PTT** | *Push To Talk*: el paso a transmisión |
| **PTT conmutado** | una pulsación para transmitir, una pulsación para volver a recepción (nunca «mientras se pulsa») |
| **STOP** | vuelta inmediata a recepción, siempre disponible |
| **TOT** | *Time Out Timer*: duración máxima de una transmisión (90 s por defecto, 120 s como máximo), con un pitido 10 s antes del corte |
| **TOT absoluto** | duración más allá de la cual el supervisor corta cualquier transmisión, incluso la hecha con el micrófono del transceptor (135 s; 5 minutos si el operador ha tocado el transceptor justo antes o durante) |
| **Latido** | la señal de vida que el teléfono envía dos veces por segundo durante la transmisión; si falta 2 s, vuelta a recepción |
| **Bandas permitidas** | los rangos de frecuencias donde la estación acepta transmitir; lista vacía = solo recepción |
| **Operador local** | alguien que usa el transceptor delante de él (menú 3.4 «Operador presente»): la transmisión a distancia queda bloqueada durante su transmisión y luego 2 minutos |
| **Puerta de audio de transmisión** | el paso del audio hacia el transceptor, abierto por la pasarela solo durante una transmisión permitida |
| **Bloqueo de seguridad** | el estado en que el supervisor pone la estación tras averías repetidas: detenida sin peligro (recepción, acceso cortado), espera una intervención; se reactiva con el menú 1.4 («Reactivar la estación») |
| **Temporizador del transceptor** (TX TIME OUT TIMER) | el corte propio del transceptor, independiente de la estación: la última barrera |

## La red

| Término | Qué es |
|---|---|
| **Red local** (LAN) | la red de casa, detrás del router |
| **Puerto 8443** | el puerto donde la pasarela recibe la página y la aplicación |
| **HTTPS**, **certificado** | el cifrado del enlace; la estación crea su propio certificado («autofirmado»): el navegador avisa la primera vez |
| **Huella del certificado** | el resumen del certificado que la aplicación recuerda para rechazar una estación falsa |
| **WebRTC** | la técnica que transporta el audio en directo, por **UDP** |
| **VPN** | un túnel cifrado que pone el teléfono «dentro» de la red de casa, desde cualquier lugar (WireGuard, Tailscale…) |
| **Perfil VPN** | las claves de un dispositivo en la VPN: un perfil por dispositivo, nunca compartido |
| **Puerto abierto** | el router que deja entrar desde Internet hacia la estación; requiere un certificado real y una contraseña robusta |
| **SSH** | la conexión cifrada que abre un terminal de otra máquina desde tu PC: `ssh -l <cuenta> <direccion>`; sirve para controlar una Raspberry Pi sin pantalla |
| **CGNAT** | dirección compartida por el operador entre varios clientes: no se puede abrir ningún puerto, hace falta una VPN |
| **ntfy** | el servicio de notificaciones que lleva las alertas de la estación a tu teléfono |
| **Código ORT** | el número de un mensaje de la estación («ORT-5031»); cada código tiene su página de explicación |

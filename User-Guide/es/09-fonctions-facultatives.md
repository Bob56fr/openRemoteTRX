# 9. Funciones opcionales

Todas están **desactivadas** al principio. Actívalas una vez validada la estación (partes 3 a 5): el menú **5.5**
«Funciones en servicio» las pone en servicio o las detiene con un número (también lanza el módulo de la función);
una función que requiere otros ajustes se rechaza indicando el menú donde hacerlos.

| Función | Para qué sirve | Dónde activarla |
|---|---|---|
| **Visitantes** solo en recepción | cuentas que escuchan la estación y ven la pantalla, sin **ninguna** orden (radioclub, demostración) | menú 4.2, luego el conmutador «Escucha de los visitantes» de la página |
| **DX Cluster** | spots en el espectro y pastillas en los botones de banda | menú 5.1 |
| **FreeDV** RADE V1 (recepción) | voz digital FreeDV decodificada por la estación | decodificadores que compilar (`sudo bash compiler-freedv.sh` en la carpeta del paquete Debian), luego menú 5.5 («Recepción FreeDV»); el locator de la actividad FreeDV: `[freedv] locator` (menú 8.1) |
| **SELCALL** | silenciador por llamada de grupo en BLU | menú 5.5, luego la sección SELCALL de la página |
| **Medida de ROE** | curva de ROE de la antena en una banda, en FM, potencia reducida | página web o aplicación; la estación transmite: solo bandas permitidas |
| **Presencia de grupo** | ver qué amigos equipados con openRemoteTRX están en QSO, y unirse a ellos | menú 5.3 |
| **Monitorización entre estaciones** | recibir ayuda a distancia de alguien de confianza, o ayudar a otro operador: estado de la estación y códigos de error, enmascarados y cifrados, sin VPN ni puerto abierto; ninguna orden posible hacia la estación ayudada | menú 5.5 («Monitorización entre estaciones»), luego menú 6.5 o sección «Monitorización» de la página (parte 8.3) |
| **Breizh Audio Box** | procesado de la voz en otro PC de la red local | menú 5.2 |
| **Difusión en directo** | hacer oír el audio del transceptor a unos pocos **oyentes** en Internet, sin cuenta en la estación: escuchan en la página de un servidor de difusión (canal privado con usuario y contraseña, o público); indicador **DIFUSIÓN** siempre visible en la página; tu voz durante tus transmisiones solo se difunde si lo pides; fuera de tus bandas, silencio para los oyentes (salvo ajuste contrario): su página dice el motivo (fuera de bandas, transmisión sin tu voz, sin audio del transceptor), igual que el menú 5.6 y el indicador 🔇; alerta en el teléfono al principio y al final | menú 5.6 (servidor y secretos dados por el administrador del servidor), menú 5.5 («Difusión en directo»), luego menú 5.6 o sección «Difusión en directo» de la página para lanzar y detener |
| **Repetición** de una grabación | volver a enviar en transmisión una grabación de la recepción | concedida en el asistente; en general **prohibida** en el servicio de aficionados |
| **Receptor SDR** (SDRplay) | segunda cascada y escucha (AM, FM, BLU, CW) de un SDR solo en recepción, junto al TRX; audio del SDR cortado durante toda transmisión; balance TRX / SDR y, con auriculares, una fuente por oído; zoom de la cascada («Zoom − / +» alrededor de la frecuencia escuchada, ◄ ► para desplazar la ventana), paleta de colores, ancho (como máximo el elegido en el menú 2.4) y antena A / B desde la página; spots del DX Cluster en la cascada del SDR (tocar un spot: el SDR lo escucha, el TRX no se mueve); la estación ralentiza o suspende el SDR por sí sola si está demasiado cargada; SDR EN ESPERA cuando nadie muestra su sección ni lo escucha desde hace 1 minuto (menos carga y calor), despertado en unos segundos al abrir la sección («SDR en espera… despertando»); SDR elegido y ajustado en el menú 2.4 de openRemoteTRX Console (búsqueda en todos los puertos USB y hubs); «QSY del TRX» hacia una frecuencia leída en el SDR; SDR en marcha: bajo la frecuencia del TRX, línea violeta «SDR» (frecuencia, modo, filtro escuchados; tocarla abre la sección SDR en su cascada), a la derecha dos bargraphs del audio oído (TRX: tocar = silencio en la página, restablecido en cada conexión; SDR: tocar = escucha lanzada o detenida, como «Escuchar»), S-metros «S-TRX» y «S-SDR» (S-SDR durante la escucha del SDR, aproximado «≈» mientras no esté calibrado: SDR en la frecuencia del TRX con «QSY TRX → SDR», una señal estable, luego «Calibrar el S-SDR con el TRX» en la sección SDR; calibración guardada en el navegador) | instalar primero la API SDRplay del fabricante, luego la estación; `trx-sdr --list` da el número de serie; `[sdr]` y «sdr» en `[modules] run` (menú 8.1) |

> **Receptor SDR: protege su entrada.** El SDR no soporta la potencia de tu TRX. Antena separada, o
> conmutador y secuenciador que pongan la entrada del SDR a masa antes de cualquier transmisión: te toca preverlo a ti,
> según tu material. La estación no puede hacerlo en tu lugar (una transmisión con el micrófono del transceptor solo se ve a
> posteriori). El SDR se designa por su **número de serie**: en una máquina que tenga varios, no pongas nunca el
> de un SDR usado por otra aplicación. Conéctalo a su propio puerto USB, nunca al hub del transceptor.
> La línea «Puertos USB» de la tarjeta ORDENADOR (panel, menú 1.3) dice si un bus USB está demasiado cargado o si
> el SDR va ralentizado; el detalle y el procedimiento están en el diagnóstico (menú 6.1). Una toma azul (USB 3)
> no acelera un SDR USB 2: comparte los 480 Mbit/s de la parte USB 2 del ordenador.

> **Seguridad.** Retransmitir a terceros lo que recibe la estación (visitantes, oyentes de la difusión)
> compromete tu responsabilidad, sobre todo fuera de las bandas de radioaficionado; por defecto, visitantes y oyentes solo oyen
> silencio fuera de tus bandas (dos ajustes independientes).

Según el transceptor, pueden faltar dos funciones de la página: el **espectro HF del transceptor** (solo por el segundo
puerto de un Icom como el IC-7300MK2; si no, solo se muestra el espectro de audio) y los **preajustes de filtro FIL1/2/3**
(propios de los Icom).

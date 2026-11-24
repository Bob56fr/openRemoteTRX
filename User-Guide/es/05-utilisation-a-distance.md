# 5. Usar la estación a distancia (fuera de la red local)

La estación no gestiona la red: escucha en una dirección y un puerto, y protege el acceso con usuario y
contraseña. Eres tú quien elige cómo tu teléfono la alcanza desde el exterior. La guía técnica completa:
https://github.com/Bob56fr/openRemoteTRX/blob/main/docs/acces-distant.md

## 5.1 Elegir: VPN o puerto abierto

| | A. VPN (recomendado) | B. Puerto abierto en el router |
|---|---|---|
| Principio | una VPN une el teléfono a la red de la estación | el router redirige un puerto de Internet hacia la estación |
| Ejemplos | WireGuard (a menudo integrado en el router), Tailscale, OpenVPN | router + nombre de dominio + certificado reconocido |
| Visible desde Internet | nada | la página de conexión |
| Audio (WebRTC, UDP) | pasa sin más | pasa a menudo, **no siempre** (router estricto, dirección compartida por el operador) |

Elige la VPN si dudas: no se expone nada, y el audio pasa.

## 5.2 Opción A: VPN

1. Instala la VPN que prefieras: servidor en el router o en el PC de la estación, cliente en el teléfono.
   Para Tailscale, una guía dedicada: https://github.com/Bob56fr/openRemoteTRX/blob/main/docs/acces-distant-tailscale.md
2. **Un perfil VPN por dispositivo**, nunca compartido. Dos dispositivos con el mismo perfil se roban el enlace: cortes
   cada 15 a 30 segundos.
3. Si la VPN llega **a tu red local** (VPN del router): nada que cambiar en la estación, usa la misma dirección
   que en casa. Si la VPN da al PC de la estación **una dirección aparte** (Tailscale, WireGuard en el PC):
   vuelve a lanzar el asistente (menú 2.1, acceso de red) para que el certificado cubra también esta dirección, luego repite
   el emparejamiento de la aplicación (menú 4.1).
4. En el teléfono, en 4G, VPN activa: abre la misma página `https://<direccion-de-la-estacion>:8443`.

En Android, solo puede estar activa una VPN a la vez. Con **Android Auto**, haz pasar por el túnel solo la
red de la estación (no todo el tráfico); si no, el coche rechaza el enlace: ajustes detallados en la guía
técnica, sección «Android Auto et VPN».

## 5.3 Opción B: puerto abierto en el router

Reservado a quien conoce su router y los certificados.

1. **Comprueba que es posible**: compara la dirección «WAN» de tu router con la que da un sitio «cuál es mi
   dirección IP». Si son distintas, tu operador comparte tu dirección (CGNAT): no se puede abrir ningún puerto,
   usa una VPN.
2. Un **nombre de dominio** que apunte a tu router (DNS dinámico si la dirección cambia).
3. Un **certificado reconocido**: lo más sencillo es un proxy HTTPS (Caddy) en el PC de la estación, que obtiene y
   renueva solo un certificado Let's Encrypt; la estación sigue entonces escuchando en local. Ejemplo y ajustes en
   la guía técnica, sección «Option B».
4. Redirige en el router el puerto 443 (TCP) hacia el PC de la estación.

> **Seguridad.** Con un puerto abierto, la **contraseña es tu única barrera**: larga y única para cada cuenta.
> La estación frena los intentos (5 fallos por minuto y por origen, 30 por cuarto de hora y por cuenta), pero una
> contraseña robada permite transmitir en tus bandas permitidas. Las seguridades de transmisión siguen activas en todos los
> casos, y el temporizador de transmisión del transceptor (parte 1) también.

## 5.4 Pruebas desde el exterior

Teléfono **en 4G** (Wi-Fi cortado), carga ficticia en el transceptor:

1. La página se abre (opción B: candado sin aviso).
2. Una contraseña errónea se rechaza.
3. La contraseña correcta conecta: frecuencia, S-metro, **audio recibido**.
4. Transmisión con carga ficticia: PTT, luego **STOP**; luego transmisión y paso a modo avión: vuelta a recepción.
5. Si la página se abre pero el audio no se establece: es el UDP el que no pasa (opción B): pasa a la VPN.

En caso de cortes repetidos, el menú 6.4 (calidad de la red) dice qué tramo falla: teléfono, red móvil,
túnel, router o estación.

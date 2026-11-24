# Poner en servicio una estación openRemoteTRX: guía del operador

Esta guía te acompaña, en orden, desde el desembalaje hasta el primer enlace desde el exterior. Vale para cualquier
transceptor conocido por Hamlib; lo que es propio de un modelo (driver USB, menús, puertos) está en su **ficha del
transceptor**:

- [Icom IC-7300MK2](postes/ic7300mk2.md): **validado** en un transceptor real;
- [Yaesu FTDX10](postes/ftdx10.md): preparado, **validación en curso**.

Para otro transceptor: su manual, la tabla «Según tu marca» del [inicio rápido](demarrage-rapide.md), y las
pruebas de la parte 3, que sirven de validación: hazlas todas, con carga ficticia, e informa del resultado
(parte 8, «Pedir ayuda»). Estado de cada transceptor probado: https://bob56fr.github.io/openRemoteTRX/postes/

> **¿Con prisa?** El [inicio rápido](demarrage-rapide.md) lleva del transceptor conectado a la página web en un
> cuarto de hora, TOT del transceptor incluido. Vuelve a las partes de abajo ante el primer problema.

## El recorrido

| Parte | Lo que haces | Duración orientativa |
|---|---|---|
| [Inicio rápido](demarrage-rapide.md) | lo esencial para impacientes, pruebas de seguridad incluidas | 15 min |
| [0. Antes de empezar](00-avant-de-commencer.md) | material, reglamentación, elección entre Debian, Raspberry Pi o Windows | 15 min de lectura |
| [1. Preparar el transceptor](01-preparer-le-poste.md) | cableado, driver USB, menús del transceptor | 30 min |
| [2. Instalar la estación](02-installer-la-station.md) | software en el PC o en la Raspberry Pi | 20 min (Pi: 1 h con la tarjeta SD) |
| [3. Integrar el TRX y probarlo](03-integrer-et-essayer-le-trx.md) | asistente, pruebas en recepción y luego en transmisión, pruebas de seguridad | 1 h 30 |
| [4. Usar en la red local](04-utilisation-sur-le-lan.md) | página web, teléfono, aplicación Android | 30 min |
| [5. Usar a distancia](05-utilisation-a-distance.md) | VPN o puerto expuesto, prueba en 4G | 1 h |
| [6. Estación sin vigilancia](06-station-sans-surveillance.md) | alertas, rearranque tras un corte, protecciones | 30 min |
| [7. Explotación diaria](07-exploitation-au-quotidien.md) | arrancar, vigilar, actualizar, hacer copias de seguridad | para leer |
| [8. Solución de problemas](08-depannage.md) | códigos de error, problemas frecuentes, pedir ayuda | según necesidad |
| [9. Funciones opcionales](09-fonctions-facultatives.md) | visitantes, DX Cluster, FreeDV, SELCALL, ROE… | a elección |
| [Glosario](glossaire.md) | las palabras del proyecto: quién es qué | según necesidad |
| [10. Resumen para marcar](10-recapitulatif.md) | saber en qué punto estás | |

Fichas de transceptor: [Icom IC-7300MK2](postes/ic7300mk2.md), [Yaesu FTDX10](postes/ftdx10.md). Esquema de los
bloques de la estación: parte 0, «Cómo está organizado».

## Cómo leer esta guía

- Los **menús de openRemoteTRX Console** se indican por su número: «menú 2.1» = tema 2 (Transceptor y hardware), menú 1. En Windows, el
  acceso directo menú Inicio > **openRemoteTRX** abre la misma consola (parte 2). La consola se abre en **pantalla completa**:
  temas a la izquierda con su pictograma (flechas e Intro), ayuda del menú elegido a la derecha; también se puede teclear el
  número en la consola de texto (`trx-console --texte`).
- Un recuadro **«Seguridad»** señala un punto que afecta a la transmisión: no te lo saltes.
- Lo que cambia según el sistema está ordenado en **pestañas** Debian / Raspberry Pi / Windows: elige la tuya
  una vez y se recuerda para toda la página. En GitHub, las pestañas se leen una debajo de otra.
- Esta guía existe también como página web, con un resumen que se marca en línea, y en **PDF** para imprimir
  (enlace «Descargar en PDF» arriba de la página): https://bob56fr.github.io/openRemoteTRX/guide/es/

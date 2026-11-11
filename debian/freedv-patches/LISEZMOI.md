# Correctifs des décodeurs FreeDV (étape 164)

Appliqués avant de compiler les décodeurs utilisés par `trxstation/freedv/` ; proposés à l'équipe FreeDV.

- `radae_rx-windows-binary-stdin.patch` (rade_c c8a3dc1, `src/radae_rx.c`) : sous Windows, stdin et stdout en mode
  binaire (sinon 0 symbole traité : un octet 0x1A arrête la lecture) et stderr sans tampon (sinon lignes d'état
  par paquets de 4 ko).
- `freedv-ka9q-windows-stdin.patch` (freedv-integrations v2.4.1, `src/ka9q/main.cpp`) : Linux ET Windows, pause
  seulement quand rien n'a été lu (sinon débit sous le temps réel : 0,993 sous Linux, ~0,6 sous Windows) ;
  Windows : lecture bloquante au lieu de `select()` sur stdin, `strerror`, stderr sans tampon.

Compilation croisée Windows (depuis Debian, MinGW variante posix) : `-DDISABLE_TLS_SUPPORT=ON
-DUSE_STATIC_EBUR128=ON -DUSE_STATIC_SAMPLERATE=ON`, `CMAKE_C_FLAGS=-DWIN32`, `CMAKE_CXX_FLAGS=-DWIN32 -include
winsock2.h -include ws2tcpip.h`, `CMAKE_CXX_STANDARD_LIBRARIES=-lws2_32 -liphlpapi`, `CMAKE_EXE_LINKER_FLAGS=-static-libgcc
-static-libstdc++` ; livrer `librade.dll`, `libwinpthread-1.dll`, `libssp-0.dll` avec les exécutables.

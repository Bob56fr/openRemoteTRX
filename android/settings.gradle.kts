// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Application Android openRemoteTRX : docs/android-cahier-des-charges.md
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "openRemoteTRX"
// Kotlin pur, testé sans émulateur : protocole (contrat avec la station) et logique (PTT, battements, liaison).
include(":protocol", ":logic")
// Android : service, WebRTC, audio, comptes (:core) ; écrans (:app).
include(":core", ":app")

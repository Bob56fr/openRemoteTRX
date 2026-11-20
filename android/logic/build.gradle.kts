// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.kotlin.jvm)
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    api(project(":protocol"))
    implementation(libs.serialization.json)
    implementation(libs.zxing.core)                                  // QR code d'appairage lu dans une image (QrImage)
    testImplementation(kotlin("test"))
}

// Tronc commun des textes (trxstation/i18n/client.<langue>.json, refus et coupures) copié dans les ressources à chaque
// compilation : mêmes textes que la station et la page web (cahier docs/application-traduction-cahier-des-charges.md)
val i18nDir = layout.buildDirectory.dir("generated/i18n")
val copyI18n by tasks.registering(Copy::class) {
    from(rootProject.file("../trxstation/i18n")) { include("client.*.json", "shared.*.json") }
    into(i18nDir.map { it.dir("i18n") })
}
sourceSets["main"].resources.srcDir(i18nDir)
tasks.processResources { dependsOn(copyI18n) }

tasks.test {
    useJUnitPlatform()
    // Exemples partagés avec la station et la page (tests/protocol/) et sources de la page (textes à garder alignés)
    systemProperty("trx.repo", rootProject.file("..").absolutePath)
    // Fichiers partagés lus par les tests : déclarés, sinon Gradle croit les tests à jour quand seuls eux changent
    inputs.dir(rootProject.file("../trxstation/gateway/api/static"))
    inputs.dir(rootProject.file("../tests/protocol"))
    inputs.dir(rootProject.file("../trxstation/i18n"))                  // TextsTest : tronc commun des textes
    inputs.dir(rootProject.file("core/src/main/assets/pochettes"))     // ArtworkTest : une image par clé
    inputs.dir(rootProject.file("core/src/main/kotlin"))               // I18nAppTest : cliquet de :core et :app
    inputs.dir(rootProject.file("app/src/main/kotlin"))
}

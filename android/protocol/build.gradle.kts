// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    implementation(libs.serialization.json)
    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
    // Exemples partagés avec la station et la page (tests/protocol/) et sources de la page (textes à garder alignés)
    systemProperty("trx.repo", rootProject.file("..").absolutePath)
    // Fichiers partagés lus par les tests : déclarés, sinon Gradle croit les tests à jour quand seuls eux changent
    inputs.dir(rootProject.file("../tests/protocol"))
}

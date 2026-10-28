// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Partie Android du client : RigService (seul propriétaire de la connexion), WebRTC, audio, comptes.
plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.rfdiy.openremotetrx.core"
    compileSdk = 37
    defaultConfig { minSdk = 29 }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    api(project(":protocol"))
    api(project(":logic"))
    api(libs.coroutines.android)
    implementation(libs.androidx.core.ktx)
    implementation(libs.serialization.json)
    implementation(libs.webrtc)
    testImplementation(kotlin("test"))
}

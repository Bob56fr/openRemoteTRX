// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Application openRemoteTRX : écrans du smartphone (Compose). La connexion appartient à RigService (:core).
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.rfdiy.openremotetrx.app"
    compileSdk = 37
    defaultConfig {
        applicationId = "com.rfdiy.openremotetrx"      // ne jamais le changer
        minSdk = 29                                     // Android 10 (décision de l'utilisateur)
        targetSdk = 36
        versionCode = 19
        versionName = "0.16.0"
    }
    buildTypes {
        release { isMinifyEnabled = false }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { compose = true }
}

dependencies {
    implementation(project(":core"))
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.material3)
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    // Lecture du QR code d'appairage (Apache-2.0, sans services Google)
    implementation(libs.zxing.embedded)
    implementation(libs.zxing.core)
    debugImplementation(libs.compose.ui.tooling)
}

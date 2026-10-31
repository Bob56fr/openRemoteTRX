// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Application openRemoteTRX : écrans du smartphone (Compose). La connexion appartient à RigService (:core).
import java.util.Properties

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
        versionCode = 32
        versionName = "0.28.0"
        buildConfigField("boolean", "SCRAMBLER", "true")
    }
    // Clé d'envoi Google Play : HORS DU DÉPÔT (docs/android-play-store.md). Fichier android/keystore.properties
    // (storeFile, storePassword, keyAlias, keyPassword), ou un autre chemin par -PkeystoreProperties=...
    val keystoreFile = rootProject.file(providers.gradleProperty("keystoreProperties").getOrElse("keystore.properties"))
    val keystore = Properties().apply { if (keystoreFile.exists()) keystoreFile.inputStream().use { load(it) } }
    signingConfigs {
        if (keystoreFile.exists()) create("upload") {
            storeFile = keystoreFile.parentFile.resolve(keystore.getProperty("storeFile"))
            storePassword = keystore.getProperty("storePassword")
            keyAlias = keystore.getProperty("keyAlias")
            keyPassword = keystore.getProperty("keyPassword")
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("upload")
        }
        // Google Play (bundlePlay -> app/build/outputs/bundle/play/app-play.aab) : comme release, SANS le scrambler
        // (codage interdit en bandes radioamateur, UIT RR art. 25 ; l'application publiée ne le propose pas).
        create("play") {
            initWith(getByName("release"))
            matchingFallbacks += "release"
            buildConfigField("boolean", "SCRAMBLER", "false")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { compose = true; buildConfig = true }
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

// Envoi au Play Store : une construction non signée serait refusée par la Play Console ; le dire avant de construire.
tasks.matching { it.name == "prePlayBuild" }.configureEach {
    doFirst {
        if (android.signingConfigs.findByName("upload") == null)
            throw GradleException("Clé d'envoi absente : créer android/keystore.properties (docs/android-play-store.md).")
    }
}

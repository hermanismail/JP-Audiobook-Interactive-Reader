plugins {
    id("com.android.application")
}

android {
    namespace = "com.misao.jpaudiobookplayer"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.misao.jpaudiobookplayer"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

// Built-in Kotlin (AGP 9+) reads compiler options from this top-level `kotlin {}`
// block - no separate Kotlin plugin ID needed (see root build.gradle.kts).
kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.documentfile:documentfile:1.0.1")
}

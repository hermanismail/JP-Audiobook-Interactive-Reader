// AGP 9.0+ has built-in Kotlin support, so no separate org.jetbrains.kotlin.android
// plugin is applied here (applying it alongside built-in Kotlin causes a Gradle
// error). See app/build.gradle.kts for the Kotlin compiler options block.
plugins {
    id("com.android.application") version "9.3.2" apply false
}

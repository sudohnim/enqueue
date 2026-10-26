buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        classpath("com.android.tools.build:gradle:8.11.0")
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:1.9.25")
    }
}

allprojects {
    repositories {
        google()
        mavenCentral()
    }
    // A plugin module (the barcode scanner, Tauri's own) is compiled into this app, never
    // published as an AAR, so it has no use for the typedef annotations a library ships.
    // Extracting them pulls in ~80 MB of lint tooling (intellij-core, kotlin-compiler)
    // that Google's CDN repeatedly cut off mid-download, failing every release build.
    tasks.matching { it.name.startsWith("extract") && it.name.endsWith("Annotations") }
        .configureEach { enabled = false }
}

tasks.register("clean").configure {
    delete("build")
}


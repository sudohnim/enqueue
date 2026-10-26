# Add project specific ProGuard rules here.
# You can control the set of applied configuration files using the
# proguardFiles setting in build.gradle.
#
# For more details, see
#   http://developer.android.com/guide/developing/tools/proguard.html

# If your project uses WebView with JS, uncomment the following
# and specify the fully qualified class name to the JavaScript interface
# class:
#-keepclassmembers class fqcn.of.javascript.interface.for.webview {
#   public *;
#}

# Uncomment this to preserve the line number information for
# debugging stack traces.
#-keepattributes SourceFile,LineNumberTable

# If you keep the line number information, uncomment this to
# hide the original source file name.
#-renamesourcefileattribute SourceFile
# Enqueue's own classes are reached by NAME from Rust over JNI (desktop/src/lib.rs:
# MainActivity.storeKey, MainActivity.getCurrentActivity, SyncForegroundService,
# CameraHelper, Biometrics callbacks) and from the page (the EnqueueAndroid
# @JavascriptInterface bridge). Nothing in Kotlin calls most of them, so R8 strips or
# renames them in a release build and the app dies at launch with "store key: Java
# exception was thrown". The classes are few and small: keep them whole.
-keep class com.sudohnim.enqueue.** { *; }
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}

# RevenueCat (Billing.kt): its own consumer rules cover it; kept whole as Dequeue does,
# since a stripped model class fails only at purchase time, on a release build.
-keep class com.revenuecat.purchases.** { *; }

# Credential Manager finds its Play Services provider by name (SignIn.kt).
-if class androidx.credentials.CredentialManager
-keep class androidx.credentials.playservices.** { *; }

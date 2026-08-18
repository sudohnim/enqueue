package com.sudohnim.enqueue

import android.Manifest
import android.os.Bundle
import android.webkit.WebView
import androidx.activity.enableEdgeToEdge
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : TauriActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()
    // Enable WebView debugging for chrome://inspect
    WebView.setWebContentsDebuggingEnabled(true)
    super.onCreate(savedInstanceState)

    // QR.4a: allow video autoplay without user gesture (muted stream from camera)
    // Android WebView defaults to TRUE, which blocks even muted <video> autoplay.
    // Setting this to false allows the camera stream to play in the setup screen.
    val webView = window?.findViewById<WebView>(android.R.id.web)
    if (webView != null) {
        webView.webSettings.mediaPlaybackRequiresUserGesture = false
    }

    // Request CAMERA permission before opening the camera in the Tauri WebView
    if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
      != android.content.pm.PackageManager.PERMISSION_GRANTED
    ) {
      ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CAMERA), 1)
    }
  }

  override fun onRequestPermissionsResult(
    requestCode: Int,
    permissions: Array<out String>,
    grantResults: IntArray,
  ) {
    super.onRequestPermissionsResult(requestCode, permissions, grantResults)
  }
}
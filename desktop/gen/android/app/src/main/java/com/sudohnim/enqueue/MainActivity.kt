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
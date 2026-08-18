package com.sudohnim.enqueue

import android.os.Bundle
import android.webkit.WebView
import androidx.activity.enableEdgeToEdge

class MainActivity : TauriActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()
    // Enable WebView debugging for chrome://inspect
    WebView.setWebContentsDebuggingEnabled(true)
    super.onCreate(savedInstanceState)
    // Camera permission is handled by the barcode scanner plugin at scan time
  }
}
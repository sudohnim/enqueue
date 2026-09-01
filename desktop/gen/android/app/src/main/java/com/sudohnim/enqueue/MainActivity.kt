package com.sudohnim.enqueue

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.webkit.WebView
import androidx.activity.enableEdgeToEdge
import com.sudohnim.enqueue.CameraHelper
import java.util.concurrent.CompletableFuture

class MainActivity : TauriActivity() {
  companion object {
    private var uiHandler: Handler? = null
    private var currentActivity: MainActivity? = null
    // Store the MainActivity class for JNI access
    @JvmStatic
    var mainActivityClass: Class<MainActivity>? = null
    
    fun initUiHandler(activity: MainActivity) {
      uiHandler = Handler(Looper.getMainLooper())
      mainActivityClass = activity.javaClass
    }
    
    fun runOnUiThread(runnable: Runnable) {
      uiHandler?.post(runnable)
    }
    
    @JvmStatic
    fun getCurrentActivity(): MainActivity {
      return currentActivity ?: throw IllegalStateException("Activity not initialized")
    }
  }

  // Instance method to capture image - called from JNI via activity instance
  fun captureImage(): CompletableFuture<String> {
    val future = CompletableFuture<String>()
    uiHandler?.post {
      try {
        val helper = CameraHelper.getInstance(this)
        val captureFuture = helper.captureImage()
        captureFuture.whenComplete { result, ex ->
          if (ex != null) {
            future.completeExceptionally(ex)
          } else {
            future.complete(result)
          }
        }
      } catch (e: Exception) {
        future.completeExceptionally(e)
      }
    }
    return future
  }

  // Instance method to pick an image from the gallery - called from JNI. Mirrors
  // captureImage: post to the UI thread, then hand back the CameraHelper's future.
  fun pickImage(): CompletableFuture<String> {
    val future = CompletableFuture<String>()
    uiHandler?.post {
      try {
        val helper = CameraHelper.getInstance(this)
        val pickFuture = helper.pickImage()
        pickFuture.whenComplete { result, ex ->
          if (ex != null) {
            future.completeExceptionally(ex)
          } else {
            future.complete(result)
          }
        }
      } catch (e: Exception) {
        future.completeExceptionally(e)
      }
    }
    return future
  }

  override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()
    WebView.setWebContentsDebuggingEnabled(true)
    super.onCreate(savedInstanceState)
    MainActivity.initUiHandler(this)
    currentActivity = this
    CameraHelper.getInstance(this)
  }

  override fun onActivityResult(
    requestCode: Int,
    resultCode: Int,
    data: Intent?,
  ) {
    super.onActivityResult(requestCode, resultCode, data)
    val handled = CameraHelper.getInstance(this).onActivityResult(requestCode, resultCode, data)
    if (!handled) {
    }
  }
}
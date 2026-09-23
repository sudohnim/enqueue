package com.sudohnim.enqueue

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.webkit.WebView
import androidx.activity.enableEdgeToEdge
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
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
    applySystemBarInsets()
  }

  /**
   * Reserve the status bar and navigation bar strips for the WebView.
   *
   * `enableEdgeToEdge()` lets the WebView paint the full window, which is what we want
   * for the wash and the scrolling list - but it also means the top of the page renders
   * underneath the clock, the status icons and the camera cutout. CSS cannot fix that on
   * its own: Android only reports a DISPLAY CUTOUT through `env(safe-area-inset-*)`,
   * never the system bars, so the library hero's raven collided with the status bar.
   *
   * Padding the content view by the system-bar insets keeps the page out of both strips.
   * The cutout is deliberately NOT added here: where a cutout exists it sits inside the
   * status bar strip on essentially every phone, and the stylesheet already adds
   * `env(safe-area-inset-*)` on top of this padding - including it would double-count.
   */
  private fun applySystemBarInsets() {
    val content = findViewById<View>(android.R.id.content) ?: return
    ViewCompat.setOnApplyWindowInsetsListener(content) { view, insets ->
      val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
      view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
      insets
    }
    ViewCompat.requestApplyInsets(content)
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
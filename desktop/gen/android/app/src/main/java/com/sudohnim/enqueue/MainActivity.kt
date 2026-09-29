package com.sudohnim.enqueue

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.webkit.JavascriptInterface
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

    /**
     * The launcher popup just saved a capture: if the app is running, have the page file
     * it into the library now rather than the next time it comes to the front.
     */
    fun drainQuickCaptures() {
      val activity = currentActivity?.takeIf { !it.isDestroyed } ?: return
      val wv = activity.webView ?: return
      wv.post {
        wv.evaluateJavascript(
          "window.__enqDrainQuickInbox && window.__enqDrainQuickInbox()",
          null,
        )
      }
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

  private var webView: WebView? = null

  inner class EnqueueBridge {
    /** Captures the launcher popup saved, oldest first: a JSON array of {id, text}. */
    @JavascriptInterface
    fun quickCaptures(): String = QuickCaptureInbox.list(this@MainActivity)

    /** The page filed this popup capture into the library: forget it. */
    @JavascriptInterface
    fun ackQuickCapture(id: String) = QuickCaptureInbox.ack(this@MainActivity, id)

    /**
     * The page's ground drifts with the time of day (js/ground.js). The status and
     * navigation bar strips this activity pads for show the window background, so
     * they follow the same colour instead of staying the daytime lavender.
     */
    @JavascriptInterface
    fun setGround(hex: String) {
      val color = runCatching { android.graphics.Color.parseColor(hex) }.getOrNull() ?: return
      runOnUiThread { window.decorView.setBackgroundColor(color) }
    }
  }

  override fun onWebViewCreate(webView: WebView) {
    super.onWebViewCreate(webView)
    this.webView = webView
    webView.addJavascriptInterface(EnqueueBridge(), "EnqueueAndroid")
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
   * Reserve the status bar, navigation bar and display-cutout strips for the WebView,
   * and make this the ONLY place that does.
   *
   * `enableEdgeToEdge()` lets the WebView paint the full window, so without padding the
   * page renders under the clock, the status icons and the camera cutout. Padding the
   * content view by the union of the system bars and the cutout keeps the page out of
   * all of them, in every orientation.
   *
   * The insets are then CONSUMED so the WebView never sees them: otherwise Chromium
   * still reports the cutout through `env(safe-area-inset-*)` (66px on a Pixel 10 Pro)
   * and every page rule that adds it double-counts the space this padding already
   * reserved - the library opened under ~86px of empty lavender.
   */
  private fun applySystemBarInsets() {
    val content = findViewById<View>(android.R.id.content) ?: return
    ViewCompat.setOnApplyWindowInsetsListener(content) { view, insets ->
      val safe = insets.getInsets(
        WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout(),
      )
      view.setPadding(safe.left, safe.top, safe.right, safe.bottom)
      WindowInsetsCompat.CONSUMED
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
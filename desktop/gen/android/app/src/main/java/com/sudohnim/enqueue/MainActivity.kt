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
import java.util.concurrent.atomic.AtomicReference

class MainActivity : TauriActivity() {
  companion object {
    /** The launcher shortcut's action (res/xml/shortcuts.xml). */
    const val ACTION_QUICK_CAPTURE = "com.sudohnim.enqueue.QUICK_CAPTURE"

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

  // ---- Quick capture from the launcher shortcut --------------------------------
  // The shortcut starts (or re-fronts) this activity with ACTION_QUICK_CAPTURE. The
  // page learns about it two ways, whichever lands first: it PULLS the pending
  // action at boot over the EnqueueAndroid bridge, and we PUSH it in with
  // evaluateJavascript once the page's handler exists (a warm start, or a cold start
  // where the bridge call ran before the page was ready). `pendingLaunch` is taken
  // with getAndSet so the sheet never opens twice for one launch.
  private val pendingLaunch = AtomicReference<String?>(null)
  private var webView: WebView? = null

  inner class EnqueueBridge {
    /** The pending launch action ("quick-capture"), consumed on read; "" if none. */
    @JavascriptInterface
    fun takeLaunchAction(): String = pendingLaunch.getAndSet(null) ?: ""

    /** The quick capture is done: hand the phone back to whatever was in front. */
    @JavascriptInterface
    fun finishQuickCapture() {
      runOnUiThread { moveTaskToBack(true) }
    }

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
    pushLaunchAction(0)
  }

  private fun recordLaunch(intent: Intent?) {
    if (intent?.action == ACTION_QUICK_CAPTURE) pendingLaunch.set("quick-capture")
  }

  // Deliver a pending action into the page, retrying until the page's handler is
  // installed (about 10s at most, then the boot-time pull is the only path left).
  private fun pushLaunchAction(attempt: Int) {
    val wv = webView ?: return
    val action = pendingLaunch.getAndSet(null) ?: return
    wv.post {
      wv.evaluateJavascript(
        "(function(){if(typeof window.__enqLaunchAction!=='function')return 'wait';" +
          "window.__enqLaunchAction('" + action + "');return 'ok';})()",
      ) { result ->
        if (result?.contains("wait") == true) {
          pendingLaunch.compareAndSet(null, action)
          if (attempt < 40) wv.postDelayed({ pushLaunchAction(attempt + 1) }, 250)
        }
      }
    }
  }

  override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    setIntent(intent)
    recordLaunch(intent)
    pushLaunchAction(0)
  }

  override fun onCreate(savedInstanceState: Bundle?) {
    recordLaunch(intent)
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
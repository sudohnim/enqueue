package com.sudohnim.enqueue

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.widget.Button
import androidx.activity.OnBackPressedCallback
import androidx.activity.enableEdgeToEdge
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.sudohnim.enqueue.CameraHelper
import java.util.concurrent.CompletableFuture
import org.json.JSONObject

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
    
    /** Away longer than this and the app lock asks again. */
    private const val LOCK_GRACE_MS = 60_000L

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
      runOnUiThread {
        groundColor = color
        window.decorView.setBackgroundColor(color)
        lockCover?.setBackgroundColor(color)
      }
    }

    // ---- fingerprint lock (BIO.1) -------------------------------------------------
    // A prompt answers later, so the calls that show one take a request id and the
    // answer comes back through window.__enqLockReply(id, {ok, reason, secret?}).

    /** What this phone can do and what is switched on, as JSON. */
    @JavascriptInterface
    fun lockStatus(): String = JSONObject()
      .put("fingerprint", bio.fingerprintState())
      .put("deviceLock", bio.deviceLockState())
      .put("appLock", bio.appLock)
      .put("vaultSecret", bio.hasVaultSecret())
      .toString()

    /** Turn the app lock on or off. Either way the owner confirms first. */
    @JavascriptInterface
    fun setAppLock(requestId: String, on: Boolean) {
      runOnUiThread {
        if (on && bio.deviceLockState() != "ready") {
          reply(requestId, false, "none")
        } else {
          val title = getString(if (on) R.string.app_lock_prompt_on else R.string.app_lock_prompt_off)
          bio.confirm(title, getString(R.string.app_lock_prompt_subtitle)) { ok ->
            if (ok) {
              bio.appLock = on
              applyRecentsPrivacy()
            }
            reply(requestId, ok, if (ok) "ok" else "cancelled")
          }
        }
      }
    }

    /**
     * Vault fingerprint unlock. The page supplies the prompt's words, because the vault
     * is entered through a decoy and the prompt must not name it.
     */
    @JavascriptInterface
    fun vaultSecretCreate(requestId: String, title: String, subtitle: String, cancel: String) {
      runOnUiThread {
        bio.createVaultSecret(title, subtitle, cancel) { secret, reason ->
          reply(requestId, secret != null, reason, secret)
        }
      }
    }

    @JavascriptInterface
    fun vaultSecretRead(requestId: String, title: String, subtitle: String, cancel: String) {
      runOnUiThread {
        bio.readVaultSecret(title, subtitle, cancel) { secret, reason ->
          reply(requestId, secret != null, reason, secret)
        }
      }
    }

    @JavascriptInterface
    fun vaultSecretClear() = bio.clearVaultSecret()
  }

  private fun reply(requestId: String, ok: Boolean, reason: String, secret: String? = null) {
    val wv = webView ?: return
    val payload = JSONObject().put("ok", ok).put("reason", reason)
    if (secret != null) payload.put("secret", secret)
    val script =
      "window.__enqLockReply && window.__enqLockReply(${JSONObject.quote(requestId)}, $payload)"
    wv.post { wv.evaluateJavascript(script, null) }
  }

  // ---- the app lock (BIO.1) -------------------------------------------------------
  // When the person turns it on, Enqueue opens behind a native cover and asks for a
  // fingerprint (or the phone's screen lock). It locks again after LOCK_GRACE_MS in the
  // background, so stepping out to the camera, the file picker or a browser link does
  // not ask again on the way back. The quick-capture popup is not locked: it can only
  // add a thought, never show the library.
  private lateinit var bio: Biometrics
  private var locked = false
  private var prompting = false
  private var autoPrompt = false
  private var stoppedAt = 0L
  private var lockCover: View? = null
  private var groundColor: Int? = null

  private fun lock() {
    locked = true
    autoPrompt = true
    if (lockCover == null) {
      val cover = layoutInflater.inflate(R.layout.view_app_lock, null)
      groundColor?.let { cover.setBackgroundColor(it) }
      cover.findViewById<Button>(R.id.app_lock_unlock).setOnClickListener { promptUnlock() }
      (window.decorView as ViewGroup).addView(
        cover,
        ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT),
      )
      lockCover = cover
    }
    // The page is still there behind the cover: keep a screen reader out of it too.
    findViewById<View>(android.R.id.content)?.importantForAccessibility =
      View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
  }

  private fun unlock() {
    locked = false
    autoPrompt = false
    stoppedAt = 0L
    lockCover?.let { (it.parent as? ViewGroup)?.removeView(it) }
    lockCover = null
    findViewById<View>(android.R.id.content)?.importantForAccessibility =
      View.IMPORTANT_FOR_ACCESSIBILITY_AUTO
  }

  private fun promptUnlock() {
    if (!locked || prompting) return
    if (bio.deviceLockState() != "ready") {
      // The phone no longer has a fingerprint or a screen lock (removing one takes the
      // owner's credential), so there is nothing left to check against. Switch the lock
      // off rather than shut the owner out of their own library.
      bio.appLock = false
      applyRecentsPrivacy()
      unlock()
      return
    }
    prompting = true
    bio.confirm(
      getString(R.string.app_lock_prompt_title),
      getString(R.string.app_lock_prompt_subtitle),
    ) { ok ->
      prompting = false
      if (ok) unlock()
    }
  }

  /**
   * A locked app must not show its last screen in the recents list. Android 13+ can
   * hide just that thumbnail; older versions only offer FLAG_SECURE, which also blocks
   * screenshots - the right trade once someone has asked for a lock.
   */
  private fun applyRecentsPrivacy() {
    val on = bio.appLock
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
      setRecentsScreenshotEnabled(!on)
    } else if (on) {
      window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
    } else {
      window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
    }
  }

  override fun onStart() {
    super.onStart()
    if (!::bio.isInitialized || !bio.appLock) return
    val away = if (stoppedAt == 0L) 0L else SystemClock.elapsedRealtime() - stoppedAt
    if (!locked && away >= LOCK_GRACE_MS) lock()
    if (locked) autoPrompt = true
  }

  override fun onResume() {
    super.onResume()
    // Ask once each time the app comes to the front. A cancelled prompt leaves the
    // cover and its Unlock button, rather than asking again in a loop.
    if (locked && autoPrompt && !prompting) {
      autoPrompt = false
      window.decorView.post { promptUnlock() }
    }
  }

  override fun onStop() {
    super.onStop()
    if (!locked) stoppedAt = SystemClock.elapsedRealtime()
  }

  override fun onWebViewCreate(webView: WebView) {
    super.onWebViewCreate(webView)
    this.webView = webView
    webView.addJavascriptInterface(EnqueueBridge(), "EnqueueAndroid")
    handleBackInThePage(webView)
  }

  override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()
    WebView.setWebContentsDebuggingEnabled(true)
    super.onCreate(savedInstanceState)
    MainActivity.initUiHandler(this)
    currentActivity = this
    CameraHelper.getInstance(this)
    applySystemBarInsets()
    bio = Biometrics(this)
    applyRecentsPrivacy()
    if (bio.appLock) lock() // before the first frame: the library never flashes
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
   *
   * The on-screen keyboard is reserved the same way. Edge-to-edge turns off the
   * window's own adjustResize, so without this the keyboard was drawn OVER the page -
   * a note being written disappeared under it. Padding the bottom by the larger of the
   * navigation bar and the keyboard shrinks the WebView to the space above the
   * keyboard, so every screen (and its visual viewport) simply gets shorter.
   */
  private fun applySystemBarInsets() {
    val content = findViewById<View>(android.R.id.content) ?: return
    ViewCompat.setOnApplyWindowInsetsListener(content) { view, insets ->
      val safe = insets.getInsets(
        WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout(),
      )
      val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
      view.setPadding(safe.left, safe.top, safe.right, maxOf(safe.bottom, ime.bottom))
      WindowInsetsCompat.CONSUMED
    }
    ViewCompat.requestApplyInsets(content)
  }

  /**
   * Back asks the page first. The generated WryActivity goes back only when the
   * WebView has back history, and Chromium skips history entries a page pushes on its
   * own, so Back closed the app from the reader and the writing page. The page's
   * `window.__enqBack()` closes its innermost layer and answers whether it did; only
   * when it had nothing to close does the app go to the background, as a root
   * activity's Back does. Registered after WryActivity's callback, so it runs first.
   */
  private fun handleBackInThePage(webView: WebView) {
    onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
      override fun handleOnBackPressed() {
        if (locked) {
          moveTaskToBack(true) // nothing behind the lock answers Back
          return
        }
        webView.evaluateJavascript(
          "(window.__enqBack && window.__enqBack()) ? 'handled' : 'none'",
        ) { answer ->
          if (answer?.contains("handled") != true) moveTaskToBack(true)
        }
      }
    })
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
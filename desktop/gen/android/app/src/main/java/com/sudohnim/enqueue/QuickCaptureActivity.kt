package com.sudohnim.enqueue

import android.os.Bundle
import android.text.SpannableString
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.view.View
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding

/**
 * The launcher long-press "Quick capture": a sheet that floats over whatever app was in
 * front, instead of opening Enqueue (Dequeue's QuickAddActivity, drawn natively because
 * a Tauri app has one WebView and it belongs to MainActivity).
 *
 * Translucent and in its own task (AndroidManifest), so saving or dismissing returns the
 * person straight to where they were. Save writes the text to QuickCaptureInbox and
 * closes at once; the page files it into the library, immediately when the app is
 * already running (MainActivity.drainQuickCaptures), else the next time it opens.
 * Dismissing keeps the draft for next time, like the desktop overlay's Escape.
 */
class QuickCaptureActivity : ComponentActivity() {
  private companion object {
    const val PREFS = "quick_capture"
    const val DRAFT = "draft"
  }

  private lateinit var field: EditText
  private var saved = false

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    // Draw under the system bars; the insets listener below lifts the sheet above the
    // navigation bar and the keyboard (the manifest asks for the keyboard up front).
    WindowCompat.setDecorFitsSystemWindows(window, false)
    setContentView(R.layout.activity_quick_capture)

    val title = getString(R.string.quick_capture_title) + "."
    view<TextView>(R.id.qcap_title).text =
      SpannableString(title).apply {
        setSpan(
          ForegroundColorSpan(ContextCompat.getColor(this@QuickCaptureActivity, R.color.purple_bold)),
          title.length - 1,
          title.length,
          Spanned.SPAN_EXCLUSIVE_EXCLUSIVE,
        )
      }

    field = view(R.id.qcap_field)
    field.setText(getSharedPreferences(PREFS, MODE_PRIVATE).getString(DRAFT, ""))
    field.setSelection(field.text.length)

    view<View>(R.id.qcap_scrim).setOnClickListener { finish() }
    view<Button>(R.id.qcap_save).setOnClickListener { save() }

    // Lay the sheet out above the navigation bar and, while it is open, the keyboard.
    val sheet = view<View>(R.id.qcap_sheet)
    val basePad = sheet.paddingBottom
    ViewCompat.setOnApplyWindowInsetsListener(view(R.id.qcap_root)) { _, insets ->
      val bottom = maxOf(
        insets.getInsets(WindowInsetsCompat.Type.ime()).bottom,
        insets.getInsets(WindowInsetsCompat.Type.navigationBars()).bottom,
      )
      sheet.updatePadding(bottom = basePad + bottom)
      insets
    }

    field.requestFocus()
    field.post {
      getSystemService(InputMethodManager::class.java)
        ?.showSoftInput(field, InputMethodManager.SHOW_IMPLICIT)
    }
  }

  private fun <T : View> view(id: Int): T = requireNotNull(findViewById(id)) { "missing view $id" }

  private fun save() {
    val text = field.text.toString().trim()
    if (text.isEmpty()) {
      field.requestFocus()
      return
    }
    if (!QuickCaptureInbox.add(this, text)) {
      view<TextView>(R.id.qcap_status).apply {
        setText(R.string.quick_capture_failed)
        visibility = View.VISIBLE
      }
      return
    }
    saved = true
    getSharedPreferences(PREFS, MODE_PRIVATE).edit().remove(DRAFT).apply()
    MainActivity.drainQuickCaptures()
    Toast.makeText(applicationContext, R.string.quick_capture_saved, Toast.LENGTH_SHORT).show()
    finish()
  }

  // Leaving without saving (scrim, back, home, another app) keeps the words for next time.
  override fun onPause() {
    super.onPause()
    if (saved) return
    getSharedPreferences(PREFS, MODE_PRIVATE).edit()
      .putString(DRAFT, field.text.toString())
      .apply()
  }

  override fun onStop() {
    super.onStop()
    // A popup that lost the front is done; the next long-press opens a fresh one.
    if (!isChangingConfigurations) finish()
  }
}

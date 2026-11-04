package com.sudohnim.enqueue

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.util.Log
import android.widget.Toast

/**
 * Enqueue in the system share sheet: a link, some text, a picture or a PDF shared from
 * another app is saved without opening Enqueue, and the person stays where they were.
 *
 * It has no screen. It writes what was shared to QuickCaptureInbox and closes; it is
 * filed into the library at once (MainActivity.drainQuickCaptures) and sent to the
 * relay by a sync job (SyncWorker.syncSoon), as the launcher's quick capture is.
 */
class ShareActivity : Activity() {
  private companion object {
    const val MAX_BYTES = 25L * 1024 * 1024
    val URL = Regex("""https?://\S+""")
  }

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    val shared = intent
    Thread {
      val result = runCatching { save(shared) }
        .onFailure { Log.w("EnqueueShare", "could not keep a share", it) }
        .getOrDefault(R.string.share_failed)
      runOnUiThread {
        if (result == R.string.quick_capture_saved) {
          MainActivity.drainQuickCaptures(this)
          SyncWorker.syncSoon(applicationContext)
        }
        Toast.makeText(applicationContext, result, Toast.LENGTH_SHORT).show()
        finish()
      }
    }.start()
  }

  /** Keep what was shared; returns the message to show. */
  private fun save(intent: Intent): Int {
    val streams = streams(intent)
    if (streams.isNotEmpty()) {
      var kept = 0
      for (uri in streams) {
        val mime = contentResolver.getType(uri) ?: intent.type ?: "application/octet-stream"
        val bytes = read(uri) ?: return R.string.share_too_big
        if (QuickCaptureInbox.addFile(this, mime, name(uri, mime), bytes)) kept++
      }
      return if (kept == streams.size) R.string.quick_capture_saved else R.string.share_failed
    }
    val text = text(intent) ?: return R.string.share_nothing
    return if (QuickCaptureInbox.add(this, text)) R.string.quick_capture_saved else R.string.share_failed
  }

  /**
   * What to file for shared text. A page shared from a browser or a reading app is its
   * address, often with its title as the subject or around the address ("Read X on
   * Medium: https://..."): that becomes "title" over "address", which the app files as a
   * link with that title. Anything else is kept as written and filed as a note.
   */
  private fun text(intent: Intent): String? {
    val body = intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()?.trim().orEmpty()
    val subject = intent.getStringExtra(Intent.EXTRA_SUBJECT)?.trim().orEmpty()
    if (body.isEmpty()) return subject.ifEmpty { null }
    val urls = URL.findAll(body).map { it.value }.toList()
    if (urls.size != 1) return body
    val around = body.replace(urls[0], " ").trim().trimEnd(':', '-', '|', '–', '—').trim()
    if (around.length > 200 || around.contains('\n')) return body
    val title = subject.ifEmpty { around }
    return if (title.isEmpty()) urls[0] else "$title\n${urls[0]}"
  }

  private fun streams(intent: Intent): List<Uri> = when (intent.action) {
    Intent.ACTION_SEND -> listOfNotNull(stream(intent))
    Intent.ACTION_SEND_MULTIPLE -> streamList(intent)
    else -> emptyList()
  }

  @Suppress("DEPRECATION")
  private fun stream(intent: Intent): Uri? =
    if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
    else intent.getParcelableExtra(Intent.EXTRA_STREAM)

  @Suppress("DEPRECATION")
  private fun streamList(intent: Intent): List<Uri> =
    if (Build.VERSION.SDK_INT >= 33) intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java).orEmpty()
    else intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM).orEmpty()

  /** The file's bytes, or null when it is larger than the app keeps from a share. */
  private fun read(uri: Uri): ByteArray? {
    contentResolver.openInputStream(uri)?.use { input ->
      val out = java.io.ByteArrayOutputStream()
      val buf = ByteArray(64 * 1024)
      while (true) {
        val n = input.read(buf)
        if (n < 0) break
        out.write(buf, 0, n)
        if (out.size() > MAX_BYTES) return null
      }
      return out.toByteArray()
    }
    error("cannot open $uri")
  }

  private fun name(uri: Uri, mime: String): String {
    val shown = runCatching {
      contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
        if (it.moveToFirst()) it.getString(0) else null
      }
    }.getOrNull()
    return shown?.takeIf { it.isNotBlank() } ?: ("shared." + mime.substringAfter('/', "bin"))
  }
}

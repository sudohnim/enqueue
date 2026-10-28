package com.sudohnim.enqueue

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/**
 * Captures saved by the launcher popup (QuickCaptureActivity), waiting for the page.
 *
 * The popup runs without the WebView, so it cannot reach the library itself: it writes
 * each capture here, one file per capture, and the page files them into the library
 * through `mobile_capture` (mobile.html `drainQuickInbox`), acknowledging each one only
 * after it is saved. A capture is written to a temp file and renamed into place, so the
 * page never reads half of one, and it stays here until acknowledged, so a failed save
 * is retried the next time the app comes to the front. It is sealed with the Keystore
 * key (StoreKey); a plain .txt from an older build is still read once.
 */
object QuickCaptureInbox {
  private const val DIR = "quick_capture"
  private val ID = Regex("^[0-9]+-[0-9a-f-]{36}$")

  private fun dir(context: Context): File = File(context.filesDir, DIR).apply { mkdirs() }

  /** Store one capture. Returns false if it could not be written. */
  @Synchronized
  fun add(context: Context, text: String): Boolean {
    val id = "${System.currentTimeMillis()}-${UUID.randomUUID()}"
    val dir = dir(context)
    val tmp = File(dir, "$id.tmp")
    return runCatching {
      tmp.writeBytes(StoreKey.seal(text.toByteArray(Charsets.UTF_8)))
      tmp.renameTo(File(dir, "$id.enc"))
    }.getOrElse {
      tmp.delete()
      false
    }
  }

  /** Every waiting capture, oldest first, as a JSON array of `{id, text}`. */
  @Synchronized
  fun list(context: Context): String {
    val out = JSONArray()
    dir(context)
      .listFiles { f -> f.isFile && (f.name.endsWith(".enc") || f.name.endsWith(".txt")) }
      ?.sortedBy { it.name }
      ?.forEach { f ->
        runCatching {
          if (f.name.endsWith(".enc")) String(StoreKey.open(f.readBytes()), Charsets.UTF_8)
          else f.readText(Charsets.UTF_8)
        }.onSuccess { text ->
          out.put(JSONObject().put("id", f.nameWithoutExtension).put("text", text))
        }
      }
    return out.toString()
  }

  /** The page saved this capture: forget it. */
  @Synchronized
  fun ack(context: Context, id: String) {
    if (!ID.matches(id)) return
    File(dir(context), "$id.enc").delete()
    File(dir(context), "$id.txt").delete()
  }
}

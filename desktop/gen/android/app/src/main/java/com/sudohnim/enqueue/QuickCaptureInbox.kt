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
 * is retried the next time the app comes to the front.
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
      tmp.writeText(text, Charsets.UTF_8)
      tmp.renameTo(File(dir, "$id.txt"))
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
      .listFiles { f -> f.isFile && f.name.endsWith(".txt") }
      ?.sortedBy { it.name }
      ?.forEach { f ->
        runCatching { f.readText(Charsets.UTF_8) }.onSuccess { text ->
          out.put(JSONObject().put("id", f.name.removeSuffix(".txt")).put("text", text))
        }
      }
    return out.toString()
  }

  /** The page saved this capture: forget it. */
  @Synchronized
  fun ack(context: Context, id: String) {
    if (ID.matches(id)) File(dir(context), "$id.txt").delete()
  }
}

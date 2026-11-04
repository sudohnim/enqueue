package com.sudohnim.enqueue

import android.content.Context
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/**
 * Captures saved by the launcher popup (QuickCaptureActivity), waiting to be filed.
 *
 * The popup runs without the WebView, so it writes each capture here, one file per
 * capture, and starts a sync job (SyncWorker.syncSoon). [fileAll] files them into the
 * library through Rust (`fileOne` in lib.rs), from that job or when the page asks
 * (mobile.html `drainQuickInbox`), and forgets each one only after it is saved. One
 * filer runs at a time, so the job and the page never file a capture twice. A capture
 * is written to a temp file and renamed into place, so a filer never reads half of one,
 * and it stays here until saved, so a failed save is retried. It is sealed with the
 * Keystore key (StoreKey); a plain .txt from an older build is still read once.
 *
 * The share sheet (ShareActivity) puts captures here too: text the same way, and a
 * shared file (a picture, a PDF) as a sealed `.file` holding its type, name and bytes.
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

  /** Store one shared file. Returns false if it could not be written. */
  @Synchronized
  fun addFile(context: Context, mime: String, name: String, bytes: ByteArray): Boolean {
    val id = "${System.currentTimeMillis()}-${UUID.randomUUID()}"
    val dir = dir(context)
    val tmp = File(dir, "$id.tmp")
    val record = JSONObject()
      .put("mime", mime)
      .put("name", name)
      .put("data", Base64.encodeToString(bytes, Base64.NO_WRAP))
    return runCatching {
      tmp.writeBytes(StoreKey.seal(record.toString().toByteArray(Charsets.UTF_8)))
      tmp.renameTo(File(dir, "$id.file"))
    }.getOrElse {
      tmp.delete()
      false
    }
  }

  /**
   * Every waiting capture, oldest first, as a JSON array of `{id, text}`, or, for a
   * shared file, `{id, mime, name, data}` with the bytes in base64.
   */
  @Synchronized
  fun list(context: Context): String {
    val out = JSONArray()
    dir(context)
      .listFiles { f -> f.isFile && f.extension in setOf("enc", "txt", "file") }
      ?.sortedBy { it.name }
      ?.forEach { f ->
        runCatching {
          when (f.extension) {
            "file" -> JSONObject(String(StoreKey.open(f.readBytes()), Charsets.UTF_8))
            "enc" -> JSONObject().put("text", String(StoreKey.open(f.readBytes()), Charsets.UTF_8))
            else -> JSONObject().put("text", f.readText(Charsets.UTF_8))
          }
        }.onSuccess { item -> out.put(item.put("id", f.nameWithoutExtension)) }
      }
    return out.toString()
  }

  /** File every waiting capture into the library, oldest first; returns how many. */
  @Synchronized
  fun fileAll(context: Context): Int {
    StoreKey.appContext = context.applicationContext
    System.loadLibrary("enqueue_lib")
    val items = JSONArray(list(context))
    val dir = context.dataDir.absolutePath
    var filed = 0
    for (i in 0 until items.length()) {
      val item = items.getJSONObject(i)
      if (!fileOne(dir, item.toString())) break // keep it, and the rest, for the next try
      ack(context, item.getString("id"))
      filed++
    }
    return filed
  }

  @JvmStatic private external fun fileOne(dir: String, record: String): Boolean

  /** This capture is saved: forget it. */
  @Synchronized
  fun ack(context: Context, id: String) {
    if (!ID.matches(id)) return
    File(dir(context), "$id.enc").delete()
    File(dir(context), "$id.txt").delete()
    File(dir(context), "$id.file").delete()
  }
}

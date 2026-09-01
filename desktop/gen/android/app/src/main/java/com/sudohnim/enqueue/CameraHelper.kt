package com.sudohnim.enqueue

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import androidx.core.content.FileProvider
import java.io.File
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.CompletableFuture

class CameraHelper(
  private val activity: Activity,
) {
  private var photoFile: File? = null
  private var photoUri: Uri? = null
  private var resultFuture: CompletableFuture<String>? = null
  private var pickFuture: CompletableFuture<String>? = null
  private val REQUEST_IMAGE_CAPTURE = 42
  private val REQUEST_PICK_IMAGE = 43

  fun captureImage(): CompletableFuture<String> {
    val future = CompletableFuture<String>()
    this.resultFuture = future

    // Create the camera intent
    val intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)

    // Create a file for the camera output
    val photoFile = createImageFile()
    this.photoFile = photoFile

    // Get the URI for the file using FileProvider
    val authority = "${activity.packageName}.fileprovider"
    val photoUri =
      FileProvider.getUriForFile(
        activity,
        authority,
        photoFile!!,
      )
    this.photoUri = photoUri

    // Add the URI as EXTRA_OUTPUT
    intent.putExtra(MediaStore.EXTRA_OUTPUT, photoUri)

    // Grant URI permissions
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)

    // Start the camera activity
    activity.startActivityForResult(intent, REQUEST_IMAGE_CAPTURE)

    return future
  }

  // Pick an existing image from the gallery / photo picker. The picker returns a
  // content:// URI (not a filesystem path), which is why reading it from Rust with
  // std::fs::read failed - it must be read through the ContentResolver here.
  fun pickImage(): CompletableFuture<String> {
    val future = CompletableFuture<String>()
    this.pickFuture = future
    val intent = Intent(Intent.ACTION_GET_CONTENT)
    intent.type = "image/*"
    intent.addCategory(Intent.CATEGORY_OPENABLE)
    activity.startActivityForResult(intent, REQUEST_PICK_IMAGE)
    return future
  }

  private fun createImageFile(): File? {
    val timeStamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
    val imageFileName = "IMG_${timeStamp}_"
    val storageDir = activity.getExternalFilesDir(Environment.DIRECTORY_PICTURES)
    return File.createTempFile(
      imageFileName,
      ".jpg",
      storageDir,
    )
  }

  fun onActivityResult(
    requestCode: Int,
    resultCode: Int,
    data: Intent?,
  ): Boolean {
    if (requestCode == REQUEST_IMAGE_CAPTURE) {
      if (resultCode == Activity.RESULT_OK) {
        // Camera capture successful
        val photoFile = this.photoFile
        if (photoFile != null && photoFile.exists()) {
          // Read the file and convert to base64
          try {
            val bytes = photoFile.readBytes()
            // NO_WRAP: DEFAULT inserts newlines every 76 chars, and those raw \n land
            // inside the JSON string we build below, so the JS JSON.parse throws "bad
            // control character" and the captured photo silently never becomes an
            // artifact. A single-line base64 is valid inside the JSON string.
            val base64 = android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)
            val mime = "image/jpeg"
            resultFuture?.complete("{\"base64\":\"$base64\",\"mime\":\"$mime\"}")
          } catch (e: IOException) {
            resultFuture?.completeExceptionally(IOException("Failed to read captured image: $e"))
          }
        } else {
          resultFuture?.completeExceptionally(IOException("Camera capture failed - file not found"))
        }
      } else {
        resultFuture?.completeExceptionally(IOException("Camera capture cancelled"))
      }
      return true
    }
    if (requestCode == REQUEST_PICK_IMAGE) {
      if (resultCode == Activity.RESULT_OK && data?.data != null) {
        val uri = data.data!!
        try {
          val bytes =
            activity.contentResolver.openInputStream(uri)?.use { it.readBytes() }
              ?: throw IOException("could not open picked image")
          // NO_WRAP: newlines from DEFAULT break the JSON string on the JS side.
          val base64 = android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)
          val mime = activity.contentResolver.getType(uri) ?: "image/jpeg"
          pickFuture?.complete("{\"base64\":\"$base64\",\"mime\":\"$mime\"}")
        } catch (e: Exception) {
          pickFuture?.completeExceptionally(IOException("Failed to read picked image: $e"))
        }
      } else {
        pickFuture?.completeExceptionally(IOException("Image pick cancelled"))
      }
      return true
    }
    return false
  }

  companion object {
    private var instance: CameraHelper? = null
    private var storedActivity: Activity? = null

    fun getInstance(activity: Activity): CameraHelper {
      storedActivity = activity
      if (instance == null) {
        instance = CameraHelper(activity)
      }
      return instance!!
    }

    fun clearInstance() {
      instance = null
      storedActivity = null
    }

    // Capture image from any thread by posting to UI thread
    fun captureImageOnUiThread(): CompletableFuture<String> {
      val future = CompletableFuture<String>()
      val activity = storedActivity
      if (activity == null) {
        future.completeExceptionally(IllegalStateException("Activity not initialized. Call getInstance() first."))
        return future
      }
      Handler(Looper.getMainLooper()).post {
        try {
          val helper = getInstance(activity)
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
  }
}
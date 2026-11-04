package com.sudohnim.enqueue

import android.content.Context
import android.os.Build
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Sync with the app closed: every half hour or so, when the phone has a network,
 * Android runs this job, which pushes what is queued and pulls (background_sync in
 * lib.rs). Tauri is not running here, so the job hands Rust the data folder itself.
 * Android decides the exact time; a job while the app is open waits for its sync.
 * A share or a quick capture asks for one at once (syncSoon), which first files the
 * inbox, so it reaches the other devices without the app being opened.
 */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
  override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
    if (QuickCaptureInbox.fileAll(applicationContext) > 0) MainActivity.quickCapturesFiled()
    syncNow(applicationContext.dataDir.absolutePath)
    Result.success()
  }

  private external fun syncNow(dir: String): Boolean

  companion object {
    fun schedule(context: Context) {
      val request = PeriodicWorkRequestBuilder<SyncWorker>(30, TimeUnit.MINUTES)
        .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
        .build()
      WorkManager.getInstance(context)
        .enqueueUniquePeriodicWork("enqueue-sync", ExistingPeriodicWorkPolicy.KEEP, request)
    }

    fun syncSoon(context: Context) {
      val request = OneTimeWorkRequestBuilder<SyncWorker>()
        .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
      // Below Android 12 an expedited job needs a foreground notification; a plain one
      // still runs as soon as the network allows.
      if (Build.VERSION.SDK_INT >= 31) {
        request.setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
      }
      WorkManager.getInstance(context)
        .enqueueUniqueWork("enqueue-sync-now", ExistingWorkPolicy.APPEND_OR_REPLACE, request.build())
    }
  }
}

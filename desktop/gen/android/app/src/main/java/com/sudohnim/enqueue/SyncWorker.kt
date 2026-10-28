package com.sudohnim.enqueue

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
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
 */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
  override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
    StoreKey.appContext = applicationContext
    System.loadLibrary("enqueue_lib")
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
  }
}

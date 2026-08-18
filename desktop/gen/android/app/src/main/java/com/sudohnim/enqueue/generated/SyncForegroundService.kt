/*
 * SyncForegroundService - keeps the sync alive during screen lock/background
 * Started/stopped from Rust via JNI when sync begins/ends.
 */

package com.sudohnim.enqueue

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat

class SyncForegroundService : Service() {
  companion object {
    const val CHANNEL_ID = "enqueue_sync_channel"
    const val NOTIFICATION_ID = 1001
    const val ACTION_START = "com.sudohnim.enqueue.SYNC_START"
    const val ACTION_STOP = "com.sudohnim.enqueue.SYNC_STOP"

    fun startSync(context: Context) {
      val intent =
        Intent(context, SyncForegroundService::class.java).apply {
          action = ACTION_START
        }
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        context.startForegroundService(intent)
      } else {
        context.startService(intent)
      }
    }

    fun stopSync(context: Context) {
      val intent =
        Intent(context, SyncForegroundService::class.java).apply {
          action = ACTION_STOP
        }
      context.startService(intent)
    }
  }

  private var notificationManager: NotificationManager? = null

  @Suppress("UNUSED_PARAMETER")
  override fun onCreate() {
    super.onCreate()
    notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager?
    createNotificationChannel()
  }

  private fun createNotificationChannel() {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      val channel =
        NotificationChannel(
          CHANNEL_ID,
          "Enqueue Sync",
          NotificationManager.IMPORTANCE_LOW,
        ).apply {
          description = "Shows active library sync progress"
          setShowBadge(false)
          // No sound, no vibration for ongoing sync
          enableVibration(false)
          setSound(null, null)
        }
      notificationManager?.createNotificationChannel(channel)
    }
  }

  private fun buildNotification(): Notification {
    val intent =
      Intent(this, MainActivity::class.java).apply {
        flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
      }
    val pendingIntent =
      PendingIntent.getActivity(
        this,
        0,
        intent,
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
      )

    return NotificationCompat
      .Builder(this, CHANNEL_ID)
      .setContentTitle("Enqueue: Syncing library…")
      .setContentText("Background sync in progress")
      .setSmallIcon(R.drawable.ic_notification)
      .setContentIntent(pendingIntent)
      .setOngoing(true)
      .setOnlyAlertOnce(true)
      .setCategory(NotificationCompat.CATEGORY_PROGRESS)
      .setPriority(NotificationCompat.PRIORITY_LOW)
      .setProgress(100, 0, true) // indeterminate progress
      .build()
  }

  override fun onStartCommand(
    intent: Intent?,
    flags: Int,
    startId: Int,
  ): Int {
    val action = intent?.action
    when (action) {
      ACTION_START -> {
        val notification = buildNotification()
        startForeground(NOTIFICATION_ID, notification)
      }

      ACTION_STOP -> {
        stopForeground(true)
        stopSelf()
      }
    }
    return START_NOT_STICKY
  }

  override fun onBind(intent: Intent?): IBinder? = null
}

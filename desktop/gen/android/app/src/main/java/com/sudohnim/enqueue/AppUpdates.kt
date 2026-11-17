package com.sudohnim.enqueue

import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.google.android.play.core.appupdate.AppUpdateInfo
import com.google.android.play.core.appupdate.AppUpdateManagerFactory
import com.google.android.play.core.appupdate.AppUpdateOptions
import com.google.android.play.core.install.model.AppUpdateType
import com.google.android.play.core.install.model.UpdateAvailability
import org.json.JSONObject

/**
 * A newer Enqueue on Google Play, through Play's in-app updates. The page asks
 * (`check`) and shows its own prompt; Update opens Play's update screen (`start`).
 * Only a copy installed from Play gets an answer; any other build hears "unavailable".
 * Every call answers later through `reply(json)`, the bridge's window.__enqUpdateReply.
 */
class AppUpdates(private val activity: AppCompatActivity) {
  // Lazy: the activity has no context yet while it is being built.
  private val manager by lazy { AppUpdateManagerFactory.create(activity) }
  private var pending: ((JSONObject) -> Unit)? = null

  // Registered while the activity is built, as the result API requires.
  private val launcher: ActivityResultLauncher<IntentSenderRequest> =
    activity.registerForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) {
      pending?.invoke(JSONObject().put("ok", it.resultCode == AppCompatActivity.RESULT_OK))
      pending = null
    }

  fun check(reply: (JSONObject) -> Unit) {
    manager.appUpdateInfo
      .addOnSuccessListener { info ->
        val out = JSONObject().put("ok", true).put("available", ready(info))
        out.put("version_code", info.availableVersionCode())
        // An update Play started earlier and the person left half done.
        out.put("resume", info.updateAvailability() == UpdateAvailability.DEVELOPER_TRIGGERED_UPDATE_IN_PROGRESS)
        reply(out)
      }
      .addOnFailureListener { reply(JSONObject().put("ok", false).put("reason", "unavailable")) }
  }

  fun start(reply: (JSONObject) -> Unit) {
    manager.appUpdateInfo
      .addOnSuccessListener { info ->
        val resume = info.updateAvailability() == UpdateAvailability.DEVELOPER_TRIGGERED_UPDATE_IN_PROGRESS
        if (!ready(info) && !resume) return@addOnSuccessListener reply(JSONObject().put("ok", false).put("reason", "none"))
        pending = reply
        val options = AppUpdateOptions.newBuilder(AppUpdateType.IMMEDIATE).build()
        if (!manager.startUpdateFlowForResult(info, launcher, options)) {
          pending = null
          reply(JSONObject().put("ok", false).put("reason", "refused"))
        }
      }
      .addOnFailureListener { reply(JSONObject().put("ok", false).put("reason", "unavailable")) }
  }

  private fun ready(info: AppUpdateInfo) =
    info.updateAvailability() == UpdateAvailability.UPDATE_AVAILABLE &&
      info.isUpdateTypeAllowed(AppUpdateType.IMMEDIATE)
}

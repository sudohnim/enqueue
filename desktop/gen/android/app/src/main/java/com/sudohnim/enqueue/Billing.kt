package com.sudohnim.enqueue

import android.app.Activity
import com.revenuecat.purchases.CustomerInfo
import com.revenuecat.purchases.Package
import com.revenuecat.purchases.PurchaseParams
import com.revenuecat.purchases.Purchases
import com.revenuecat.purchases.PurchasesConfiguration
import com.revenuecat.purchases.PurchasesError
import com.revenuecat.purchases.getCustomerInfoWith
import com.revenuecat.purchases.getOfferingsWith
import com.revenuecat.purchases.logInWith
import com.revenuecat.purchases.purchaseWith
import com.revenuecat.purchases.restorePurchasesWith
import org.json.JSONArray
import org.json.JSONObject

/**
 * Enqueue Pro through Google Play, by RevenueCat (Dequeue's pattern).
 *
 * The RevenueCat user IS the Enqueue sync account (its id, from the relay's
 * /account/plan), so a purchase reaches the relay through RevenueCat's webhook and
 * every device of the account sees Pro, the Mac included, which never sells anything.
 * Nothing here decides what Pro allows: the relay does. A phone on a relay of its own
 * has no account and never configures this.
 *
 * Every call answers later through `reply(json)`, which the bridge hands to the page
 * as window.__enqBillingReply(id, {...}).
 */
class Billing(private val activity: Activity) {
  // RevenueCat's public Android key for the Enqueue app. Public by design: it can only
  // read offerings and start purchases; the secret keys never ship.
  private val apiKey = "goog_BcdeKsNNPRNEAOxLFvcGFBVAqsM"

  val available: Boolean get() = apiKey.startsWith("goog_")

  /** Configure once for this account, or switch to it when another was configured. */
  fun start(accountId: String, reply: (JSONObject) -> Unit) {
    if (!available) return reply(fail("unavailable"))
    if (!Purchases.isConfigured) {
      Purchases.configure(
        PurchasesConfiguration.Builder(activity.applicationContext, apiKey)
          .appUserID(accountId)
          .build(),
      )
      return customer(reply)
    }
    if (Purchases.sharedInstance.appUserID == accountId) return customer(reply)
    Purchases.sharedInstance.logInWith(
      accountId,
      onError = { reply(error(it)) },
      onSuccess = { info, _ -> reply(state(info)) },
    )
  }

  fun customer(reply: (JSONObject) -> Unit) {
    if (!Purchases.isConfigured) return reply(fail("not_started"))
    Purchases.sharedInstance.getCustomerInfoWith(
      onError = { reply(error(it)) },
      onSuccess = { reply(state(it)) },
    )
  }

  /** The current offering's packages: what the paywall lists, priced by Play. */
  fun offerings(reply: (JSONObject) -> Unit) {
    if (!Purchases.isConfigured) return reply(fail("not_started"))
    Purchases.sharedInstance.getOfferingsWith(
      onError = { reply(error(it)) },
      onSuccess = { offerings ->
        val list = JSONArray()
        offerings.current?.availablePackages?.forEach { list.put(describe(it)) }
        reply(JSONObject().put("ok", true).put("packages", list))
      },
    )
  }

  fun purchase(packageId: String, reply: (JSONObject) -> Unit) {
    if (!Purchases.isConfigured) return reply(fail("not_started"))
    Purchases.sharedInstance.getOfferingsWith(
      onError = { reply(error(it)) },
      onSuccess = { offerings ->
        val pkg = offerings.current?.availablePackages?.firstOrNull { it.identifier == packageId }
          ?: return@getOfferingsWith reply(fail("no_package"))
        Purchases.sharedInstance.purchaseWith(
          PurchaseParams.Builder(activity, pkg).build(),
          onError = { err, cancelled -> reply(if (cancelled) fail("cancelled") else error(err)) },
          onSuccess = { _, info -> reply(state(info)) },
        )
      },
    )
  }

  fun restore(reply: (JSONObject) -> Unit) {
    if (!Purchases.isConfigured) return reply(fail("not_started"))
    Purchases.sharedInstance.restorePurchasesWith(
      onError = { reply(error(it)) },
      onSuccess = { reply(state(it)) },
    )
  }

  private fun describe(pkg: Package): JSONObject {
    val product = pkg.product
    return JSONObject()
      .put("id", pkg.identifier)
      .put("type", pkg.packageType.name)
      .put("title", product.title)
      .put("price", product.price.formatted)
      .put("period", product.period?.iso8601 ?: JSONObject.NULL)
  }

  private fun state(info: CustomerInfo): JSONObject {
    val pro = info.entitlements[PRO]
    return JSONObject()
      .put("ok", true)
      .put("pro", pro?.isActive == true)
      .put("expires", pro?.expirationDate?.time ?: JSONObject.NULL)
      .put("willRenew", pro?.willRenew == true)
      .put("manage", info.managementURL?.toString() ?: JSONObject.NULL)
  }

  private fun error(err: PurchasesError): JSONObject =
    fail(err.code.name.lowercase()).put("message", err.message)

  private fun fail(reason: String): JSONObject = JSONObject().put("ok", false).put("reason", reason)

  companion object {
    const val PRO = "pro"
  }
}

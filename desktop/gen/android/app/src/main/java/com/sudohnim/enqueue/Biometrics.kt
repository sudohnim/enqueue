package com.sudohnim.enqueue

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyPermanentlyInvalidatedException
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Fingerprint checks for the phone (BIO.1). Two separate jobs, deliberately not merged:
 *
 * 1. The APP LOCK: "is this the phone's owner?" A plain prompt that accepts a
 *    fingerprint or the phone's own screen lock, so a wet finger or a sensor lockout can
 *    never shut the owner out of their library. It gates the screen; it holds no key.
 *
 * 2. The VAULT SECRET: a random 32 bytes the Android Keystore releases only after a
 *    strong fingerprint. The vault key itself never comes here - the Rust side keeps it
 *    sealed under this secret (sync::vault_bio_seal) - so what crosses the page is a
 *    value that is useless without the app's own sealed record.
 *
 * The Keystore key needs a fingerprint for EVERY use and dies when a new fingerprint is
 * enrolled, so adding a finger to the phone cannot open the vault: the 6-digit code is
 * needed again, and fingerprint unlock is turned on afresh.
 *
 * Every method that shows a prompt must be called on the main thread.
 */
class Biometrics(private val activity: FragmentActivity) {
  private val prefs = activity.getSharedPreferences("enqueue_lock", Context.MODE_PRIVATE)

  // ---- what the phone can do ----------------------------------------------------

  /** "ready", "none" (nothing enrolled) or "unavailable" (no usable sensor). */
  fun fingerprintState(): String = state(Authenticators.BIOMETRIC_STRONG)

  /** The app lock accepts a fingerprint OR the phone's screen lock. */
  fun deviceLockState(): String = state(APP_LOCK_AUTH)

  private fun state(authenticators: Int): String =
    when (BiometricManager.from(activity).canAuthenticate(authenticators)) {
      BiometricManager.BIOMETRIC_SUCCESS -> "ready"
      BiometricManager.BIOMETRIC_ERROR_NONE_ENROLLED -> "none"
      else -> "unavailable"
    }

  // ---- the app lock ---------------------------------------------------------------

  var appLock: Boolean
    get() = prefs.getBoolean(KEY_APP_LOCK, false)
    set(on) = prefs.edit().putBoolean(KEY_APP_LOCK, on).apply()

  /** Ask "is this the owner?" and answer true only on a successful check. */
  fun confirm(title: String, subtitle: String, onDone: (Boolean) -> Unit) {
    val info = BiometricPrompt.PromptInfo.Builder()
      .setTitle(title)
      .setSubtitle(subtitle)
      .setAllowedAuthenticators(APP_LOCK_AUTH) // no cancel button: the system adds its own
      .build()
    prompt(null, info) { result, _ -> onDone(result != null) }
  }

  // ---- the vault secret -----------------------------------------------------------

  fun hasVaultSecret(): Boolean =
    prefs.contains(KEY_SECRET_CT) && prefs.contains(KEY_SECRET_IV) && keystoreKey() != null

  /**
   * Make a fresh secret, lock it behind a fingerprint, and hand it back once so the Rust
   * side can seal the vault key under it. Answers (hex, "ok") or (null, reason).
   */
  fun createVaultSecret(
    title: String,
    subtitle: String,
    cancel: String,
    onDone: (String?, String) -> Unit,
  ) {
    val cipher = try {
      clearVaultSecret()
      Cipher.getInstance(TRANSFORMATION).apply { init(Cipher.ENCRYPT_MODE, newKeystoreKey()) }
    } catch (e: Exception) {
      return onDone(null, "error")
    }
    prompt(cipher, strongInfo(title, subtitle, cancel)) { result, reason ->
      val unlocked = result?.cryptoObject?.cipher ?: return@prompt onDone(null, reason)
      try {
        val secret = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val sealed = unlocked.doFinal(secret)
        prefs.edit()
          .putString(KEY_SECRET_IV, Base64.encodeToString(unlocked.iv, Base64.NO_WRAP))
          .putString(KEY_SECRET_CT, Base64.encodeToString(sealed, Base64.NO_WRAP))
          .apply()
        onDone(secret.toHex(), "ok")
      } catch (e: Exception) {
        clearVaultSecret()
        onDone(null, "error")
      }
    }
  }

  /**
   * Release the secret after a fingerprint. "invalidated" means the phone's fingerprints
   * changed (or the key is gone): the secret is destroyed and the code is needed.
   */
  fun readVaultSecret(
    title: String,
    subtitle: String,
    cancel: String,
    onDone: (String?, String) -> Unit,
  ) {
    val iv = prefs.getString(KEY_SECRET_IV, null)?.let { Base64.decode(it, Base64.NO_WRAP) }
    val sealed = prefs.getString(KEY_SECRET_CT, null)?.let { Base64.decode(it, Base64.NO_WRAP) }
    val key = keystoreKey()
    if (iv == null || sealed == null || key == null) {
      clearVaultSecret()
      return onDone(null, "invalidated")
    }
    val cipher = try {
      Cipher.getInstance(TRANSFORMATION).apply {
        init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(GCM_TAG_BITS, iv))
      }
    } catch (e: KeyPermanentlyInvalidatedException) {
      clearVaultSecret()
      return onDone(null, "invalidated")
    } catch (e: Exception) {
      return onDone(null, "error")
    }
    prompt(cipher, strongInfo(title, subtitle, cancel)) { result, reason ->
      val unlocked = result?.cryptoObject?.cipher ?: return@prompt onDone(null, reason)
      try {
        onDone(unlocked.doFinal(sealed).toHex(), "ok")
      } catch (e: Exception) {
        onDone(null, "error")
      }
    }
  }

  fun clearVaultSecret() {
    prefs.edit().remove(KEY_SECRET_IV).remove(KEY_SECRET_CT).apply()
    runCatching { keystore().deleteEntry(KEY_ALIAS) }
  }

  // ---- plumbing -------------------------------------------------------------------

  private fun strongInfo(title: String, subtitle: String, cancel: String) =
    BiometricPrompt.PromptInfo.Builder()
      .setTitle(title)
      .setSubtitle(subtitle)
      .setNegativeButtonText(cancel)
      .setAllowedAuthenticators(Authenticators.BIOMETRIC_STRONG)
      .build()

  /**
   * Show one prompt. Answers (result, "ok") on success, or (null, reason) where reason
   * is "cancelled", "lockout" (too many tries) or "error". A finger that simply did not
   * match keeps the prompt open and is not an answer.
   */
  private fun prompt(
    cipher: Cipher?,
    info: BiometricPrompt.PromptInfo,
    onDone: (BiometricPrompt.AuthenticationResult?, String) -> Unit,
  ) {
    var answered = false
    val once = { result: BiometricPrompt.AuthenticationResult?, reason: String ->
      if (!answered) {
        answered = true
        onDone(result, reason)
      }
    }
    val callback = object : BiometricPrompt.AuthenticationCallback() {
      override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) =
        once(result, "ok")

      override fun onAuthenticationError(code: Int, message: CharSequence) =
        once(
          null,
          when (code) {
            BiometricPrompt.ERROR_USER_CANCELED,
            BiometricPrompt.ERROR_NEGATIVE_BUTTON,
            BiometricPrompt.ERROR_CANCELED -> "cancelled"
            BiometricPrompt.ERROR_LOCKOUT,
            BiometricPrompt.ERROR_LOCKOUT_PERMANENT -> "lockout"
            else -> "error"
          },
        )
    }
    try {
      val biometricPrompt =
        BiometricPrompt(activity, ContextCompat.getMainExecutor(activity), callback)
      if (cipher != null) {
        biometricPrompt.authenticate(info, BiometricPrompt.CryptoObject(cipher))
      } else {
        biometricPrompt.authenticate(info)
      }
    } catch (e: Exception) {
      once(null, "error")
    }
  }

  private fun keystore(): KeyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }

  private fun keystoreKey(): SecretKey? =
    runCatching { keystore().getKey(KEY_ALIAS, null) as? SecretKey }.getOrNull()

  private fun newKeystoreKey(): SecretKey {
    val spec = KeyGenParameterSpec.Builder(
      KEY_ALIAS,
      KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
    )
      .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
      .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
      .setKeySize(256)
      .setUserAuthenticationRequired(true)
      // A fingerprint added later must not inherit the vault.
      .setInvalidatedByBiometricEnrollment(true)
      .apply {
        // A fingerprint for every single use, never a time window.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
          setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)
        }
      }
      .build()
    return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
      .apply { init(spec) }
      .generateKey()
  }

  private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

  companion object {
    private const val KEYSTORE = "AndroidKeyStore"
    private const val KEY_ALIAS = "enqueue_vault_fingerprint"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val GCM_TAG_BITS = 128
    private const val KEY_APP_LOCK = "app_lock"
    private const val KEY_SECRET_IV = "vault_secret_iv"
    private const val KEY_SECRET_CT = "vault_secret_ct"

    // BIOMETRIC_WEAK | DEVICE_CREDENTIAL is the one credential-fallback combination
    // every supported Android version accepts (STRONG | CREDENTIAL is refused on 28-29).
    private const val APP_LOCK_AUTH =
      Authenticators.BIOMETRIC_WEAK or Authenticators.DEVICE_CREDENTIAL
  }
}

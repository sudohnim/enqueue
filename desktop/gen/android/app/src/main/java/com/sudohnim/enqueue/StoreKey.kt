package com.sudohnim.enqueue

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.File
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * The key this phone keeps its library under (`store_key` in lib.rs): the encrypted
 * database (SQLCipher) and the sealed secrets (the sync key, the vault records) are
 * locked with keys derived from it.
 *
 * It is 32 random bytes, made on first use, and kept in `filesDir/store_key` encrypted
 * by an AES-GCM key in the Android Keystore, which never leaves the phone's secure
 * hardware. That Keystore key needs no fingerprint (the sync service reads the library
 * while the phone is locked); the fingerprint locks are separate (Biometrics.kt).
 * It never leaves this phone and is not synced: lose it and the phone links again,
 * since the library on it is a copy of the one on the Mac.
 */
object StoreKey {
  private const val ALIAS = "enqueue-store"
  private const val FILE = "store_key"

  @Volatile private var cached: ByteArray? = null

  /** The application context, set by MainActivity.onCreate before the page (and so any
   *  Rust command) can run. Rust calls in with no context of its own: Tauri never
   *  initializes ndk-context, and asking it for one aborts the app. */
  @Volatile var appContext: Context? = null

  @Synchronized
  fun get(): ByteArray {
    cached?.let { return it }
    val context = appContext ?: throw IllegalStateException("the store key was asked for too early")
    val file = File(context.filesDir, FILE)
    val key =
      if (file.exists()) {
        open(file.readBytes())
      } else {
        val fresh = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val tmp = File(context.filesDir, "$FILE.partial")
        tmp.writeBytes(seal(fresh))
        if (!tmp.renameTo(file)) throw IllegalStateException("could not keep the store key")
        fresh
      }
    cached = key
    return key
  }

  private fun keystoreKey(): SecretKey {
    val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
    val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
    gen.init(
      KeyGenParameterSpec.Builder(
          ALIAS,
          KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
        .setKeySize(256)
        .build()
    )
    return gen.generateKey()
  }

  internal fun seal(plain: ByteArray): ByteArray {
    val cipher = Cipher.getInstance("AES/GCM/NoPadding")
    cipher.init(Cipher.ENCRYPT_MODE, keystoreKey())
    return cipher.iv + cipher.doFinal(plain)
  }

  internal fun open(sealed: ByteArray): ByteArray {
    val cipher = Cipher.getInstance("AES/GCM/NoPadding")
    cipher.init(
      Cipher.DECRYPT_MODE,
      keystoreKey(),
      GCMParameterSpec(128, sealed.copyOfRange(0, 12)),
    )
    return cipher.doFinal(sealed.copyOfRange(12, sealed.size))
  }
}

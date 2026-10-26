package com.sudohnim.enqueue

import android.app.Activity
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialException
import androidx.credentials.exceptions.NoCredentialException
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * Sign in to Enqueue sync with Google on the phone (Credential Manager), so a phone can
 * join the account's library without the Mac's code. Google hands back an id token
 * whose audience is Enqueue's Web client; the page passes it to `mobile_sign_in`, which
 * trades it at the relay (POST /auth/google) for a device pass of this phone's own.
 * The token never leaves for anywhere but Enqueue sync.
 *
 * Google only issues it to this app once its Android client (package and signing
 * certificate) is registered in the same Google Cloud project as the Web client.
 */
class SignIn(private val activity: Activity) {
  private val webClientId = "760253515706-65gi4hr5igu9lqae3gs0i9julkusfask.apps.googleusercontent.com"

  fun google(reply: (JSONObject) -> Unit) {
    val request = GetCredentialRequest.Builder()
      .addCredentialOption(GetSignInWithGoogleOption.Builder(webClientId).build())
      .build()
    CoroutineScope(Dispatchers.Main).launch {
      try {
        val result = CredentialManager.create(activity).getCredential(activity, request)
        val credential = result.credential
        if (credential is CustomCredential &&
          credential.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL
        ) {
          val google = GoogleIdTokenCredential.createFrom(credential.data)
          reply(JSONObject().put("ok", true).put("idToken", google.idToken))
        } else {
          reply(fail("unexpected"))
        }
      } catch (e: GetCredentialCancellationException) {
        reply(fail("cancelled"))
      } catch (e: NoCredentialException) {
        reply(fail("no_account"))
      } catch (e: GetCredentialException) {
        reply(fail("failed").put("message", e.message ?: e.type))
      }
    }
  }

  private fun fail(reason: String) = JSONObject().put("ok", false).put("reason", reason)
}

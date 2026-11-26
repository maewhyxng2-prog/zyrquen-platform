package com.zyrquen.realitycheck

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import java.util.concurrent.TimeUnit

data class LoginRequest(val email: String, val password: String)
data class LoginResponse(val access_token: String, val token_type: String)
data class LogoutResponse(val authenticated: Boolean, val revoked: Boolean)
data class HealthResponse(val status: String?, val service: String?)
data class UserResponse(val id: String, val email: String, val is_active: Boolean)
data class WorkflowListResponse(val items: List<Map<String, Any?>> = emptyList())
data class InferenceRequest(
    val prompt: String,
    val request_id: String,
    val max_tokens: Int = 256,
    val temperature: Double = 0.4,
    val top_k: Int = 0,
    val top_p: Double = 1.0
)
data class InferenceResponse(
    val status: String?,
    val provider: String?,
    val model_version: String?,
    val result: String?
)

interface RealityCheckApi {
    @POST("auth/login")
    suspend fun login(@Body body: LoginRequest): LoginResponse

    @GET("auth/me")
    suspend fun me(@Header("Authorization") authorization: String): UserResponse

    @POST("auth/logout")
    suspend fun logout(@Header("Authorization") authorization: String): LogoutResponse

    @GET("health")
    suspend fun health(): HealthResponse

    @GET("v1/workflows/runs")
    suspend fun workflows(@Header("Authorization") authorization: String): WorkflowListResponse

    @POST("v1/native-ai/infer")
    suspend fun infer(
        @Header("Authorization") authorization: String,
        @Body body: InferenceRequest
    ): InferenceResponse
}

class TokenStore(context: Context) {
    private val preferences = EncryptedSharedPreferences.create(
        context,
        "realitycheck_secure",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )

    fun read(): String? = preferences.getString("access_token", null)
    fun write(token: String) { preferences.edit().putString("access_token", token).apply() }
    fun clear() { preferences.edit().remove("access_token").apply() }
}

object ApiFactory {
    fun create(baseUrl: String, token: () -> String?): RealityCheckApi {
        require(baseUrl.startsWith("https://")) { "API URL must use HTTPS" }
        require(baseUrl.endsWith("/")) { "API URL must end with /" }
        val auth = Interceptor { chain ->
            val request = chain.request().newBuilder().apply {
                token()?.takeIf { it.isNotBlank() }?.let { header("Authorization", "Bearer $it") }
            }.build()
            chain.proceed(request)
        }
        val client = OkHttpClient.Builder()
            .addInterceptor(auth)
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(130, TimeUnit.SECONDS)
            .callTimeout(140, TimeUnit.SECONDS)
            .build()
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(RealityCheckApi::class.java)
    }
}

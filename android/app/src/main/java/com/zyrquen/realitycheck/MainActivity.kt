package com.zyrquen.realitycheck

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import retrofit2.HttpException
import java.util.UUID

private val Navy = Color(0xFF0A1425)
private val Panel = Color(0xFF14243A)
private val Blue = Color(0xFF2494FF)
private val Green = Color(0xFF36D77A)
private val Muted = Color(0xFF9FB1C9)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val tokens = TokenStore(this)
        setContent {
            MaterialTheme(
                colorScheme = darkColorScheme(
                    background = Navy,
                    surface = Panel,
                    primary = Blue,
                    secondary = Green,
                    onBackground = Color.White,
                    onSurface = Color.White
                )
            ) {
                RealityCheckApp(tokens)
            }
        }
    }
}

@Composable
private fun RealityCheckApp(tokens: TokenStore) {
    val scope = rememberCoroutineScope()
    var baseUrl by remember { mutableStateOf(tokens.readBaseUrl()) }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var token by remember { mutableStateOf(tokens.read().orEmpty()) }
    var statusText by remember { mutableStateOf("ยังไม่ได้เชื่อมต่อ Backend") }
    var health by remember { mutableStateOf("UNKNOWN") }
    var workflows by remember { mutableStateOf<List<Map<String, Any?>>>(emptyList()) }
    var prompt by remember { mutableStateOf("") }
    var answer by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var tab by remember { mutableStateOf("home") }
    var api by remember { mutableStateOf<RealityCheckApi?>(null) }

    LaunchedEffect(baseUrl) {
        if (baseUrl.startsWith("https://") && baseUrl.endsWith("/")) {
            api = runCatching { ApiFactory.create(baseUrl) { token.ifBlank { null } } }.getOrNull()
        }
    }

    fun connect() {
        try {
            api = ApiFactory.create(baseUrl.trim()) { token.ifBlank { null } }
            statusText = "กำลังเชื่อมต่อ..."
            scope.launch {
                busy = true
                try {
                    health = api!!.livez().status ?: "UNKNOWN"
                    statusText = "Backend ตอบสนองแล้ว"
                    if (token.isNotBlank()) {
                        api!!.me("Bearer $token")
                        workflows = api!!.workflows("Bearer $token").items
                    }
                } catch (e: Exception) {
                    health = "UNAVAILABLE"
                    statusText = safeMessage(e)
                } finally { busy = false }
            }
        } catch (e: Exception) {
            statusText = e.message ?: "กำหนดค่า API ไม่ถูกต้อง"
        }
    }

    Surface(modifier = Modifier.fillMaxSize(), color = Navy) {
        if (token.isBlank()) {
            LoginScreen(
                baseUrl, { baseUrl = it }, email, { email = it },
                password, { password = it }, statusText, busy,
                onLogin = {
                    scope.launch {
                        busy = true
                        try {
                            val client = ApiFactory.create(baseUrl.trim()) { null }
                            val result = client.login(LoginRequest(email.trim(), password))
                            tokens.write(result.access_token, baseUrl.trim())
                            token = result.access_token
                            password = ""
                            api = ApiFactory.create(baseUrl.trim()) { token }
                            health = api!!.health().status ?: "UNKNOWN"
                            api!!.me("Bearer $token")
                            workflows = api!!.workflows("Bearer $token").items
                            statusText = "เข้าสู่ระบบสำเร็จ"
                        } catch (e: Exception) {
                            statusText = safeMessage(e)
                        } finally { busy = false }
                    }
                }
            )
        } else {
            Column(Modifier.fillMaxSize().padding(18.dp)) {
                Text("RealityCheck", style = MaterialTheme.typography.headlineMedium)
                Text("RestoreProof · ZYRQUEN Native Operations", color = Muted)
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("home" to "ภาพรวม", "assistant" to "AI Assistant", "runs" to "งาน").forEach { (key, label) ->
                        FilterChip(selected = tab == key, onClick = { tab = key }, label = { Text(label) })
                    }
                }
                Spacer(Modifier.height(12.dp))
                when (tab) {
                    "assistant" -> AssistantScreen(
                        prompt, { prompt = it }, answer, busy,
                        onSend = {
                            val client = api
                            if (client == null || prompt.isBlank()) return@AssistantScreen
                            scope.launch {
                                busy = true
                                answer = ""
                                try {
                                    val response = client.infer(
                                        "Bearer $token",
                                        InferenceRequest(prompt.trim(), UUID.randomUUID().toString())
                                    )
                                    answer = response.result ?: "Native AI ไม่ได้ส่งผลลัพธ์"
                                } catch (e: Exception) {
                                    answer = safeMessage(e)
                                } finally { busy = false }
                            }
                        }
                    )
                    "runs" -> RunsScreen(workflows)
                    else -> DashboardScreen(
                        health, statusText, workflows.size, busy,
                        onRefresh = { connect() },
                        onLogout = {
                            scope.launch {
                                try { api?.logout("Bearer $token") } catch (_: Exception) { }
                                tokens.clear()
                                token = ""
                                workflows = emptyList()
                                answer = ""
                                statusText = "ออกจากระบบในอุปกรณ์แล้ว"
                            }
                        }
                    )
                }
            }
        }
    }
}

@Composable
private fun LoginScreen(
    baseUrl: String, onBaseUrl: (String) -> Unit,
    email: String, onEmail: (String) -> Unit,
    password: String, onPassword: (String) -> Unit,
    status: String, busy: Boolean, onLogin: () -> Unit
) {
    Column(Modifier.fillMaxSize().background(Navy).padding(24.dp), verticalArrangement = Arrangement.Center) {
        Text("RealityCheck", style = MaterialTheme.typography.headlineLarge)
        Text("RestoreProof · Android Control App", color = Muted)
        Spacer(Modifier.height(28.dp))
        OutlinedTextField(baseUrl, onBaseUrl, label = { Text("Backend HTTPS URL") }, placeholder = { Text("https://your-api-host/") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(email, onEmail, label = { Text("อีเมล") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(password, onPassword, label = { Text("รหัสผ่าน") }, modifier = Modifier.fillMaxWidth(), singleLine = true, visualTransformation = PasswordVisualTransformation())
        Spacer(Modifier.height(14.dp))
        Button(onClick = onLogin, enabled = !busy && baseUrl.startsWith("https://") && email.isNotBlank() && password.isNotBlank(), modifier = Modifier.fillMaxWidth()) {
            Text(if (busy) "กำลังดำเนินการ..." else "เข้าสู่ระบบ")
        }
        Text(status, color = Muted, modifier = Modifier.padding(top = 12.dp))
        Text("เชื่อมต่อ HTTPS เท่านั้น · ไม่มีบัญชีหรือข้อมูลตัวอย่าง", color = Muted, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun DashboardScreen(
    health: String, status: String, runCount: Int, busy: Boolean,
    onRefresh: () -> Unit, onLogout: () -> Unit
) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { InfoCard("สถานะ Backend", health, if (health == "healthy") Green else Blue) }
        item { InfoCard("Workflow Runs ที่โหลดได้", runCount.toString(), Blue) }
        item {
            InfoCard("RestoreProof", "ยังไม่เปิดใช้งาน", Muted)
            Text("ยังไม่มี RestoreProof Worker ที่ผ่านการยืนยันใน Backend นี้ จึงปิดคำสั่ง Restore และไม่แสดงผล PASS จำลอง", color = Muted, modifier = Modifier.padding(8.dp))
        }
        item { Text(status, color = Muted) }
        item {
            Button(onClick = onRefresh, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text("รีเฟรชจาก Backend") }
            OutlinedButton(onClick = onLogout, modifier = Modifier.fillMaxWidth()) { Text("ล้าง Token / ออกจากอุปกรณ์") }
        }
    }
}

@Composable
private fun RunsScreen(items: List<Map<String, Any?>>) {
    if (items.isEmpty()) {
        Text("Backend ยังไม่ส่ง Workflow Run", color = Muted)
    } else {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(items.size) { index ->
                val item = items[index]
                InfoCard(
                    item["workflow_key"]?.toString() ?: "Workflow",
                    item["status"]?.toString() ?: "UNKNOWN",
                    Blue
                )
            }
        }
    }
}

@Composable
private fun AssistantScreen(
    prompt: String, onPrompt: (String) -> Unit,
    answer: String, busy: Boolean, onSend: () -> Unit
) {
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("ZYRQUEN Native AI", style = MaterialTheme.typography.titleLarge)
        Text("ผู้ช่วยอธิบายและวิเคราะห์งานผ่าน Native Model เท่านั้น การสั่งงานจริงต้องผ่าน API และ Approval Gate แยกต่างหาก", color = Muted)
        OutlinedTextField(prompt, onPrompt, modifier = Modifier.fillMaxWidth(), label = { Text("พิมพ์คำถามหรือคำสั่ง") }, minLines = 3)
        Button(onClick = onSend, enabled = !busy && prompt.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("ส่งให้ Native AI") }
        if (busy) { CircularProgressIndicator() }
        if (answer.isNotBlank()) {
            Card(colors = CardDefaults.cardColors(containerColor = Panel)) {
                Text(answer, modifier = Modifier.padding(16.dp))
            }
        }
    }
}

@Composable
private fun InfoCard(title: String, value: String, accent: Color) {
    Card(shape = RoundedCornerShape(18.dp), colors = CardDefaults.cardColors(containerColor = Panel)) {
        Column(Modifier.fillMaxWidth().padding(18.dp)) {
            Text(title, color = Muted)
            Text(value, color = accent, style = MaterialTheme.typography.headlineSmall)
        }
    }
}

private fun safeMessage(error: Exception): String = when (error) {
    is HttpException -> when (error.code()) {
        401 -> "การยืนยันตัวตนหมดอายุหรือไม่ถูกต้อง กรุณาเข้าสู่ระบบใหม่"
        403 -> "บัญชีนี้ไม่มีสิทธิ์ดำเนินการ"
        429 -> "คำขอเกินขีดจำกัด กรุณารอสักครู่"
        in 500..599 -> "Backend หรือ Native Model ไม่พร้อมใช้งาน"
        else -> "คำขอไม่สำเร็จ (HTTP ${error.code()})"
    }
    else -> error.message ?: "ไม่สามารถเชื่อมต่อบริการได้"
}

package com.example

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AdminPanelSettings
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Dashboard
import androidx.compose.material.icons.outlined.VerifiedUser
import androidx.compose.material.icons.rounded.AdminPanelSettings
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.Dashboard
import androidx.compose.material.icons.rounded.VerifiedUser
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.windowsizeclass.ExperimentalMaterial3WindowSizeClassApi
import androidx.compose.material3.windowsizeclass.WindowWidthSizeClass
import androidx.compose.material3.windowsizeclass.calculateWindowSizeClass
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.example.ai.configureAppCheck
import com.example.domain.ApprovalStatus
import com.example.ui.components.EvidenceReportDetailDialog
import com.example.ui.screens.AssistantScreen
import com.example.ui.screens.GovernanceScreen
import com.example.ui.screens.OverviewScreen
import com.example.ui.screens.VerifyScreen
import com.example.ui.theme.CoolGray
import com.example.ui.theme.ElectricBlue
import com.example.ui.theme.MidnightNavy
import com.example.ui.theme.NeonCyan
import com.example.ui.theme.RealityCheckTheme
import com.example.ui.theme.SlateRaised
import com.example.ui.theme.SlateSurface
import com.example.ui.theme.SoftWhite
import com.example.viewmodel.RealityCheckViewModel
import kotlinx.serialization.Serializable

@Serializable
object RouteOverview

@Serializable
object RouteAssistant

@Serializable
object RouteVerify

@Serializable
object RouteGovernance

private data class NavDestinationItem(
    val route: Any,
    val label: String,
    val selectedIcon: ImageVector,
    val unselectedIcon: ImageVector,
    val testTag: String
)

class MainActivity : ComponentActivity() {
    @OptIn(ExperimentalMaterial3WindowSizeClassApi::class)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // STEP 1: Configure Firebase App Check with launch intent BEFORE UI, ViewModels, or Firebase calls
        configureAppCheck(this, intent)

        setContent {
            val widthSizeClass = calculateWindowSizeClass(this).widthSizeClass
            RealityCheckTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MidnightNavy
                ) {
                    RealityCheckApp(useNavRail = widthSizeClass != WindowWidthSizeClass.Compact)
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RealityCheckApp(
    useNavRail: Boolean,
    viewModel: RealityCheckViewModel = viewModel()
) {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentDestination = backStackEntry?.destination

    val backupTargets by viewModel.backupTargets.collectAsStateWithLifecycle()
    val syncTargets by viewModel.syncTargets.collectAsStateWithLifecycle()
    val reports by viewModel.reports.collectAsStateWithLifecycle()
    val approvals by viewModel.approvals.collectAsStateWithLifecycle()
    val auditLogs by viewModel.auditLogs.collectAsStateWithLifecycle()
    val operatorRole by viewModel.operatorRole.collectAsStateWithLifecycle()
    val isolationGateState by viewModel.isolationGateState.collectAsStateWithLifecycle()
    val selectedReport by viewModel.selectedReport.collectAsStateWithLifecycle()
    val workerBusy by viewModel.workerBusy.collectAsStateWithLifecycle()
    val assistantBusy by viewModel.assistantBusy.collectAsStateWithLifecycle()
    val assistantTurns by viewModel.assistantTurns.collectAsStateWithLifecycle()
    val bannerNotice by viewModel.bannerNotice.collectAsStateWithLifecycle()

    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(bannerNotice) {
        val msg = bannerNotice
        if (!msg.isNullOrBlank()) {
            snackbarHostState.showSnackbar(msg)
            viewModel.clearBannerNotice()
        }
    }

    val pendingApprovalsCount = approvals.count { it.status == ApprovalStatus.PENDING_APPROVAL }

    val navItems = remember {
        listOf(
            NavDestinationItem(
                route = RouteOverview,
                label = "ภาพรวม",
                selectedIcon = Icons.Rounded.Dashboard,
                unselectedIcon = Icons.Outlined.Dashboard,
                testTag = "nav_overview"
            ),
            NavDestinationItem(
                route = RouteAssistant,
                label = "ผู้ช่วย AI",
                selectedIcon = Icons.Rounded.AutoAwesome,
                unselectedIcon = Icons.Outlined.AutoAwesome,
                testTag = "nav_assistant"
            ),
            NavDestinationItem(
                route = RouteVerify,
                label = "ตรวจสอบ",
                selectedIcon = Icons.Rounded.VerifiedUser,
                unselectedIcon = Icons.Outlined.VerifiedUser,
                testTag = "nav_verify"
            ),
            NavDestinationItem(
                route = RouteGovernance,
                label = "อนุมัติ/สิทธิ์",
                selectedIcon = Icons.Rounded.AdminPanelSettings,
                unselectedIcon = Icons.Outlined.AdminPanelSettings,
                testTag = "nav_governance"
            )
        )
    }

    fun navigateTo(route: Any) {
        navController.navigate(route) {
            popUpTo(navController.graph.findStartDestination().id) {
                saveState = true
            }
            launchSingleTop = true
            restoreState = true
        }
    }

    val screenTitle = when {
        currentDestination?.hasRoute<RouteAssistant>() == true -> "AI Operations Assistant"
        currentDestination?.hasRoute<RouteVerify>() == true -> "RestoreProof Worker"
        currentDestination?.hasRoute<RouteGovernance>() == true -> "Governance & Approvals"
        else -> "RealityCheck"
    }

    Row(modifier = Modifier.fillMaxSize()) {
        if (useNavRail) {
            NavigationRail(
                containerColor = SlateSurface,
                modifier = Modifier.windowInsetsPadding(WindowInsets.safeDrawing)
            ) {
                navItems.forEach { item ->
                    val selected = currentDestination?.hasRoute(item.route::class) == true
                    NavigationRailItem(
                        selected = selected,
                        onClick = { navigateTo(item.route) },
                        icon = {
                            if (item.route == RouteGovernance && pendingApprovalsCount > 0) {
                                BadgedBox(badge = { Badge { Text("$pendingApprovalsCount") } }) {
                                    Icon(
                                        imageVector = if (selected) item.selectedIcon else item.unselectedIcon,
                                        contentDescription = item.label
                                    )
                                }
                            } else {
                                Icon(
                                    imageVector = if (selected) item.selectedIcon else item.unselectedIcon,
                                    contentDescription = item.label
                                )
                            }
                        },
                        label = { Text(item.label) },
                        colors = NavigationRailItemDefaults.colors(
                            selectedIconColor = NeonCyan,
                            selectedTextColor = NeonCyan,
                            indicatorColor = SlateRaised,
                            unselectedIconColor = CoolGray,
                            unselectedTextColor = CoolGray
                        ),
                        modifier = Modifier.testTag(item.testTag)
                    )
                }
            }
        }

        Scaffold(
            modifier = Modifier.weight(1f),
            containerColor = MidnightNavy,
            snackbarHost = { SnackbarHost(hostState = snackbarHostState) },
            topBar = {
                TopAppBar(
                    title = {
                        Text(
                            text = screenTitle,
                            style = MaterialTheme.typography.titleLarge,
                            color = SoftWhite
                        )
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = SlateSurface
                    )
                )
            },
            bottomBar = {
                if (!useNavRail) {
                    NavigationBar(
                        containerColor = SlateSurface,
                        windowInsets = WindowInsets.navigationBars
                    ) {
                        navItems.forEach { item ->
                            val selected = currentDestination?.hasRoute(item.route::class) == true
                            NavigationBarItem(
                                selected = selected,
                                onClick = { navigateTo(item.route) },
                                icon = {
                                    if (item.route == RouteGovernance && pendingApprovalsCount > 0) {
                                        BadgedBox(badge = { Badge { Text("$pendingApprovalsCount") } }) {
                                            Icon(
                                                imageVector = if (selected) item.selectedIcon else item.unselectedIcon,
                                                contentDescription = item.label
                                            )
                                        }
                                    } else {
                                        Icon(
                                            imageVector = if (selected) item.selectedIcon else item.unselectedIcon,
                                            contentDescription = item.label
                                        )
                                    }
                                },
                                label = { Text(item.label, maxLines = 1) },
                                colors = NavigationBarItemDefaults.colors(
                                    selectedIconColor = NeonCyan,
                                    selectedTextColor = NeonCyan,
                                    indicatorColor = ElectricBlue.copy(alpha = 0.25f),
                                    unselectedIconColor = CoolGray,
                                    unselectedTextColor = CoolGray
                                ),
                                modifier = Modifier.testTag(item.testTag)
                            )
                        }
                    }
                }
            }
        ) { innerPadding ->
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding)
            ) {
                NavHost(
                    navController = navController,
                    startDestination = RouteOverview
                ) {
                    composable<RouteOverview> {
                        OverviewScreen(
                            backupTargets = backupTargets,
                            reports = reports,
                            approvals = approvals,
                            operatorRole = operatorRole,
                            isolationGateState = isolationGateState,
                            workerBusy = workerBusy,
                            onLaunchAiCommand = { cmd ->
                                navigateTo(RouteAssistant)
                                viewModel.sendAssistantCommand(cmd)
                            },
                            onVerifyAllBackups = { viewModel.verifyAllBackups() },
                            onRunIsolationSuite = { viewModel.runIsolationSuite() },
                            onSelectReport = { viewModel.selectReport(it) },
                            onNavigateVerify = { navigateTo(RouteVerify) }
                        )
                    }
                    composable<RouteAssistant> {
                        AssistantScreen(
                            turns = assistantTurns,
                            assistantBusy = assistantBusy,
                            onSendCommand = { viewModel.sendAssistantCommand(it) },
                            onSelectReport = { viewModel.selectReport(it) },
                            onOpenApprovals = { navigateTo(RouteGovernance) }
                        )
                    }
                    composable<RouteVerify> {
                        VerifyScreen(
                            backupTargets = backupTargets,
                            syncTargets = syncTargets,
                            reports = reports,
                            workerBusy = workerBusy,
                            onVerifyBackup = { viewModel.verifyBackup(it) },
                            onVerifyAllBackups = { viewModel.verifyAllBackups() },
                            onVerifySync = { viewModel.verifySyncPair(it) },
                            onRunIsolationSuite = { viewModel.runIsolationSuite() },
                            onImportAndVerifyUri = { uri, name ->
                                viewModel.importAndVerifyUserArchive(uri, name)
                            },
                            onSelectReport = { viewModel.selectReport(it) }
                        )
                    }
                    composable<RouteGovernance> {
                        GovernanceScreen(
                            operatorRole = operatorRole,
                            isolationGateState = isolationGateState,
                            approvals = approvals,
                            auditLogs = auditLogs,
                            onSwitchRole = { viewModel.switchRole(it) },
                            onDecideApproval = { id, approve -> viewModel.decideApproval(id, approve) }
                        )
                    }
                }
            }
        }
    }

    selectedReport?.let { report ->
        EvidenceReportDetailDialog(
            report = report,
            exportJson = viewModel.exportReportJson(report),
            onDismiss = { viewModel.selectReport(null) }
        )
    }
}

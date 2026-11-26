package com.example.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp

private val RealityCheckDarkColorScheme = darkColorScheme(
    primary = ElectricBlue,
    onPrimary = SoftWhite,
    primaryContainer = SlateHover,
    onPrimaryContainer = NeonCyan,
    secondary = NeonCyan,
    onSecondary = MidnightNavy,
    secondaryContainer = SlateRaised,
    onSecondaryContainer = SoftWhite,
    tertiary = VioletHighlight,
    onTertiary = MidnightNavy,
    background = MidnightNavy,
    onBackground = SoftWhite,
    surface = SlateSurface,
    onSurface = SoftWhite,
    surfaceVariant = SlateRaised,
    onSurfaceVariant = CoolGray,
    surfaceContainerLowest = DeepGraphite,
    surfaceContainerLow = SlateSurface,
    surfaceContainer = SlateRaised,
    surfaceContainerHigh = SlateHover,
    outline = SlateBorder,
    outlineVariant = SlateBorder,
    error = StatusFail,
    onError = MidnightNavy,
    errorContainer = StatusFailBg,
    onErrorContainer = StatusFail
)

private val RealityCheckShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(18.dp),
    extraLarge = RoundedCornerShape(24.dp)
)

@Composable
fun RealityCheckTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = RealityCheckDarkColorScheme,
        typography = RealityCheckTypography,
        shapes = RealityCheckShapes,
        content = content
    )
}

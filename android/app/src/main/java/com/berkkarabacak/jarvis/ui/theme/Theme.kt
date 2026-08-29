package com.berkkarabacak.jarvis.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Cream = Color(0xFFF7F0E8)
private val Ink = Color(0xFF1B2430)
private val Card = Color(0xFFFFFBF7)
private val Accent = Color(0xFF2F5D50)

private val Colors = lightColorScheme(
    primary = Accent,
    onPrimary = Color.White,
    secondary = Ink,
    onSecondary = Cream,
    background = Cream,
    onBackground = Ink,
    surface = Card,
    onSurface = Ink,
    surfaceVariant = Color(0xFFEFE4D6),
    onSurfaceVariant = Color(0xFF3D4A3F),
    error = Color(0xFF8B2E2E),
)

@Composable
fun JarvisTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = Colors,
        content = content,
    )
}

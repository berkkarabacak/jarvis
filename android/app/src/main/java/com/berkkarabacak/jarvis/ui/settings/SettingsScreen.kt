package com.berkkarabacak.jarvis.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import com.berkkarabacak.jarvis.R
import com.berkkarabacak.jarvis.billing.PlayCatalog
import com.berkkarabacak.jarvis.billing.SubscribePlan
import com.berkkarabacak.jarvis.billing.SubscribeUiState
import com.berkkarabacak.jarvis.data.BudgetStatus
import com.berkkarabacak.jarvis.data.JarvisJson

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun SettingsScreen(
    viewModel: SettingsViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsState()
    val lookSpeeds = state.lookSpeeds.ifEmpty { JarvisJson.defaultLookSpeeds() }
    val qualities = state.qualityChoices.ifEmpty { JarvisJson.defaultQualityChoices() }
    val activity = LocalContext.current.findActivity()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.settings_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Outlined.ArrowBack,
                            contentDescription = "Back",
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            SectionTitle(stringResource(R.string.settings_connection))
            OutlinedTextField(
                value = state.baseUrl,
                onValueChange = viewModel::setBaseUrl,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.settings_base_url)) },
                placeholder = { Text("http://192.168.1.20:8787") },
                singleLine = true,
            )
            OutlinedTextField(
                value = state.apiKey,
                onValueChange = viewModel::setApiKey,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.settings_api_key)) },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
            )
            OutlinedButton(
                onClick = viewModel::testConnection,
                enabled = !state.busy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(stringResource(R.string.settings_test))
            }

            SectionTitle(stringResource(R.string.settings_budget_title))
            Text(
                text = stringResource(R.string.settings_budget_hint),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedTextField(
                value = state.monthlyBudgetText,
                onValueChange = viewModel::setMonthlyBudgetText,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.settings_monthly_budget)) },
                placeholder = { Text(stringResource(R.string.settings_no_limit)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            )
            SpendLine(state.budget, monthly = true)
            OutlinedTextField(
                value = state.dailyBudgetText,
                onValueChange = viewModel::setDailyBudgetText,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.settings_daily_budget)) },
                placeholder = { Text(stringResource(R.string.settings_no_limit)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            )
            SpendLine(state.budget, monthly = false)
            BudgetActionLine(state.budget)

            SectionTitle(stringResource(R.string.settings_quality_title))
            Text(
                text = qualities.firstOrNull { it.id == state.qualityVsPrice }?.allows
                    ?: "A middle path — not the cheapest, not the most expensive.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                qualities.forEach { option ->
                    FilterChip(
                        selected = state.qualityVsPrice == option.id,
                        onClick = { viewModel.setQualityVsPrice(option.id) },
                        label = { Text(option.label) },
                    )
                }
            }

            SectionTitle(stringResource(R.string.settings_look_speed))
            Text(
                text = lookSpeeds.firstOrNull { it.id == state.lookSpeed }?.allows
                    ?: "Off means I only look when a job needs a picture.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                lookSpeeds.forEach { option ->
                    FilterChip(
                        selected = state.lookSpeed == option.id,
                        onClick = { viewModel.setLookSpeed(option.id) },
                        label = { Text(option.label) },
                    )
                }
            }

            SectionTitle(stringResource(R.string.settings_permission))
            if (state.permissionProfiles.isEmpty()) {
                Text(
                    text = "Load settings from the server to see what each choice allows.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            state.permissionProfiles.forEach { option ->
                FilterChip(
                    selected = state.permissionProfile == option.id,
                    onClick = { viewModel.setPermissionProfile(option.id) },
                    label = { Text(option.label) },
                    modifier = Modifier.fillMaxWidth(),
                )
                if (state.permissionProfile == option.id && option.allows.isNotBlank()) {
                    Text(
                        text = option.allows,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            SubscribeSection(
                subscribe = state.subscribe,
                enabled = !state.busy,
                onPick = { productId -> viewModel.pickPlan(productId, activity) },
            )

            if (state.status.isNotBlank()) {
                Text(
                    text = state.status,
                    color = if (state.statusIsError) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.primary
                    },
                    style = MaterialTheme.typography.bodyLarge,
                )
            }

            Button(
                onClick = viewModel::save,
                enabled = !state.busy,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 24.dp),
            ) {
                Text(if (state.busy) "Working…" else stringResource(R.string.settings_save))
            }
        }
    }
}

@Composable
private fun SpendLine(budget: BudgetStatus?, monthly: Boolean) {
    val text = spendLabel(budget, monthly) ?: return
    Text(
        text = text,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
private fun BudgetActionLine(budget: BudgetStatus?) {
    val text = when (budget?.action) {
        "stop" -> "Jarvis will stop — a spending limit was reached."
        "cheaper" -> "Near the limit — Jarvis will use a cheaper model."
        else -> return
    }
    Text(
        text = text,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.error,
    )
}

@Composable
private fun SectionTitle(text: String) {
    Text(text = text, style = MaterialTheme.typography.titleLarge)
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SubscribeSection(
    subscribe: SubscribeUiState,
    enabled: Boolean,
    onPick: (String) -> Unit,
) {
    val current = subscribe.plans.firstOrNull { it.current }
        ?: subscribe.plans.firstOrNull { it.productId == PlayCatalog.FREE }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            text = stringResource(R.string.settings_subscribe_title),
            style = MaterialTheme.typography.titleLarge,
        )
        Text(
            text = stringResource(R.string.settings_subscribe_hint),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = currentPlanLabel(current),
            style = MaterialTheme.typography.bodyLarge,
        )
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            subscribe.plans.forEach { plan ->
                FilterChip(
                    selected = plan.current,
                    onClick = { onPick(plan.productId) },
                    enabled = enabled && !subscribe.busy,
                    label = { Text(planChipLabel(plan)) },
                )
            }
        }
        subscribe.plans.forEach { plan ->
            if (plan.current && plan.description.isNotBlank()) {
                Text(
                    text = plan.description,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (!subscribe.playAvailable || subscribe.message == PlayCatalog.PLAY_NEEDED) {
            Text(
                text = PlayCatalog.PLAY_NEEDED,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else if (subscribe.message.isNotBlank()) {
            Text(
                text = subscribe.message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

internal fun currentPlanLabel(plan: SubscribePlan?): String {
    val name = plan?.title ?: "Free"
    return "Current plan: $name"
}

internal fun planChipLabel(plan: SubscribePlan): String {
    return if (plan.current) "${plan.priceLabel} · current" else plan.priceLabel
}

private fun Context.findActivity(): Activity? {
    var ctx: Context = this
    while (ctx is ContextWrapper) {
        if (ctx is Activity) return ctx
        ctx = ctx.baseContext
    }
    return null
}

internal fun spendLabel(budget: BudgetStatus?, monthly: Boolean): String? {
    if (budget == null) return null
    val spent = if (monthly) budget.monthlySpentUsd else budget.dailySpentUsd
    val cap = if (monthly) budget.monthlyCapUsd else budget.dailyCapUsd
    val period = if (monthly) "month" else "day"
    if (spent == null && cap == null) return null
    if (cap == null) {
        return if (spent != null) "Spent ${moneyLabel(spent)} this $period (no limit)." else null
    }
    return if (spent != null) {
        "Spent ${moneyLabel(spent)} of ${moneyLabel(cap)} this $period."
    } else {
        "Limit ${moneyLabel(cap)} this $period."
    }
}

internal fun moneyLabel(value: Double): String {
    return if (value == value.toLong().toDouble()) "$${value.toLong()}" else "$" + "%.2f".format(value)
}

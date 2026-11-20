// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Hello

/**
 * Allumage et extinction du poste à distance (fonction « power », docs/protocole.md § 21 ; lot P3). Mêmes vues et
 * mêmes textes que la page (client.js : powerStepsView, powerBannerView, stopHoldChoices). Kotlin pur, testé sans écran.
 */
data class PowerStep(val status: String = "", val detail: String = "", val ort: String = "", val remainingS: Double? = null)

/** Allumage suivi par CE téléphone : `status` = running, done, error ; `hidden` = fenêtre masquée (l'allumage continue). */
data class PowerRun(
    val status: String = "running",
    val steps: Map<String, PowerStep> = emptyMap(),
    val how: String = "connect",
    val error: String = "",
    val done: String = "",
    val hidden: Boolean = false,
)

data class PowerLine(val key: String, val label: String, val status: String, val detail: String)

data class PowerDialogView(
    val status: String,
    val title: String,
    val lines: List<PowerLine>,
    val text: String,
    val canRetry: Boolean,
    val canContinue: Boolean,
    val canHide: Boolean,
    /** Réussite : la fenêtre se ferme seule après ce délai (0 = non). */
    val autoCloseMs: Long,
)

data class PowerBanner(val text: String, val canPowerOn: Boolean)

data class StopHoldChoices(val powerOff: Boolean, val powerReason: String)

object Power {
    /** Étapes de l'allumage (codes du protocole, textes `power.step_<code>`). */
    private val STEP_KEYS = listOf("ports", "check_off", "order", "wait", "readback")
    val STEPS: List<Pair<String, String>> get() = STEP_KEYS.map { it to Tr.t("power.step_$it") }
    const val STOP_HOLD_MS = 3000L
    const val STOP_HOLD_AUTO_CANCEL_MS = 15_000L
    val CONFIRM_TITLE: String get() = Tr.t("power.confirm_title")
    val CONFIRM_TEXT: String get() = Tr.t("power.confirm_text")
    private val ORT = Regex("^ORT-\\d{4}$")

    /** Fenêtre « Allumage du TRX » ; null = rien à montrer (pas d'allumage suivi, ou fenêtre masquée). */
    fun dialog(run: PowerRun?): PowerDialogView? {
        if (run == null || run.hidden) return null
        val lines = STEPS.map { (key, label) ->
            val s = run.steps[key] ?: PowerStep()
            val status = when (s.status) { "ok" -> "ok"; "error" -> "error"; "running" -> "running"; else -> "pending" }
            var detail = s.detail.take(300)
            if (key == "wait" && status == "running" && s.remainingS != null) {
                detail = Tr.t("power.wait_left", "seconds" to kotlin.math.ceil(maxOf(0.0, s.remainingS)).toInt())
            }
            if (status == "error" && ORT.matches(s.ort)) detail += " [${s.ort}]"
            PowerLine(key, label, status, detail)
        }
        val text = when (run.status) {
            "done" -> run.done.ifEmpty { Tr.t("power.done") }
            "error" -> run.error.ifEmpty { Tr.t("power.error") }
            else -> Tr.t("power.running")
        }
        return PowerDialogView(run.status, Tr.t("power.dialog_title"), lines, text, canRetry = run.status == "error",
            canContinue = run.status == "error", canHide = run.status == "running",
            autoCloseMs = if (run.status == "done") 3000L else 0L)
    }

    /** Bandeau « POSTE ÉTEINT » (state.rig.power, visiteurs compris) ; null = poste allumé ou inconnu. */
    fun banner(rigPower: String?, hello: Hello?, running: Boolean): PowerBanner? {
        if (rigPower != "off") return null
        if (hello?.listener == true) return PowerBanner(Tr.t("power.banner_listener"), false)
        if (hello?.offers("power") != true) {
            return PowerBanner(Tr.t("power.banner_disabled"), false)
        }
        return PowerBanner(if (running) Tr.t("power.banner_running") else Tr.t("power.banner_off"), !running)
    }

    /** STOP maintenu 3 s : « Se déconnecter » toujours ; « Arrêter le TRX à distance » grisé avec sa raison. */
    fun stopHold(hello: Hello?, rigPower: String?): StopHoldChoices {
        val reason = when {
            hello?.listener == true -> Tr.t("power.reason_listener")
            // station 0.222.0+ : can_set_power / can_get_power toujours envoyés ; sans eux (station ancienne) = « ne le permet pas »
            hello?.offers("power") != true ->
                if (hello?.capabilities?.let { it.canSetPower && it.canGetPower } == true) Tr.t("power.reason_disabled")
                else Tr.t("power.reason_unsupported")
            rigPower == "off" -> Tr.t("power.reason_already_off")
            else -> ""
        }
        return StopHoldChoices(powerOff = reason.isEmpty(), powerReason = reason)
    }

    /** Titre d'Android Auto quand le poste est éteint ou s'allume ; null = titre habituel. */
    fun carTitle(rigPower: String?, run: PowerRun?): String? = when {
        run?.status == "running" -> Tr.t("power.car_running")
        rigPower == "off" && run?.status == "error" -> Tr.t("power.car_error")
        rigPower == "off" -> Tr.t("power.car_off")
        else -> null
    }
}

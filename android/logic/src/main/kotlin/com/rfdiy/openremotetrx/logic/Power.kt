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
    val STEPS = listOf(
        "ports" to "Vérification des ports série du poste",
        "check_off" to "Vérification que le poste est bien éteint",
        "order" to "Ordre d'allumage envoyé",
        "wait" to "Démarrage du poste (quelques secondes ; environ 8 s pour un FTDX10)",
        "readback" to "Relecture : réception confirmée, fréquence et mode",
    )
    const val STOP_HOLD_MS = 3000L
    const val STOP_HOLD_AUTO_CANCEL_MS = 15_000L
    const val CONFIRM_TITLE = "Confirmer l'arrêt à distance de votre TRX ?"
    const val CONFIRM_TEXT = "Plus personne ne pourra l'écouter ; il se rallumera à la prochaine connexion d'un opérateur."
    private val ORT = Regex("^ORT-\\d{4}$")

    /** Fenêtre « Allumage du TRX » ; null = rien à montrer (pas d'allumage suivi, ou fenêtre masquée). */
    fun dialog(run: PowerRun?): PowerDialogView? {
        if (run == null || run.hidden) return null
        val lines = STEPS.map { (key, label) ->
            val s = run.steps[key] ?: PowerStep()
            val status = when (s.status) { "ok" -> "ok"; "error" -> "error"; "running" -> "running"; else -> "pending" }
            var detail = s.detail.take(300)
            if (key == "wait" && status == "running" && s.remainingS != null) {
                detail = "encore ${kotlin.math.ceil(maxOf(0.0, s.remainingS)).toInt()} s au plus"
            }
            if (status == "error" && ORT.matches(s.ort)) detail += " [${s.ort}]"
            PowerLine(key, label, status, detail)
        }
        val text = when (run.status) {
            "done" -> run.done.ifEmpty { "TRX allumé." }
            "error" -> run.error.ifEmpty { "Allumage impossible." }
            else -> "Allumage en cours : la réception reprend toute seule à la fin."
        }
        return PowerDialogView(run.status, "Allumage du TRX", lines, text, canRetry = run.status == "error",
            canContinue = run.status == "error", canHide = run.status == "running",
            autoCloseMs = if (run.status == "done") 3000L else 0L)
    }

    /** Bandeau « POSTE ÉTEINT » (state.rig.power, visiteurs compris) ; null = poste allumé ou inconnu. */
    fun banner(rigPower: String?, hello: Hello?, running: Boolean): PowerBanner? {
        if (rigPower != "off") return null
        if (hello?.listener == true) return PowerBanner("Le poste est éteint ; seul un opérateur peut l'allumer.", false)
        if (hello?.offers("power") != true) {
            return PowerBanner("POSTE ÉTEINT : allumage à distance hors service (menu 2.8 de TRX Console sur la station).", false)
        }
        return PowerBanner(if (running) "POSTE ÉTEINT : allumage en cours…" else "POSTE ÉTEINT", !running)
    }

    /** STOP maintenu 3 s : « Se déconnecter » toujours ; « Arrêter le TRX à distance » grisé avec sa raison. */
    fun stopHold(hello: Hello?, rigPower: String?): StopHoldChoices {
        val reason = when {
            hello?.listener == true -> "Compte visiteur"
            // station 0.222.0+ : can_set_power / can_get_power toujours envoyés ; sans eux (station ancienne) = « ne le permet pas »
            hello?.offers("power") != true ->
                if (hello?.capabilities?.let { it.canSetPower && it.canGetPower } == true) "Arrêt à distance hors service : menu 2.8 de TRX Console"
                else "Votre poste ne le permet pas"
            rigPower == "off" -> "Le poste est déjà éteint"
            else -> ""
        }
        return StopHoldChoices(powerOff = reason.isEmpty(), powerReason = reason)
    }

    /** Titre d'Android Auto quand le poste est éteint ou s'allume ; null = titre habituel. */
    fun carTitle(rigPower: String?, run: PowerRun?): String? = when {
        run?.status == "running" -> "ALLUMAGE DU POSTE…"
        rigPower == "off" && run?.status == "error" -> "POSTE ÉTEINT : erreur"
        rigPower == "off" -> "POSTE ÉTEINT"
        else -> null
    }
}

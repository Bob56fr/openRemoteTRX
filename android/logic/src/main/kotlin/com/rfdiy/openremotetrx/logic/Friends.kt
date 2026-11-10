// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.longOrNull
import java.time.Instant
import java.time.ZoneId
import java.util.Locale

/**
 * Présence de groupe « Amis » (docs/presence-cahier-des-charges.md, docs/protocole.md § 16), reprise de la page
 * (friends.js) : MÊMES textes et mêmes règles ; âges, pseudo et texte libre vérifiés sur les vecteurs de la station
 * (tests/protocol/presence_vectors.json). Kotlin pur : rien ici n'agit sur le poste. Le QSY vers un ami est confirmé
 * par l'opérateur, refusé pendant l'émission, et passe par les commandes habituelles (mode puis fréquence).
 */
object Friends {
    const val OFFLINE_AFTER_S = 240L
    const val REFRESH_MS = 30_000L
    private val ORDER = mapOf("Q" to 0, "R" to 1, "S" to 2, "A" to 3, "O" to 4)
    val LABELS = mapOf("Q" to "En QSO", "R" to "En RX", "S" to "Au shack", "A" to "Absent", "O" to "Hors ligne")
    val ROLES = mapOf("a" to "administrateur", "c" to "co-administrateur", "m" to "membre")
    val STATUS = mapOf("member" to "", "pending" to "adhésion en attente de validation", "removed" to "exclu ou groupe supprimé")
    val LEVELS = linkedMapOf("f" to "Fréquence et mode", "o" to "« On Air » seulement", "x" to "Un court texte")
    val CONSENT = listOf(
        "L'administrateur du groupe verra des statistiques d'activité AGRÉGÉES de votre station : jours actifs, temps approximatif en QSO et en réception par semaine, date d'adhésion, version de la station. Jamais un emploi du temps détaillé.",
        "Les membres du groupe verront votre statut (en QSO, en réception, au shack, absent, hors ligne) et ce que vous choisissez de partager ci-dessous ; vous pourrez le changer, ou devenir invisible, à tout moment.",
        "Le relais de présence ne voit que des états chiffrés : ni fréquence, ni mode, ni texte, ni statut.",
    )
    private val PSEUDO_RE = Regex("^[A-Za-z0-9](?:[A-Za-z0-9 ./_-]{0,14}[A-Za-z0-9./_-])?$")
    private val TEXT_RE = Regex("^[A-Za-z0-9./-](?:[A-Za-z0-9 ./-]{0,14}[A-Za-z0-9./-])?$")

    private fun squeeze(s: String) = s.split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")
    /** Même règle que la station (wire.clean_pseudo) : null si refusé. */
    fun cleanPseudo(s: String): String? = squeeze(s).takeIf { PSEUDO_RE.matches(it) }
    /** Même règle que la station (wire.clean_text) : null si refusé. */
    fun cleanText(s: String): String? = squeeze(s).takeIf { TEXT_RE.matches(it) }

    /** Comme la station (status.format_age) : « 3 min » (1 au moins), « 2 h », « 4 j ». */
    fun formatAge(seconds: Long): String {
        val s = maxOf(0, seconds)
        return when {
            s < 3600 -> "${maxOf(1, s / 60)} min"
            s < 86400 -> "${s / 3600} h"
            else -> "${s / 86400} j"
        }
    }

    /** « mis à jour il y a … » : secondes sous la minute. */
    fun freshness(seconds: Long): String = if (seconds < 60) "${maxOf(0, seconds)} s" else formatAge(seconds)

    fun frequencyText(hz: Long): String = String.format(Locale.ROOT, "%.3f", hz / 1e6).replace('.', ',') + " MHz"

    data class Member(
        val id: String, val pseudo: String, val code: String, val letter: String, val label: String, val detail: String,
        val lines: List<String>, val qsy: Boolean, val hz: Long?, val mode: String?, val txOk: Boolean?, val role: String,
        val groups: List<String> = emptyList(),
    )

    data class Group(
        val g: String, val name: String, val role: String, val roleText: String, val status: String, val statusText: String,
        val admin: Boolean, val share: Share, val members: List<Member>,
    )

    data class Share(val level: String = "o", val text: String? = null, val invisible: Boolean = false, val hideAbsence: Boolean = false)

    data class View(
        val pseudo: String, val registered: Boolean, val problem: String?, val texts: List<String>, val groups: List<Group>,
        /** Vue par membre : un membre de plusieurs groupes une seule fois (avec ses groupes). */
        val members: List<Member>,
    )

    private fun JsonObject.str(k: String) = (this[k] as? JsonPrimitive)?.contentOrNull
    private fun JsonObject.long(k: String) = (this[k] as? JsonPrimitive)?.let { if (it.isString) null else it.longOrNull }
    private fun JsonObject.bool(k: String) = (this[k] as? JsonPrimitive)?.booleanOrNull

    private fun clock(epochS: Long, zone: ZoneId): String {
        val t = Instant.ofEpochSecond(epochS).atZone(zone)
        return String.format(Locale.ROOT, "%02d:%02d", t.hour, t.minute)
    }

    /** Un membre tel qu'affiché ; `elapsedS` : secondes depuis la lecture de la vue (les âges avancent sans la redemander). */
    fun member(m: JsonObject, nowS: Long, elapsedS: Long, zone: ZoneId = ZoneId.systemDefault()): Member {
        val e = maxOf(0, elapsedS)
        val age = m.long("age") ?: (OFFLINE_AFTER_S + 1)
        var code = m.str("code")?.takeIf { it in ORDER } ?: "O"
        if (age + e > OFFLINE_AFTER_S) code = "O"
        val label = LABELS.getValue(code)
        val sd = m.long("sd"); val lt = m.long("lt"); val su = m.long("su"); val updated = m.long("updated")
        val lv = m.str("lv"); val hz = m.long("f"); val mode = m.str("m"); val text = m.str("x")
        val detail = when {
            code == "O" -> "Hors ligne"
            code == "S" -> if (su != null) "Au shack jusqu'à " + clock(su, zone) else "Au shack"
            code == "A" -> if (sd != null) "Absent depuis " + formatAge(nowS - sd) else "Absent"
            lv == "f" && hz != null -> frequencyText(hz) + (if (mode != null) " $mode" else "")
            lv == "x" && !text.isNullOrEmpty() -> "« $text »"
            else -> if (code == "Q") "On Air" else label
        }
        val lines = buildList {
            if (code != "O") {
                if (sd != null) add("$label depuis " + formatAge(nowS - sd))
                if (lt != null) add("Dernière émission il y a " + formatAge(nowS - lt))
                if (updated != null) add("Mis à jour il y a " + freshness(updated + e))
            } else add("Dernière nouvelle il y a " + formatAge(age + e))
        }
        return Member(
            id = m.str("id").orEmpty(), pseudo = m.str("pseudo") ?: "?", code = code, letter = if (code == "O") "" else code,
            label = label, detail = detail, lines = lines, qsy = code != "O" && lv == "f" && hz != null && !mode.isNullOrEmpty(),
            hz = hz, mode = mode, txOk = m.bool("tx_ok"), role = m.str("role") ?: "m",
        )
    }

    private fun sorted(list: List<Member>) =
        list.sortedWith(compareBy<Member>({ ORDER.getValue(it.code) }, { it.pseudo.lowercase(Locale.FRENCH) }))

    /** Vue de la station (action « view ») ; null si illisible. */
    fun view(data: JsonObject?, nowS: Long, elapsedS: Long, zone: ZoneId = ZoneId.systemDefault()): View? {
        data ?: return null
        val groups = (data["groups"] as? JsonArray).orEmpty().mapNotNull { item ->
            val g = item as? JsonObject ?: return@mapNotNull null
            val role = g.str("role") ?: "m"
            val status = g.str("status") ?: "member"
            val share = (g["share"] as? JsonObject)?.let { s ->
                Share(s.str("level") ?: "o", s.str("text"), s.bool("invisible") == true, s.bool("hide_absence") == true)
            } ?: Share()
            Group(g.str("g").orEmpty(), g.str("name") ?: "?", role, ROLES[role].orEmpty(), status, STATUS[status].orEmpty(),
                  role == "a" || role == "c", share,
                  sorted((g["members"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonObject)?.let { m -> member(m, nowS, elapsedS, zone) } }))
        }
        val byId = LinkedHashMap<String, Member>()
        for (g in groups) for (m in g.members) {
            val known = byId[m.id]
            val names = (known?.groups ?: emptyList()) + g.name
            byId[m.id] = if (known == null || ORDER.getValue(m.code) < ORDER.getValue(known.code)) m.copy(groups = names) else known.copy(groups = names)
        }
        return View(data.str("pseudo").orEmpty(), data.bool("registered") == true, data.str("problem"),
                    (data["texts"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }, groups,
                    sorted(byId.values.toList()))
    }

    data class Badges(val list: List<Member>, val active: Int, val total: Int)

    /** Pastilles du bandeau : actifs d'abord, `max` au plus. */
    fun badges(view: View?, max: Int = 8): Badges {
        val all = view?.members.orEmpty()
        return Badges(all.filter { it.code != "O" }.take(max), all.count { it.code == "Q" || it.code == "R" }, all.size)
    }

    private val BAND_EDGES_KHZ = listOf(1810 to 2000, 3500 to 3800, 5351 to 5367, 7000 to 7200, 10100 to 10150,
        14000 to 14350, 18068 to 18168, 21000 to 21450, 24890 to 24990, 26960 to 27410, 28000 to 29700, 50000 to 54000,
        144000 to 146000, 430000 to 440000)

    fun bandOf(hz: Long): Int? = BAND_EDGES_KHZ.firstOrNull { (lo, hi) -> hz / 1000.0 in lo.toDouble()..hi.toDouble() }?.first

    data class Warning(val level: String, val text: String)
    data class QsyPlan(val ok: Boolean, val reason: String = "", val text: String, val hz: Long? = null, val mode: String? = null,
                       val warnings: List<Warning> = emptyList())

    /** Ce que demande le QSY vers un ami : refus, ou texte de confirmation et avertissements (comme friends.js qsyPlan). */
    fun qsyPlan(member: Member?, pttState: String?, rigHz: Long?, selfCode: String? = null): QsyPlan {
        if (pttState != null && pttState != "RX") return QsyPlan(false, "tx_active", "Émission en cours : pas de QSY.")
        if (member == null || !member.qsy) return QsyPlan(false, "no_frequency", "Ce membre ne partage pas sa fréquence.")
        val hz = member.hz!!
        val warnings = buildList {
            if (selfCode == "Q") add(Warning("strong", "Vous êtes en QSO : votre correspondant ne vous entendra plus sur votre fréquence actuelle."))
            if (member.lines.isNotEmpty()) add(Warning("info", member.lines.joinToString(" · ")))
            if (rigHz != null && bandOf(rigHz) != bandOf(hz)) add(Warning("warn", "Changement de bande : vérifiez l'accord de l'antenne avant d'émettre."))
            if (member.txOk == false) add(Warning("warn", "Hors des bandes d'émission de cette station : réception seulement."))
        }
        return QsyPlan(true, text = "Aller sur ${frequencyText(hz)} ${member.mode} ?", hz = hz, mode = member.mode, warnings = warnings)
    }

    data class StatsRow(val id: String, val pseudo: String, val lastActive: String, val days: Int, val qsoMin: Long, val rxMin: Long)

    /** Statistiques de l'administrateur (action « stats »). */
    fun statsRows(stats: JsonObject?, pseudos: Map<String, String>): List<StatsRow> =
        stats.orEmpty().map { (id, v) ->
            val s = v as? JsonObject ?: JsonObject(emptyMap())
            val week = ((s["weeks"] as? JsonArray)?.firstOrNull() as? JsonObject) ?: JsonObject(emptyMap())
            StatsRow(id, pseudos[id] ?: id.take(8), s.str("last_active") ?: "—", (s.long("active_days_month") ?: 0).toInt(),
                     week.long("qso_min") ?: 0, week.long("rx_min") ?: 0)
        }.sortedBy { it.pseudo.lowercase(Locale.FRENCH) }

    /** Onglet « Amis » du téléphone (demande de l'utilisateur, 2026-11-11) : seulement quand la station fait partie
     *  d'au moins un groupe (membre, adhésion en attente ou exclue) ; avant, créer ou rejoindre se fait dans l'onglet
     *  Mémoires. */
    fun inGroup(f: FriendsState?): Boolean = (f?.data?.get("groups") as? JsonArray)?.isNotEmpty() == true

    /** Vue mise en forme à partir de l'état de la session (l'interface ne lit jamais le JSON elle-même). */
    fun ofState(f: FriendsState?, nowMs: Long, zone: ZoneId = ZoneId.systemDefault()): View? =
        f?.let { view(it.data, nowMs / 1000, maxOf(0, (nowMs - it.atWallMs) / 1000), zone) }

    /** Statistiques reçues (après « stats ») : (groupe, lignes), pseudos pris dans la vue. */
    fun statsOf(f: FriendsState?, view: View?): Pair<Group?, List<StatsRow>>? = f?.stats?.let { (g, s) ->
        val group = view?.groups?.firstOrNull { it.g == g }
        group to statsRows(s, group?.members.orEmpty().associate { it.id to it.pseudo })
    }

    /** Invitation collée : l'URL entière (ou le code après #), sans espaces ; null si visiblement incomplète. */
    fun cleanInvitation(text: String): String? = text.trim().replace(Regex("\\s+"), "").takeIf { it.length in 20..1000 }
}

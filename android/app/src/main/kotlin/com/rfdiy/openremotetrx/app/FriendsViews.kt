// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.view.WindowManager
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.Friends
import com.rfdiy.openremotetrx.logic.RigState
import com.rfdiy.openremotetrx.logic.Tr
import kotlinx.coroutines.delay

/*
 * Présence de groupe « Amis » (docs/presence-cahier-des-charges.md § 9.3), mêmes règles et mêmes textes que la page
 * (logic/Friends.kt ↔ friends.js). Pastille = couleur ET lettre (lisible par les daltoniens). Le QSY vers un ami est
 * confirmé ici, refusé pendant l'émission (ici et par la station), puis passe par mode et fréquence ; jamais d'émission.
 * Pas d'Android Auto (décision de l'utilisateur du 2026-11-10).
 */

internal const val PREF_FRIENDS_BLOCK = "friends_block"         // bloc « Amis » à la place du petit waterfall et des bandes
private const val PREF_FRIENDS_BY = "friends_by"
private val WARN = Page.ALERTE
private val FR_COLORS = mapOf("Q" to Page.TX, "R" to Page.SUCCES, "S" to Page.ALERTE, "A" to Page.TEXTE_2)

/** Heure du téléphone qui avance (âges affichés) ; la vue elle-même est relue par la session. */
@Composable
private fun rememberWallClock(stepMs: Long = 5_000): Long {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { delay(stepMs); now = System.currentTimeMillis() } }
    return now
}

private fun friendsView(rig: RigState, nowMs: Long): Friends.View? = Friends.ofState(rig.friends, nowMs)

@Composable
internal fun FriendDot(m: Friends.Member, size: Dp = 22.dp) {
    val fill = FR_COLORS[m.code]
    Box(
        Modifier.size(size).then(if (fill != null) Modifier.background(fill, CircleShape) else Modifier.border(2.dp, Page.TEXTE_2, CircleShape)),
        contentAlignment = Alignment.Center,
    ) { if (m.letter.isNotEmpty()) Text(m.letter, color = Page.FOND, fontWeight = FontWeight.Bold, fontSize = (size.value * 0.55f).sp) }
}

/** Bandeau discret de l'onglet Station : pastilles des amis actifs ; toucher = vue complète. */
@Composable
internal fun FriendsBanner(rig: RigState, onOpen: () -> Unit) {
    if (rig.friends == null) return
    val now = rememberWallClock()
    DisposableEffect(Unit) { RigHub.friendsWatch(true); onDispose { RigHub.friendsWatch(false) } }
    val b = Friends.badges(friendsView(rig, now), 8)
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onOpen).padding(horizontal = 4.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(Tr.t("friendsviews.friends"), style = MaterialTheme.typography.labelLarge, color = Page.TEXTE_2)
        for (m in b.list) FriendDot(m, 20.dp)
        Text(if (b.total == 0) Tr.t("friendsviews.none") else "${b.active}/${b.total}", style = MaterialTheme.typography.labelMedium, color = Page.TEXTE_2)
    }
}

/**
 * Bloc « Amis » : liste par groupe ou par membre, actions. `compact` : bloc de l'onglet Station (sans la gestion des
 * groupes). `canSet` : réglages du poste permis (réception, opérateur).
 */
@Composable
internal fun FriendsPanel(rig: RigState, canSet: Boolean, compact: Boolean, prefs: SharedPreferences) {
    val f = rig.friends ?: return
    val now = rememberWallClock()
    DisposableEffect(Unit) { RigHub.friendsWatch(true); onDispose { RigHub.friendsWatch(false) } }
    val view = friendsView(rig, now)
    var byMember by remember { mutableStateOf(prefs.getString(PREF_FRIENDS_BY, "group") == "member") }
    var block by remember { mutableStateOf(prefs.getBoolean(PREF_FRIENDS_BLOCK, false)) }
    var member by remember { mutableStateOf<Pair<Friends.Member, Friends.Group?>?>(null) }
    var share by remember { mutableStateOf<Friends.Group?>(null) }
    var leave by remember { mutableStateOf<Friends.Group?>(null) }
    var join by remember { mutableStateOf(false) }
    var create by remember { mutableStateOf(false) }
    var watch by remember { mutableStateOf(false) }
    var pseudo by remember(view?.pseudo) { mutableStateOf(view?.pseudo.orEmpty()) }

    Panel {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(Tr.t("friendsviews.friends"), style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
            if (f.back) CompactChip(Tr.t("friendsviews.back"), onClick = { RigHub.friendsBack() }, enabled = canSet)
            CompactChip(Tr.t("friendsviews.watch"), onClick = { watch = true })
            CompactChip("⟳", onClick = { RigHub.friendsRefresh() })
        }
        if (view != null) {
            val status = listOf(if (view.pseudo.isNotEmpty()) Tr.t("friendsviews.pseudo_is", "pseudo" to view.pseudo) else Tr.t("friendsviews.no_pseudo"),
                                if (view.registered) Tr.t("friendsviews.registered") else Tr.t("friendsviews.not_registered"),
                                view.problem?.let { Tr.t("friendsviews.problem", "problem" to it) }).filterNotNull().joinToString(" · ")
            Text(status, style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        } else Text(Tr.t("friendsviews.reading"), style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        if (f.notice.isNotEmpty()) Text(f.notice, style = MaterialTheme.typography.bodySmall, color = WARN,
                                        modifier = Modifier.clickable { RigHub.friendsDismiss() })
        Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            CompactChip(Tr.t("friendsviews.by_group"), onClick = { byMember = false; prefs.edit().putString(PREF_FRIENDS_BY, "group").apply() }, selected = !byMember)
            CompactChip(Tr.t("friendsviews.by_member"), onClick = { byMember = true; prefs.edit().putString(PREF_FRIENDS_BY, "member").apply() }, selected = byMember)
        }
        val groups = view?.groups.orEmpty()
        if (groups.isEmpty()) Text(Tr.t("friendsviews.no_groups"),
                                   style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        else if (byMember) {
            // Bloc de l'accueil : les amis JOIGNABLES seulement (demande de l'utilisateur, 2026-11-11)
            val shown = if (compact) view!!.members.filter { it.code != "O" } else view!!.members
            for (m in shown) FriendRow(m) { member = m to null }
            if (compact && shown.size < view.members.size) OfflineCount(view.members.size - shown.size)
            if (view.members.isEmpty()) Text(Tr.t("friendsviews.nobody_in_groups"), style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        } else for (g in groups) {
            HorizontalDivider(color = Page.LIGNE)
            Text(g.name + (if (g.role != "m") " · ${g.roleText}" else "") + (if (g.statusText.isNotEmpty()) " · ${g.statusText}" else ""),
                 style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
            if (!compact) FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                if (g.status == "member") CompactChip(Tr.t("friendsviews.share"), onClick = { share = g })
                if (g.admin && g.status == "member") {
                    CompactChip(Tr.t("friendsviews.invite"), onClick = { RigHub.friendsAction("invite", mapOf("g" to g.g, "days" to 7)) })
                    CompactChip(Tr.t("friendsviews.stats"), onClick = { RigHub.friendsAction("stats", mapOf("g" to g.g)) })
                }
                CompactChip(if (g.role == "a") Tr.t("friendsviews.leave_or_delete") else Tr.t("friendsviews.leave"), onClick = { leave = g })
            }
            val shown = if (compact) g.members.filter { it.code != "O" } else g.members
            for (m in shown) FriendRow(m) { member = m to g }
            if (compact && shown.size < g.members.size) OfflineCount(g.members.size - shown.size)
            if (g.members.isEmpty() && g.status == "member") Text(Tr.t("friendsviews.nobody_yet"), style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        }
        if (!compact) {
            HorizontalDivider(color = Page.LIGNE)
            Text(Tr.t("friendsviews.my_status"), style = MaterialTheme.typography.labelLarge)
            // Choix unique, le bouton en cours allumé, puis UNE phrase : ce que voient les amis (étapes 297 et 299)
            val choice = view?.me?.choice
            FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                CompactChip(Tr.t("friendsviews.automatic"), onClick = { RigHub.friendsAction("shack_cancel") }, selected = choice == "auto")
                CompactChip(Tr.t("friendsviews.shack_1h"), onClick = { RigHub.friendsAction("shack_for", mapOf("minutes" to 60)) }, selected = choice == "60")
                CompactChip(Tr.t("friendsviews.shack_2h"), onClick = { RigHub.friendsAction("shack_for", mapOf("minutes" to 120)) }, selected = choice == "120")
            }
            view?.me?.let { Text(it.text, style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2) }
            HorizontalDivider(color = Page.LIGNE)
            Text(Tr.t("friendsviews.pseudo_in_groups"), style = MaterialTheme.typography.labelLarge)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Box(Modifier.weight(1f)) { CompactField(pseudo, { pseudo = it.take(16) }, Tr.t("friendsviews.pseudo")) }
                TextButton(onClick = { Friends.cleanPseudo(pseudo)?.let { RigHub.friendsAction("pseudo", mapOf("pseudo" to it)) } },
                           enabled = Friends.cleanPseudo(pseudo) != null && Friends.cleanPseudo(pseudo) != view?.pseudo) { Text(Tr.t("friendsviews.save_pseudo")) }
            }
            HorizontalDivider(color = Page.LIGNE)
            Text(Tr.t("friendsviews.groups"), style = MaterialTheme.typography.labelLarge)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                CompactChip(Tr.t("friendsviews.create_group"), onClick = { create = true })
                CompactChip(Tr.t("friendsviews.join_invitation"), onClick = { join = true })
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(Tr.t("friendsviews.block_switch"),
                     style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                Switch(block, { block = it; prefs.edit().putBoolean(PREF_FRIENDS_BLOCK, it).apply() })
            }
            Text(Tr.t("friendsviews.relay_note"),
                 style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        }
    }

    member?.let { (m, g) -> MemberDialog(rig, m, g, canSet) { member = null } }
    share?.let { g -> ShareDialog(g, view?.texts.orEmpty()) { share = null } }
    leave?.let { g -> LeaveDialog(g) { leave = null } }
    if (join) JoinDialog { join = false }
    if (create) CreateDialog { create = false }
    f.invite?.let { (_, url) -> InviteDialog(url) }
    Friends.statsOf(f, view)?.let { (g, rows) -> StatsDialog(g, rows) }
    if (watch) ShackWatch(rig) { watch = false }
}

@Composable
private fun OfflineCount(n: Int) {
    Text(Tr.t("friendsviews.offline", "n" to n), style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
}

@Composable
private fun FriendRow(m: Friends.Member, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        FriendDot(m)
        Text(m.pseudo + (if (m.groups.size > 1) " (${m.groups.joinToString(", ")})" else ""), Modifier.weight(1f),
             maxLines = 1, overflow = TextOverflow.Ellipsis, color = if (m.code == "O") Page.TEXTE_2 else Page.TEXTE)
        Text(m.detail, style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2, maxLines = 1)
    }
}

@Composable
private fun MemberDialog(rig: RigState, m: Friends.Member, g: Friends.Group?, canSet: Boolean, onClose: () -> Unit) {
    val plan = Friends.qsyPlan(m, rig.state?.ptt?.state, rig.state?.rig?.frequencyHz)
    var confirmExclude by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text(m.pseudo + (g?.let { " · ${it.name}" } ?: "")) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("${m.label} · ${m.detail}")
                for (l in m.lines) Text(l, style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
                if (m.qsy) {
                    if (!plan.ok) Text(plan.text, color = WARN)
                    else {
                        Text(plan.text, fontWeight = FontWeight.SemiBold)
                        for (w in plan.warnings.filter { it.level != "info" }) Text(w.text, color = if (w.level == "strong") Page.TX else WARN)
                    }
                }
                if (g != null && g.admin && g.status == "member" && m.role != "a") {
                    HorizontalDivider(color = Page.LIGNE)
                    TextButton(onClick = {
                        RigHub.friendsAction("role", mapOf("g" to g.g, "member" to m.id, "role" to if (m.role == "c") "m" else "c")); onClose()
                    }) { Text(if (m.role == "c") Tr.t("friendsviews.remove_coadmin") else Tr.t("friendsviews.name_coadmin")) }
                    if (!confirmExclude) TextButton(onClick = { confirmExclude = true }) { Text(Tr.t("friendsviews.exclude_ask")) }
                    else {
                        Text(Tr.t("friendsviews.exclude_confirm", "pseudo" to m.pseudo), color = WARN)
                        TextButton(onClick = { RigHub.friendsAction("exclude", mapOf("g" to g.g, "member" to m.id)); onClose() }) { Text(Tr.t("friendsviews.exclude"), color = Page.TX) }
                    }
                }
            }
        },
        confirmButton = {
            if (m.qsy && plan.ok) TextButton(onClick = { RigHub.friendsQsy(plan.hz!!, plan.mode!!); onClose() }, enabled = canSet) {
                Text(Tr.t("friendsviews.go_to_frequency"))
            }
        },
        dismissButton = { TextButton(onClick = onClose) { Text(Tr.t("common.close")) } },
    )
}

@Composable
private fun LevelChips(level: String, onLevel: (String) -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
        for ((key, label) in Friends.LEVELS) CompactChip(label, onClick = { onLevel(key) }, selected = key == level)
    }
}

@Composable
private fun ShareDialog(g: Friends.Group, presets: List<String>, onClose: () -> Unit) {
    var level by remember { mutableStateOf(g.share.level) }
    var text by remember { mutableStateOf(g.share.text.orEmpty()) }
    var invisible by remember { mutableStateOf(g.share.invisible) }
    var hide by remember { mutableStateOf(g.share.hideAbsence) }
    val clean = Friends.cleanText(text)
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text(Tr.t("friendsviews.share_title", "name" to g.name)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                LevelChips(level) { level = it }
                if (level == "x") {
                    OutlinedTextField(text, { text = it.take(16) }, label = { Text(Tr.t("friendsviews.text_16")) }, singleLine = true,
                                      isError = clean == null)
                    if (presets.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                        for (p in presets) CompactChip(p, onClick = { text = p })
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(invisible, { invisible = it }); Text(Tr.t("friendsviews.invisible")) }
                Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(hide, { hide = it }); Text(Tr.t("friendsviews.hide_absence")) }
                Text(Tr.t("friendsviews.next_request"), style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                RigHub.friendsAction("share", mapOf("g" to g.g, "level" to level, "invisible" to invisible, "hide_absence" to hide,
                                                    "text" to if (level == "x") clean else null))
                onClose()
            }, enabled = level != "x" || clean != null) { Text(Tr.t("common.save")) }
        },
        dismissButton = { TextButton(onClick = onClose) { Text(Tr.t("common.cancel")) } },
    )
}

@Composable
private fun JoinDialog(onClose: () -> Unit) {
    var url by remember { mutableStateOf("") }
    var name by remember { mutableStateOf("") }
    var level by remember { mutableStateOf("o") }
    val link = Friends.cleanInvitation(url)
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text(Tr.t("friendsviews.join_title")) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(url, { url = it }, label = { Text(Tr.t("friendsviews.invitation_received")) }, minLines = 2)
                OutlinedTextField(name, { name = it.take(24) }, label = { Text(Tr.t("friendsviews.group_name_local")) }, singleLine = true)
                for (c in Friends.CONSENT) Text(c, style = MaterialTheme.typography.bodySmall)
                Text(Tr.t("friendsviews.i_share"), style = MaterialTheme.typography.labelLarge)
                LevelChips(level) { level = it }
            }
        },
        confirmButton = {
            TextButton(onClick = { RigHub.friendsJoin(link!!, name.trim(), level); onClose() }, enabled = link != null) { Text(Tr.t("friendsviews.accept_join")) }
        },
        dismissButton = { TextButton(onClick = onClose) { Text(Tr.t("common.cancel")) } },
    )
}

@Composable
private fun CreateDialog(onClose: () -> Unit) {
    var name by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text(Tr.t("friendsviews.create_group")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(name, { name = it.take(24) }, label = { Text(Tr.t("friendsviews.group_name")) }, singleLine = true)
                Text(Tr.t("friendsviews.create_note"), style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
            }
        },
        confirmButton = { TextButton(onClick = { RigHub.friendsAction("create", mapOf("name" to name.trim())); onClose() }, enabled = name.isNotBlank()) { Text(Tr.t("friendsviews.create")) } },
        dismissButton = { TextButton(onClick = onClose) { Text(Tr.t("common.cancel")) } },
    )
}

@Composable
private fun LeaveDialog(g: Friends.Group, onClose: () -> Unit) {
    var sure by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text(g.name) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(if (g.role == "a") Tr.t("friendsviews.leave_admin")
                     else Tr.t("friendsviews.leave_question"))
                if (g.role == "a") {
                    if (!sure) TextButton(onClick = { sure = true }) { Text(Tr.t("friendsviews.delete_all"), color = Page.TX) }
                    else TextButton(onClick = { RigHub.friendsAction("delete", mapOf("g" to g.g)); onClose() }) { Text(Tr.t("friendsviews.confirm_delete"), color = Page.TX) }
                }
            }
        },
        confirmButton = { TextButton(onClick = { RigHub.friendsAction("leave", mapOf("g" to g.g)); onClose() }) { Text(Tr.t("friendsviews.leave_group")) } },
        dismissButton = { TextButton(onClick = onClose) { Text(Tr.t("common.cancel")) } },
    )
}

@Composable
private fun InviteDialog(url: String) {
    val context = LocalContext.current
    AlertDialog(
        onDismissRequest = { RigHub.friendsDismiss() },
        title = { Text(Tr.t("friendsviews.invitation")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(Tr.t("friendsviews.invite_valid"))
                Text(url, style = MaterialTheme.typography.bodySmall)
                Text(Tr.t("friendsviews.invite_auto"),
                     style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, url)
                    .putExtra(Intent.EXTRA_SUBJECT, Tr.t("friendsviews.invite_subject"))
                context.startActivity(Intent.createChooser(send, Tr.t("friendsviews.send_invite")))
            }) { Text(Tr.t("common.share")) }
        },
        dismissButton = {
            Row {
                TextButton(onClick = {
                    (context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager)?.setPrimaryClip(ClipData.newPlainText(Tr.t("friendsviews.invitation"), url))
                }) { Text(Tr.t("common.copy")) }
                TextButton(onClick = { RigHub.friendsDismiss() }) { Text(Tr.t("common.close")) }
            }
        },
    )
}

@Composable
private fun StatsDialog(g: Friends.Group?, rows: List<Friends.StatsRow>) {
    AlertDialog(
        onDismissRequest = { RigHub.friendsDismiss() },
        title = { Text(Tr.t("friendsviews.stats") + (g?.let { " · ${it.name}" } ?: "")) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                if (rows.isEmpty()) Text(Tr.t("friendsviews.no_stats"))
                for (r in rows) Text(Tr.t("friendsviews.stats_row", "pseudo" to r.pseudo, "last_active" to r.lastActive, "days" to r.days, "qso_min" to r.qsoMin, "rx_min" to r.rxMin))
                Text(Tr.t("friendsviews.stats_note"),
                     style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
            }
        },
        confirmButton = { TextButton(onClick = { RigHub.friendsDismiss() }) { Text(Tr.t("common.close")) } },
    )
}

/**
 * Veille du shack : plein écran noir, gros caractères, luminosité basse, écran maintenu allumé tant qu'elle est
 * ouverte (posée sur son chargeur). Un toucher la ferme. N'agit sur rien : lecture seule.
 */
@Composable
private fun ShackWatch(rig: RigState, onClose: () -> Unit) {
    val now = rememberWallClock(5_000)
    val view = friendsView(rig, now)
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        val v = LocalView.current
        val activity = LocalContext.current as? Activity
        DisposableEffect(Unit) {
            v.keepScreenOn = true
            val window = activity?.window
            val before = window?.attributes?.screenBrightness ?: WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
            window?.let { w -> w.attributes = w.attributes.also { it.screenBrightness = 0.05f } }
            onDispose {
                v.keepScreenOn = false
                window?.let { w -> w.attributes = w.attributes.also { it.screenBrightness = before } }
            }
        }
        Box(Modifier.fillMaxSize().background(Color.Black).clickable(onClick = onClose).padding(24.dp)) {
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Text(Tr.t("friendsviews.friends"), color = Page.TEXTE_2, fontSize = 22.sp)
                val members = view?.members.orEmpty()
                if (members.isEmpty()) Text(Tr.t("friendsviews.nobody"), color = Page.TEXTE_2, fontSize = 26.sp)
                for (m in members.take(12)) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    FriendDot(m, 34.dp)
                    Column {
                        Text(m.pseudo, color = if (m.code == "O") Page.TEXTE_2 else Page.TEXTE, fontSize = 30.sp, fontWeight = FontWeight.SemiBold)
                        Text(m.detail, color = Page.TEXTE_2, fontSize = 20.sp)
                    }
                }
                Text(Tr.t("friendsviews.touch_to_close"), color = Page.TEXTE_2.copy(alpha = 0.5f), fontSize = 14.sp)
            }
        }
    }
}


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
        Text("Amis", style = MaterialTheme.typography.labelLarge, color = Page.TEXTE_2)
        for (m in b.list) FriendDot(m, 20.dp)
        Text(if (b.total == 0) "aucun" else "${b.active}/${b.total}", style = MaterialTheme.typography.labelMedium, color = Page.TEXTE_2)
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
            Text("Amis", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
            if (f.back) CompactChip("↩ Retour", onClick = { RigHub.friendsBack() }, enabled = canSet)
            CompactChip("Veille", onClick = { watch = true })
            CompactChip("⟳", onClick = { RigHub.friendsRefresh() })
        }
        if (view != null) {
            val status = listOf(if (view.pseudo.isNotEmpty()) "Pseudo ${view.pseudo}" else "Pas encore de pseudo",
                                if (view.registered) "enregistrée auprès du relais" else "pas encore enregistrée",
                                view.problem?.let { "problème : $it" }).filterNotNull().joinToString(" · ")
            Text(status, style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        } else Text("Lecture…", style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        if (f.notice.isNotEmpty()) Text(f.notice, style = MaterialTheme.typography.bodySmall, color = WARN,
                                        modifier = Modifier.clickable { RigHub.friendsDismiss() })
        Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            CompactChip("Par groupe", onClick = { byMember = false; prefs.edit().putString(PREF_FRIENDS_BY, "group").apply() }, selected = !byMember)
            CompactChip("Par membre", onClick = { byMember = true; prefs.edit().putString(PREF_FRIENDS_BY, "member").apply() }, selected = byMember)
        }
        val groups = view?.groups.orEmpty()
        if (groups.isEmpty()) Text("Aucun groupe : créez-en un, ou rejoignez celui d'un ami avec son invitation.",
                                   style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        else if (byMember) {
            for (m in view!!.members) FriendRow(m) { member = m to null }
            if (view.members.isEmpty()) Text("Personne d'autre dans vos groupes pour l'instant.", style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        } else for (g in groups) {
            HorizontalDivider(color = Page.LIGNE)
            Text(g.name + (if (g.role != "m") " · ${g.roleText}" else "") + (if (g.statusText.isNotEmpty()) " · ${g.statusText}" else ""),
                 style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
            if (!compact) FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                if (g.status == "member") CompactChip("Partage", onClick = { share = g })
                if (g.admin && g.status == "member") {
                    CompactChip("Inviter", onClick = { RigHub.friendsAction("invite", mapOf("g" to g.g, "days" to 7)) })
                    CompactChip("Statistiques", onClick = { RigHub.friendsAction("stats", mapOf("g" to g.g)) })
                }
                CompactChip(if (g.role == "a") "Quitter ou supprimer" else "Quitter", onClick = { leave = g })
            }
            for (m in g.members) FriendRow(m) { member = m to g }
            if (g.members.isEmpty() && g.status == "member") Text("Personne d'autre pour l'instant.", style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        }
        if (!compact) {
            HorizontalDivider(color = Page.LIGNE)
            Text("Mon statut", style = MaterialTheme.typography.labelLarge)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                CompactChip("Au shack 1 h", onClick = { RigHub.friendsAction("shack_for", mapOf("minutes" to 60)) })
                CompactChip("Au shack 2 h", onClick = { RigHub.friendsAction("shack_for", mapOf("minutes" to 120)) })
                CompactChip("Fin du « shack »", onClick = { RigHub.friendsAction("shack_cancel") })
            }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(pseudo, { pseudo = it.take(16) }, label = { Text("Pseudo") }, singleLine = true, modifier = Modifier.weight(1f))
                TextButton(onClick = { Friends.cleanPseudo(pseudo)?.let { RigHub.friendsAction("pseudo", mapOf("pseudo" to it)) } },
                           enabled = Friends.cleanPseudo(pseudo) != null) { Text("Enregistrer") }
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                CompactChip("Créer un groupe", onClick = { create = true })
                CompactChip("Rejoindre (invitation)", onClick = { join = true })
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Bloc « Amis » sur l'onglet Station (à la place du petit waterfall et des bandes)",
                     style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                Switch(block, { block = it; prefs.edit().putBoolean(PREF_FRIENDS_BLOCK, it).apply() })
            }
            Text("Le relais de présence ne voit que des états chiffrés ; un QSY vers un ami se fait en réception, après confirmation, jamais pendant une émission.",
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
                    }) { Text(if (m.role == "c") "Retirer co-administrateur" else "Nommer co-administrateur") }
                    if (!confirmExclude) TextButton(onClick = { confirmExclude = true }) { Text("Exclure du groupe…") }
                    else {
                        Text("Exclure ${m.pseudo} ? Une nouvelle clé est remise aux autres membres : ${m.pseudo} ne lira plus rien du groupe.", color = WARN)
                        TextButton(onClick = { RigHub.friendsAction("exclude", mapOf("g" to g.g, "member" to m.id)); onClose() }) { Text("Exclure", color = Page.TX) }
                    }
                }
            }
        },
        confirmButton = {
            if (m.qsy && plan.ok) TextButton(onClick = { RigHub.friendsQsy(plan.hz!!, plan.mode!!); onClose() }, enabled = canSet) {
                Text("Aller sur cette fréquence")
            }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("Fermer") } },
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
        title = { Text("Partage · ${g.name}") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                LevelChips(level) { level = it }
                if (level == "x") {
                    OutlinedTextField(text, { text = it.take(16) }, label = { Text("Texte (16 caractères)") }, singleLine = true,
                                      isError = clean == null)
                    if (presets.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                        for (p in presets) CompactChip(p, onClick = { text = p })
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(invisible, { invisible = it }); Text("Invisible dans ce groupe (les autres me voient hors ligne)") }
                Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(hide, { hide = it }); Text("Ne pas montrer depuis quand je suis absent") }
                Text("Pris à la prochaine requête de la station (moins de 2 minutes).", style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                RigHub.friendsAction("share", mapOf("g" to g.g, "level" to level, "invisible" to invisible, "hide_absence" to hide,
                                                    "text" to if (level == "x") clean else null))
                onClose()
            }, enabled = level != "x" || clean != null) { Text("Enregistrer") }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("Annuler") } },
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
        title = { Text("Rejoindre un groupe") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(url, { url = it }, label = { Text("Invitation reçue") }, minLines = 2)
                OutlinedTextField(name, { name = it.take(24) }, label = { Text("Nom du groupe chez moi (facultatif)") }, singleLine = true)
                for (c in Friends.CONSENT) Text(c, style = MaterialTheme.typography.bodySmall)
                Text("Je partage", style = MaterialTheme.typography.labelLarge)
                LevelChips(level) { level = it }
            }
        },
        confirmButton = {
            TextButton(onClick = { RigHub.friendsJoin(link!!, name.trim(), level); onClose() }, enabled = link != null) { Text("J'accepte et je rejoins") }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("Annuler") } },
    )
}

@Composable
private fun CreateDialog(onClose: () -> Unit) {
    var name by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("Créer un groupe") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(name, { name = it.take(24) }, label = { Text("Nom du groupe") }, singleLine = true)
                Text("Vous en serez l'administrateur ; invitez ensuite vos amis (« Inviter »).", style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
            }
        },
        confirmButton = { TextButton(onClick = { RigHub.friendsAction("create", mapOf("name" to name.trim())); onClose() }, enabled = name.isNotBlank()) { Text("Créer") } },
        dismissButton = { TextButton(onClick = onClose) { Text("Annuler") } },
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
                Text(if (g.role == "a") "Vous êtes administrateur : supprimer le groupe pour tout le monde, ou seulement le quitter ?"
                     else "Quitter ce groupe ? Il faudra une nouvelle invitation pour y revenir.")
                if (g.role == "a") {
                    if (!sure) TextButton(onClick = { sure = true }) { Text("Supprimer pour tous…", color = Page.TX) }
                    else TextButton(onClick = { RigHub.friendsAction("delete", mapOf("g" to g.g)); onClose() }) { Text("Confirmer la suppression", color = Page.TX) }
                }
            }
        },
        confirmButton = { TextButton(onClick = { RigHub.friendsAction("leave", mapOf("g" to g.g)); onClose() }) { Text("Quitter le groupe") } },
        dismissButton = { TextButton(onClick = onClose) { Text("Annuler") } },
    )
}

@Composable
private fun InviteDialog(url: String) {
    val context = LocalContext.current
    AlertDialog(
        onDismissRequest = { RigHub.friendsDismiss() },
        title = { Text("Invitation") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Valable 7 jours, pour UNE seule station. Elle contient la clé du groupe : à transmettre seulement à la personne invitée.")
                Text(url, style = MaterialTheme.typography.bodySmall)
                Text("Son adhésion sera validée automatiquement par votre station. QR code : TRX Console, menu 24.",
                     style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, url)
                    .putExtra(Intent.EXTRA_SUBJECT, "Invitation openRemoteTRX")
                context.startActivity(Intent.createChooser(send, "Envoyer l'invitation"))
            }) { Text("Partager") }
        },
        dismissButton = {
            Row {
                TextButton(onClick = {
                    (context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager)?.setPrimaryClip(ClipData.newPlainText("Invitation", url))
                }) { Text("Copier") }
                TextButton(onClick = { RigHub.friendsDismiss() }) { Text("Fermer") }
            }
        },
    )
}

@Composable
private fun StatsDialog(g: Friends.Group?, rows: List<Friends.StatsRow>) {
    AlertDialog(
        onDismissRequest = { RigHub.friendsDismiss() },
        title = { Text("Statistiques" + (g?.let { " · ${it.name}" } ?: "")) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                if (rows.isEmpty()) Text("Pas encore de statistiques : elles se remplissent pendant que votre station est en marche.")
                for (r in rows) Text("${r.pseudo} : dernier jour actif ${r.lastActive}, ${r.days} jour(s) actif(s) ce mois ; cette semaine QSO ${r.qsoMin} min, RX ${r.rxMin} min")
                Text("Agrégées par jour, 6 mois au plus, calculées sur votre station ; les heures où elle était éteinte ne sont pas comptées.",
                     style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
            }
        },
        confirmButton = { TextButton(onClick = { RigHub.friendsDismiss() }) { Text("Fermer") } },
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
                Text("Amis", color = Page.TEXTE_2, fontSize = 22.sp)
                val members = view?.members.orEmpty()
                if (members.isEmpty()) Text("Personne pour l'instant.", color = Page.TEXTE_2, fontSize = 26.sp)
                for (m in members.take(12)) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    FriendDot(m, 34.dp)
                    Column {
                        Text(m.pseudo, color = if (m.code == "O") Page.TEXTE_2 else Page.TEXTE, fontSize = 30.sp, fontWeight = FontWeight.SemiBold)
                        Text(m.detail, color = Page.TEXTE_2, fontSize = 20.sp)
                    }
                }
                Text("Toucher pour fermer", color = Page.TEXTE_2.copy(alpha = 0.5f), fontSize = 14.sp)
            }
        }
    }
}


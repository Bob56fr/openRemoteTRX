// SPDX-License-Identifier: AGPL-3.0-or-later WITH AdditionRef-RF-DIY-SDRplay-linking-exception
// Copyright (C) 2026 RF-DIY.COM
//
// EXCEPTION DE LIAISON (article 7 de la GNU AGPL v3, accordée par le titulaire des droits, 2026-11-15) :
// RF-DIY.COM vous accorde en plus la permission de lier ce programme à la bibliothèque PROPRIÉTAIRE de l'API
// SDRplay (libsdrplay_api.so / sdrplay_api.dll, fournie et installée séparément par l'utilisateur) et de
// distribuer le résultat, sans que les conditions de l'AGPL s'appliquent à cette bibliothèque. Ce programme
// reste sous AGPL-3.0-or-later. Linking exception: RF-DIY.COM additionally permits linking this program with
// the proprietary SDRplay API library and distributing the result; the AGPL does not apply to that library.
//
// sdr-core : cœur natif du module SDR d'openRemoteTRX (docs/sdr-cahier-des-charges.md, lot S1a).
// - ouvre UN SDR désigné par son NUMÉRO DE SÉRIE (jamais « le premier trouvé », jamais un autre appareil) ;
// - calcule le waterfall (FFT liquid-dsp, moyenne, max par groupe de cases) et l'écrit sur la sortie standard
//   en trames binaires (format : docs/protocole.md § 18 et trxstation/sdr/frames.py) ;
// - lit des commandes texte sur l'entrée standard : « freq HZ », « gain LNA GR », « rate N », « quit ».
// Mode d'essai sans matériel : --iq-file FICHIER (IQ int16 entrelacés, rejoué en boucle au rythme réel).
// Compilation sans l'API SDRplay (essais) : -DSDR_NO_SDRPLAY.
// Clés RTL-SDR (étape 197) : -DSDR_RTLSDR -lrtlsdr (librtlsdr d'osmocom, GPL-2.0+ : compatible AGPL, sans exception
// de liaison) ; choix du pilote à l'exécution par --driver sdrplay|rtlsdr.
#include <complex.h>
#include <errno.h>
#include <math.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <liquid/liquid.h>
#ifndef SDR_NO_SDRPLAY
#include <sdrplay_api.h>
#endif
#ifdef SDR_RTLSDR
#include <rtl-sdr.h>
#endif

#define CORE_VERSION "1.0"
#define FRAME_MAGIC "ORS1"
#define FRAME_LINE 1
#define FRAME_JSON 2
#define FRAME_AUDIO 3         // son démodulé : 960 échantillons int16 à 48 kHz (20 ms)
#define AUDIO_RATE 48000
#define AUDIO_BLOCK 960
#define DB_MIN (-150.0f)      // dBFS de la valeur 0 d'une case
#define DB_STEP (0.5f)        // dB par pas (255 = -22,5 dBFS)
#define RING_BITS 21          // 2 097 152 échantillons complexes en attente au plus
#define RING_SIZE (1u << RING_BITS)
#define MAX_FFT_PER_LINE 64

// ---------------------------------------------------------------- réglages
static double g_fs = 2e6, g_freq = 7.1e6;
static int g_bw = 1536, g_lna = 2, g_gr = 50, g_fft = 4096, g_bins = 1024;
static double g_rate = 8.0;
static int g_zoom = 1;                  // zoom du waterfall : 1, 2, 4, 8 ou 16 (étape 200)
static double g_zoom_off = 0;           // centre de la fenêtre zoomée par rapport au centre du SDR (Hz)
static char g_ant = 'A';
static int g_agc = 1;                   // AGC matériel de la FI (consigne AGC_SETPOINT_DBFS) : le SDR règle la réduction
#define AGC_SETPOINT_DBFS (-30)
static volatile int g_gr_now = -1;      // réduction de gain FI réellement appliquée (événement de l'API), -1 = inconnue
static volatile double g_gain_db = 0;   // gain total du récepteur selon l'API (dB)
static const char *g_serial = NULL, *g_iq_file = NULL;
static int g_driver = 0;                // 0 = SDRplay, 1 = RTL-SDR (--driver)

// ---------------------------------------------------------------- état partagé
static volatile sig_atomic_t g_stop = 0;
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_cond = PTHREAD_COND_INITIALIZER;
static pthread_mutex_t g_out = PTHREAD_MUTEX_INITIALIZER;
static int16_t *g_ring;                 // I,Q entrelacés
static uint64_t g_head = 0, g_tail = 0; // écrit / lu (en échantillons complexes)
static uint64_t g_samples = 0, g_drops = 0, g_gaps = 0;
static int g_overload = 0;

static void on_signal(int s) { (void)s; g_stop = 1; }   // rien d'autre ici : seul g_stop est sûr dans un signal

static double now_s(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec / 1e9; }

// ---------------------------------------------------------------- sortie en trames
static int write_frame(uint32_t type, const void *a, uint32_t na, const void *b, uint32_t nb) {
    uint8_t head[12];
    uint32_t len = na + nb;
    memcpy(head, FRAME_MAGIC, 4);
    memcpy(head + 4, &type, 4);             // petit-boutiste sur x86 / ARM : vérifié par frames.py (vecteurs)
    memcpy(head + 8, &len, 4);
    pthread_mutex_lock(&g_out);
    int ok = fwrite(head, 1, 12, stdout) == 12 && (na == 0 || fwrite(a, 1, na, stdout) == na)
             && (nb == 0 || fwrite(b, 1, nb, stdout) == nb) && fflush(stdout) == 0;
    pthread_mutex_unlock(&g_out);
    if (!ok) g_stop = 1;                    // module parti : on s'arrête
    return ok;
}

static void json_frame(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void json_frame(const char *fmt, ...) {
    char buf[1024];
    va_list ap; va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    if (n > 0) write_frame(FRAME_JSON, buf, (uint32_t)(n < (int)sizeof buf ? n : (int)sizeof buf - 1), NULL, 0);
}

static void fatal(int code, const char *kind, const char *detail) {
    json_frame("{\"t\":\"error\",\"code\":\"%s\",\"detail\":\"%s\"}", kind, detail ? detail : "");
    exit(code);
}

// ---------------------------------------------------------------- anneau d'échantillons
static void ring_push(const int16_t *xi, const int16_t *xq, unsigned int n) {
    pthread_mutex_lock(&g_lock);
    if (g_head - g_tail + n > RING_SIZE) {      // traitement en retard : on jette ce bloc (compté)
        g_drops += n;
    } else {
        for (unsigned int i = 0; i < n; i++) {
            uint64_t k = (g_head + i) & (RING_SIZE - 1);
            g_ring[2 * k] = xi ? xi[i] : 0;
            g_ring[2 * k + 1] = xq ? xq[i] : 0;
        }
        g_head += n;
    }
    g_samples += n;
    pthread_cond_signal(&g_cond);
    pthread_mutex_unlock(&g_lock);
}

// ---------------------------------------------------------------- démodulation d'UN canal (lot S1b)
// Chaîne : NCO (canal ramené près de 0) -> rééchantillonnage vers 48 kHz -> filtre de canal (passe-bande complexe par
// décalage, passe-bas, décalage inverse) -> squelch (puissance du canal au-dessus du bruit estimé) -> AGC (sauf FM) ->
// démodulation (AM : enveloppe ; FM : discriminateur ; BLU / CW : partie réelle) -> int16, blocs de 20 ms.
// AGC (étape 191) : l'AGC de liquid-dsp ramène le signal à une énergie UNITÉ (set_signal_level n'est que son
// estimation de départ) : le son sortait écrêté. AGC propre : enveloppe à attaque de 2 ms et retombée de 0,5 s,
// crête ramenée à AGC_PEAK (environ -20 dBFS efficaces), gain plafonné (bruit seul pas gonflé sans fin).
#define AGC_PEAK 0.25f
#define AGC_FLOOR 1e-5f
enum { M_AM = 0, M_NFM, M_USB, M_LSB, M_CW };
static const char *MODE_NAMES[] = { "AM", "NFM", "USB", "LSB", "CW" };
#define CW_TONE_HZ 700.0
static pthread_mutex_t g_dlock = PTHREAD_MUTEX_INITIALIZER;
static int g_audio = 0;                  // démodulation demandée (quelqu'un écoute)
static double g_dfreq = -1;              // fréquence écoutée (Hz) ; -1 = le centre
static int g_mode = M_USB, g_dbw = 2700; // mode et largeur du filtre (Hz)
static double g_sql = 0;                 // seuil du squelch en dB au-dessus du bruit ; 0 = toujours ouvert
static int g_dirty = 1;                  // réglages changés : chaîne refaite par le fil principal
static volatile int g_sql_open = 1;
static volatile double g_chan_db = -200, g_noise_db = -200;

static struct {
    int ready;
    nco_crcf nco, shift, unshift;            // shift et unshift avancent ensemble (phase cohérente)
    msresamp_crcf rs;
    firfilt_crcf lpf;
    freqdem fm;
    double center_shift;                 // décalage du passe-bande (Hz) à 48 kHz
    int mode;
    float complex *x, *y, *z;            // tampons
    unsigned int cap;
    int16_t out[AUDIO_BLOCK];
    unsigned int nout;
    float dc;                            // AM : suppression de la composante continue
    float env;                           // AGC : enveloppe suivie (attaque rapide, retombée lente)
    double hang;                         // squelch : maintien après la fermeture
} D;

static int mode_of(const char *name) {
    for (int i = 0; i < 5; i++) if (!strcmp(name, MODE_NAMES[i])) return i;
    return -1;
}

static void demod_free(void) {
    if (!D.ready) return;
    nco_crcf_destroy(D.nco); nco_crcf_destroy(D.shift); nco_crcf_destroy(D.unshift); msresamp_crcf_destroy(D.rs);
    firfilt_crcf_destroy(D.lpf); freqdem_destroy(D.fm);
    D.ready = 0;
}

static void demod_build(void) {
    /* Refait la chaîne d'après les réglages (fil principal seulement). */
    pthread_mutex_lock(&g_dlock);
    double dfreq = g_dfreq; int mode = g_mode, bw = g_dbw;
    g_dirty = 0;
    pthread_mutex_unlock(&g_dlock);
    demod_free();
    double tone = mode == M_CW ? CW_TONE_HZ : 0.0;               // CW : porteuse entendue à 700 Hz
    double off = dfreq - g_freq - tone;
    D.nco = nco_crcf_create(LIQUID_NCO);
    nco_crcf_set_frequency(D.nco, (float)(2.0 * M_PI * off / g_fs));
    D.rs = msresamp_crcf_create((float)(AUDIO_RATE / g_fs), 60.0f);
    double lo, hi;                                               // passe-bande du canal à 48 kHz (Hz)
    switch (mode) {
    case M_USB: lo = 300; hi = bw; break;
    case M_LSB: lo = -bw; hi = -300; break;
    case M_CW:  lo = CW_TONE_HZ - bw / 2.0; hi = CW_TONE_HZ + bw / 2.0; break;
    default:    lo = -bw / 2.0; hi = bw / 2.0; break;           // AM, FM
    }
    D.center_shift = (lo + hi) / 2.0;
    float fc = (float)((hi - lo) / 2.0 / AUDIO_RATE);
    D.lpf = firfilt_crcf_create_kaiser(129, fc < 0.49f ? fc : 0.49f, 60.0f, 0.0f);
    D.shift = nco_crcf_create(LIQUID_NCO);
    nco_crcf_set_frequency(D.shift, (float)(2.0 * M_PI * D.center_shift / AUDIO_RATE));
    D.unshift = nco_crcf_create(LIQUID_NCO);
    nco_crcf_set_frequency(D.unshift, (float)(2.0 * M_PI * D.center_shift / AUDIO_RATE));
    D.fm = freqdem_create((float)(bw / 2.0 / AUDIO_RATE));
    D.mode = mode; D.dc = 0; D.nout = 0; D.hang = 0; D.env = 0;
    D.ready = 1;
}

static void demod_feed(const float complex *raw, unsigned int n) {
    /* n échantillons bruts du SDR -> son à 48 kHz, envoyé par blocs de 20 ms. */
    if (g_dirty || !D.ready) demod_build();
    unsigned int need = n + 64;
    if (D.cap < need) {
        free(D.x); free(D.y); free(D.z);
        D.x = malloc(sizeof(float complex) * need); D.y = malloc(sizeof(float complex) * need);
        D.z = malloc(sizeof(float complex) * need); D.cap = need;
    }
    nco_crcf_mix_block_down(D.nco, (float complex *)raw, D.x, n);
    unsigned int m = 0;
    msresamp_crcf_execute(D.rs, D.x, n, D.y, &m);
    if (!m) return;
    // filtre de canal : décalage vers 0, passe-bas, décalage inverse
    nco_crcf_mix_block_down(D.shift, D.y, D.z, m);
    firfilt_crcf_execute_block(D.lpf, D.z, m, D.z);
    double p = 0;
    for (unsigned int i = 0; i < m; i++) p += crealf(D.z[i]) * crealf(D.z[i]) + cimagf(D.z[i]) * cimagf(D.z[i]);
    double db = 10.0 * log10(p / m + 1e-30);                     // dBFS (entrée normalisée)
    g_chan_db = db;
    double dt = (double)m / AUDIO_RATE;
    if (g_noise_db < -190 || db < g_noise_db) g_noise_db = db;   // bruit : suit les creux tout de suite,
    else g_noise_db += 1.0 * dt;                                 // remonte lentement (1 dB/s)
    int open = g_sql_open;
    if (g_sql <= 0) open = 1;
    else if (db > g_noise_db + g_sql) { open = 1; D.hang = 0.3; }
    else if (db < g_noise_db + g_sql - 3.0) { D.hang -= dt; if (D.hang <= 0) open = 0; }
    if (open != g_sql_open) {
        g_sql_open = open;
        json_frame("{\"t\":\"event\",\"name\":\"squelch\",\"open\":%d}", open);
    }
    nco_crcf_mix_block_up(D.unshift, D.z, D.y, m);
    const float att = 1.0f - expf(-1.0f / (0.002f * AUDIO_RATE));
    const float rel = expf(-1.0f / (0.5f * AUDIO_RATE));
    for (unsigned int i = 0; i < m; i++) {
        float s;
        if (D.mode == M_NFM) {
            freqdem_demodulate(D.fm, D.y[i], &s);
            s *= 0.3f;
        } else {
            float mag = cabsf(D.y[i]);
            if (mag > D.env) D.env += att * (mag - D.env);
            else D.env *= rel;
            float g = AGC_PEAK / (D.env > AGC_FLOOR ? D.env : AGC_FLOOR);
            if (D.mode == M_AM) {
                float e = mag * g;
                D.dc += 0.001f * (e - D.dc);
                s = (e - D.dc) * 2.0f;           // porteuse ~AGC_PEAK : modulation à 100 % = ±AGC_PEAK, x2
            } else {
                s = crealf(D.y[i]) * g;
            }
        }
        if (!open) s = 0;
        s = s > 1.0f ? 1.0f : s < -1.0f ? -1.0f : s;
        D.out[D.nout++] = (int16_t)(s * 32000.0f);
        if (D.nout == AUDIO_BLOCK) {
            write_frame(FRAME_AUDIO, D.out, sizeof D.out, NULL, 0);
            D.nout = 0;
        }
    }
}

// ---------------------------------------------------------------- SDRplay
#ifndef SDR_NO_SDRPLAY
static sdrplay_api_DeviceT g_devs[8];
static sdrplay_api_DeviceT *g_dev = NULL;
static sdrplay_api_DeviceParamsT *g_params = NULL;
static unsigned int g_next_first = 0;
static int g_have_first = 0;

static void stream_cb(short *xi, short *xq, sdrplay_api_StreamCbParamsT *p, unsigned int n, unsigned int reset, void *ctx) {
    (void)reset; (void)ctx;
    if (g_have_first && p->firstSampleNum != g_next_first) g_gaps++;
    g_next_first = p->firstSampleNum + n; g_have_first = 1;
    ring_push(xi, xq, n);
}

static void event_cb(sdrplay_api_EventT id, sdrplay_api_TunerSelectT tuner, sdrplay_api_EventParamsT *p, void *ctx) {
    (void)ctx;
    if (id == sdrplay_api_GainChange) {
        g_gr_now = (int)p->gainParams.gRdB;
        g_gain_db = p->gainParams.currGain;
    } else if (id == sdrplay_api_PowerOverloadChange && g_dev) {
        g_overload = p->powerOverloadParams.powerOverloadChangeType == sdrplay_api_Overload_Detected;
        sdrplay_api_Update(g_dev->dev, tuner, sdrplay_api_Update_Ctrl_OverloadMsgAck, sdrplay_api_Update_Ext1_None);
        json_frame("{\"t\":\"event\",\"name\":\"overload\",\"on\":%d}", g_overload);
    } else if (id == sdrplay_api_DeviceRemoved) {
        json_frame("{\"t\":\"error\",\"code\":\"removed\",\"detail\":\"SDR débranché\"}");
        g_stop = 1;
        pthread_cond_broadcast(&g_cond);
    }
}

static int api_list(int *first, float *ver) {
    /* SDR SDRplay LIBRES (le service du fabricant ne propose pas ceux qu'une autre application tient). 0 = service
       injoignable. */
    if (sdrplay_api_Open() != sdrplay_api_Success) return 0;
    sdrplay_api_ApiVersion(ver);
    sdrplay_api_LockDeviceApi();
    unsigned int n = 0;
    sdrplay_api_GetDevices(g_devs, &n, 8);
    sdrplay_api_UnlockDeviceApi();
    for (unsigned int i = 0; i < n; i++) {
        printf("%s{\"serial\":\"%s\",\"hw\":%u,\"driver\":\"sdrplay\"}", *first ? "" : ",", g_devs[i].SerNo, g_devs[i].hwVer);
        *first = 0;
    }
    sdrplay_api_Close();
    return 1;
}

static void api_start(void) {
    float ver = 0;
    if (sdrplay_api_Open() != sdrplay_api_Success) fatal(4, "service", "service SDRplay injoignable (sdrplay.service)");
    sdrplay_api_ApiVersion(&ver);
    sdrplay_api_LockDeviceApi();
    unsigned int n = 0;
    sdrplay_api_GetDevices(g_devs, &n, 8);
    for (unsigned int i = 0; i < n; i++)
        if (!strcmp(g_devs[i].SerNo, g_serial)) g_dev = &g_devs[i];
    if (!g_dev) { sdrplay_api_UnlockDeviceApi(); sdrplay_api_Close(); fatal(3, "absent", g_serial); }
    if (sdrplay_api_SelectDevice(g_dev) != sdrplay_api_Success) {
        sdrplay_api_UnlockDeviceApi(); sdrplay_api_Close(); fatal(3, "busy", g_serial);
    }
    sdrplay_api_UnlockDeviceApi();
    sdrplay_api_GetDeviceParams(g_dev->dev, &g_params);
    g_params->devParams->fsFreq.fsHz = g_fs;
    sdrplay_api_RxChannelParamsT *ch = g_params->rxChannelA;
    ch->tunerParams.rfFreq.rfHz = g_freq;
    ch->tunerParams.bwType = (sdrplay_api_Bw_MHzT)g_bw;
    ch->tunerParams.ifType = sdrplay_api_IF_Zero;
    ch->tunerParams.gain.gRdB = g_gr;
    ch->tunerParams.gain.LNAstate = (unsigned char)g_lna;
    ch->ctrlParams.agc.enable = g_agc ? sdrplay_api_AGC_50HZ : sdrplay_api_AGC_DISABLE;
    ch->ctrlParams.agc.setPoint_dBfs = AGC_SETPOINT_DBFS;
    if (g_dev->hwVer == SDRPLAY_RSP2_ID)
        ch->rsp2TunerParams.antennaSel = g_ant == 'B' ? sdrplay_api_Rsp2_ANTENNA_B : sdrplay_api_Rsp2_ANTENNA_A;
    sdrplay_api_CallbackFnsT cb = { stream_cb, NULL, event_cb };
    sdrplay_api_ErrT e = sdrplay_api_Init(g_dev->dev, &cb, NULL);
    if (e != sdrplay_api_Success) {
        sdrplay_api_ReleaseDevice(g_dev); sdrplay_api_Close();
        fatal(5, "init", sdrplay_api_GetErrorString(e));
    }
    json_frame("{\"t\":\"started\",\"serial\":\"%s\",\"hw\":%u,\"api\":%.2f,\"core\":\"%s\"}", g_serial, g_dev->hwVer, ver, CORE_VERSION);
}

static void api_stop(void) {
    if (!g_dev) return;
    sdrplay_api_Uninit(g_dev->dev);
    sdrplay_api_ReleaseDevice(g_dev);
    sdrplay_api_Close();
    g_dev = NULL;
}

static void api_set_freq(double hz) {
    if (!g_dev) return;
    g_params->rxChannelA->tunerParams.rfFreq.rfHz = hz;
    sdrplay_api_Update(g_dev->dev, sdrplay_api_Tuner_A, sdrplay_api_Update_Tuner_Frf, sdrplay_api_Update_Ext1_None);
}

static void api_set_gain(int lna, int gr) {
    if (!g_dev) return;
    g_params->rxChannelA->tunerParams.gain.LNAstate = (unsigned char)lna;
    g_params->rxChannelA->tunerParams.gain.gRdB = gr;
    sdrplay_api_Update(g_dev->dev, sdrplay_api_Tuner_A, sdrplay_api_Update_Tuner_Gr, sdrplay_api_Update_Ext1_None);
}

static void api_set_agc(int on) {
    if (!g_dev) return;
    g_params->rxChannelA->ctrlParams.agc.enable = on ? sdrplay_api_AGC_50HZ : sdrplay_api_AGC_DISABLE;
    g_params->rxChannelA->ctrlParams.agc.setPoint_dBfs = AGC_SETPOINT_DBFS;
    sdrplay_api_Update(g_dev->dev, sdrplay_api_Tuner_A, sdrplay_api_Update_Ctrl_Agc, sdrplay_api_Update_Ext1_None);
    if (!on) api_set_gain(g_lna, g_gr);                // AGC coupé : la réduction choisie s'applique de nouveau
}
#endif

// ---------------------------------------------------------------- RTL-SDR (étape 197)
#ifdef SDR_RTLSDR
#define RTL_BUF_BYTES (16 * 16384)       // 131 072 échantillons complexes par tampon
static rtlsdr_dev_t *g_rtl = NULL;
static pthread_t g_rtl_thread;
static int g_rtl_running = 0;

static void rtl_cb(unsigned char *buf, uint32_t len, void *ctx) {
    (void)ctx;
    static int16_t xi[RTL_BUF_BYTES / 2], xq[RTL_BUF_BYTES / 2];
    unsigned int n = len / 2, clip = 0;
    if (n > RTL_BUF_BYTES / 2) n = RTL_BUF_BYTES / 2;
    for (unsigned int i = 0; i < n; i++) {
        unsigned char a = buf[2 * i], b = buf[2 * i + 1];
        clip += (a == 0 || a == 255) + (b == 0 || b == 255);
        xi[i] = (int16_t)(((int)a - 128) * 256 + 128);       // 8 bits non signés -> pleine échelle int16
        xq[i] = (int16_t)(((int)b - 128) * 256 + 128);
    }
    int over = clip * 1000u > n * 2u;                         // plus d'un pour mille écrêté : CAN saturé
    if (over != g_overload) {
        g_overload = over;
        json_frame("{\"t\":\"event\",\"name\":\"overload\",\"on\":%d}", over);
    }
    ring_push(xi, xq, n);
}

static void *rtl_thread(void *arg) {
    (void)arg;
    int r = rtlsdr_read_async(g_rtl, rtl_cb, NULL, 0, RTL_BUF_BYTES);
    if (!g_stop) {                                            // sortie non demandée : clé débranchée
        json_frame("{\"t\":\"error\",\"code\":\"removed\",\"detail\":\"clé RTL-SDR débranchée (%d)\"}", r);
        g_stop = 1;
        pthread_cond_broadcast(&g_cond);
    }
    return NULL;
}

static void rtl_apply_gain(void) {
    /* AGC = gain automatique du tuner ; sinon gain manuel : LNA 0 (gain maximal) à 8 (minimal), comme le RSP. */
    if (!g_rtl) return;
    if (g_agc) {
        rtlsdr_set_tuner_gain_mode(g_rtl, 0);
    } else {
        int gains[64], n = rtlsdr_get_tuner_gains(g_rtl, NULL);
        if (n > 64) n = 64;
        if (n > 0) {
            rtlsdr_get_tuner_gains(g_rtl, gains);
            int k = (n - 1) * (8 - (g_lna > 8 ? 8 : g_lna)) / 8;
            rtlsdr_set_tuner_gain_mode(g_rtl, 1);
            rtlsdr_set_tuner_gain(g_rtl, gains[k]);
        }
    }
    g_gain_db = rtlsdr_get_tuner_gain(g_rtl) / 10.0;
}

static void rtl_list(int *first) {
    uint32_t n = rtlsdr_get_device_count();
    for (uint32_t i = 0; i < n; i++) {
        char m[256] = "", p[256] = "", s[256] = "";
        rtlsdr_get_device_usb_strings(i, m, p, s);
        for (char *c = s; *c; c++) if (*c == '"' || *c == '\\' || (unsigned char)*c < 32) *c = '?';
        for (char *c = p; *c; c++) if (*c == '"' || *c == '\\' || (unsigned char)*c < 32) *c = '?';
        printf("%s{\"serial\":\"%s\",\"hw\":0,\"driver\":\"rtlsdr\",\"product\":\"%s\"}", *first ? "" : ",", s, p);
        *first = 0;
    }
}

static void rtl_start(void) {
    uint32_t n = rtlsdr_get_device_count();
    int idx = -1, matches = 0, unreadable = 0;
    for (uint32_t i = 0; i < n; i++) {
        char m[256] = "", p[256] = "", s[256] = "";
        if (rtlsdr_get_device_usb_strings(i, m, p, s) != 0) { unreadable++; continue; }   // droits USB insuffisants
        if (!strcmp(s, g_serial)) { idx = (int)i; matches++; }
    }
    if (!matches && unreadable) fatal(3, "access", "clé RTL-SDR illisible par le compte de la station : droits USB (règle udev de l'installation)");
    if (!matches) fatal(3, "absent", g_serial);
    if (matches > 1) fatal(3, "duplicate", "numéro de série en double : clé impossible à désigner");
    if (rtlsdr_open(&g_rtl, (uint32_t)idx) < 0) { g_rtl = NULL; fatal(3, "busy", g_serial); }
    if (rtlsdr_set_sample_rate(g_rtl, (uint32_t)g_fs) < 0) { rtlsdr_close(g_rtl); g_rtl = NULL; fatal(5, "init", "fréquence d'échantillonnage refusée"); }
    rtlsdr_set_center_freq(g_rtl, (uint32_t)g_freq);
    rtlsdr_set_tuner_bandwidth(g_rtl, 0);                      // largeur automatique
    rtl_apply_gain();
    rtlsdr_reset_buffer(g_rtl);
    g_rtl_running = pthread_create(&g_rtl_thread, NULL, rtl_thread, NULL) == 0;
    json_frame("{\"t\":\"started\",\"serial\":\"%s\",\"hw\":%d,\"api\":null,\"driver\":\"rtlsdr\",\"core\":\"%s\"}",
               g_serial, (int)rtlsdr_get_tuner_type(g_rtl), CORE_VERSION);
}

static void rtl_stop(void) {
    if (!g_rtl) return;
    rtlsdr_cancel_async(g_rtl);
    if (g_rtl_running) pthread_join(g_rtl_thread, NULL);
    rtlsdr_close(g_rtl);
    g_rtl = NULL;
}
#endif

// ---------------------------------------------------------------- aiguillage vers le pilote choisi (--driver)
static void drv_set_freq(double hz) {
#ifndef SDR_NO_SDRPLAY
    if (g_driver == 0) api_set_freq(hz);
#endif
#ifdef SDR_RTLSDR
    if (g_driver == 1 && g_rtl) { rtlsdr_set_center_freq(g_rtl, (uint32_t)hz); }
#endif
    (void)hz;
}

static void drv_set_gain(int lna, int gr) {
#ifndef SDR_NO_SDRPLAY
    if (g_driver == 0) api_set_gain(lna, gr);
#endif
#ifdef SDR_RTLSDR
    if (g_driver == 1) rtl_apply_gain();
#endif
    (void)lna; (void)gr;
}

static void drv_set_agc(int on) {
#ifndef SDR_NO_SDRPLAY
    if (g_driver == 0) api_set_agc(on);
#endif
#ifdef SDR_RTLSDR
    if (g_driver == 1) rtl_apply_gain();
#endif
    (void)on;
}

// ---------------------------------------------------------------- source fichier (essais sans matériel)
static void *file_thread(void *arg) {
    (void)arg;
    FILE *f = fopen(g_iq_file, "rb");
    if (!f) { json_frame("{\"t\":\"error\",\"code\":\"file\",\"detail\":\"%s\"}", strerror(errno)); g_stop = 1; pthread_cond_broadcast(&g_cond); return NULL; }
    enum { CHUNK = 4096 };
    static int16_t raw[2 * CHUNK], xi[CHUNK], xq[CHUNK];
    double t0 = now_s(), sent = 0;
    while (!g_stop) {
        size_t n = fread(raw, 4, CHUNK, f);
        if (n == 0) { rewind(f); n = fread(raw, 4, CHUNK, f); if (n == 0) break; }
        for (size_t i = 0; i < n; i++) { xi[i] = raw[2 * i]; xq[i] = raw[2 * i + 1]; }
        ring_push(xi, xq, (unsigned int)n);
        sent += n;
        double ahead = sent / g_fs - (now_s() - t0);       // rythme réel : on attend sur l'horloge
        if (ahead > 0.002) { struct timespec ts = { (time_t)ahead, (long)((ahead - (time_t)ahead) * 1e9) }; nanosleep(&ts, NULL); }
    }
    fclose(f);
    return NULL;
}

// ---------------------------------------------------------------- commandes (entrée standard)
static void *command_thread(void *arg) {
    (void)arg;
    char line[256];
    while (!g_stop && fgets(line, sizeof line, stdin)) {
        double hz; int lna, gr; double rate;
        char mode[8]; int bw, on; double sql;
        if (sscanf(line, "freq %lf", &hz) == 1 && hz >= 1e3 && hz <= 2e9) {
            pthread_mutex_lock(&g_dlock);
            g_freq = hz; g_dirty = 1;                 // le canal écouté est repéré par rapport au centre
            pthread_mutex_unlock(&g_dlock);
            drv_set_freq(hz);
        } else if (sscanf(line, "demod %lf %7s %d", &hz, mode, &bw) == 3 && mode_of(mode) >= 0 && bw >= 100
                   && bw <= 15000 && fabs(hz - g_freq) <= g_fs / 2) {
            pthread_mutex_lock(&g_dlock);
            g_dfreq = hz; g_mode = mode_of(mode); g_dbw = bw; g_dirty = 1;
            pthread_mutex_unlock(&g_dlock);
        } else if (sscanf(line, "sql %lf", &sql) == 1 && sql >= 0 && sql <= 40) {
            g_sql = sql;
        } else if (sscanf(line, "audio %d", &on) == 1 && (on == 0 || on == 1)) {
            g_audio = on;
        } else if (sscanf(line, "gain %d %d", &lna, &gr) == 2 && lna >= 0 && lna <= 9 && gr >= 20 && gr <= 59) {
            g_lna = lna; g_gr = gr;
            drv_set_gain(lna, gr);
        } else if (sscanf(line, "agc %d", &lna) == 1 && (lna == 0 || lna == 1)) {
            g_agc = lna;
            drv_set_agc(lna);
        } else if (sscanf(line, "zoom %d %lf", &on, &hz) == 2 && (on == 1 || on == 2 || on == 4 || on == 8 || on == 16)
                   && fabs(hz) <= g_fs / 2) {
            g_zoom = on; g_zoom_off = hz;
        } else if (sscanf(line, "rate %lf", &rate) == 1 && rate >= 1 && rate <= 25) {
            g_rate = rate;
        } else if (!strncmp(line, "quit", 4)) {
            break;
        } else {
            json_frame("{\"t\":\"event\",\"name\":\"refused\",\"detail\":\"commande inconnue ou hors limites\"}");
        }
    }
    g_stop = 1;                                  // entrée fermée (module parti) ou « quit » : arrêt propre
    pthread_cond_broadcast(&g_cond);
    return NULL;
}

// ---------------------------------------------------------------- arguments
static int is_pow2(int v) { return v > 0 && (v & (v - 1)) == 0; }

static int parse_args(int argc, char **argv, int *list) {
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i], *v = i + 1 < argc ? argv[i + 1] : NULL;
        if (!strcmp(a, "--list")) { *list = 1; continue; }
        if (!strcmp(a, "--version")) { printf("sdr-core %s\n", CORE_VERSION); exit(0); }
        if (!v) { fprintf(stderr, "argument sans valeur : %s\n", a); return 0; }
        i++;
        if (!strcmp(a, "--serial")) g_serial = v;
        else if (!strcmp(a, "--iq-file")) g_iq_file = v;
        else if (!strcmp(a, "--fs")) g_fs = atof(v);
        else if (!strcmp(a, "--freq")) g_freq = atof(v);
        else if (!strcmp(a, "--bw")) g_bw = atoi(v);
        else if (!strcmp(a, "--lna")) g_lna = atoi(v);
        else if (!strcmp(a, "--gr")) g_gr = atoi(v);
        else if (!strcmp(a, "--ant")) g_ant = v[0];
        else if (!strcmp(a, "--fft")) g_fft = atoi(v);
        else if (!strcmp(a, "--bins")) g_bins = atoi(v);
        else if (!strcmp(a, "--rate")) g_rate = atof(v);
        else if (!strcmp(a, "--zoom")) g_zoom = atoi(v);
        else if (!strcmp(a, "--zoom-off")) g_zoom_off = atof(v);
        else if (!strcmp(a, "--agc")) g_agc = atoi(v);
        else if (!strcmp(a, "--dfreq")) g_dfreq = atof(v);
        else if (!strcmp(a, "--mode")) g_mode = mode_of(v);
        else if (!strcmp(a, "--dbw")) g_dbw = atoi(v);
        else if (!strcmp(a, "--sql")) g_sql = atof(v);
        else if (!strcmp(a, "--driver")) {
            if (!strcmp(v, "sdrplay")) g_driver = 0;
            else if (!strcmp(v, "rtlsdr")) g_driver = 1;
            else { fprintf(stderr, "pilote inconnu : %s\n", v); return 0; }
        }
        else { fprintf(stderr, "argument inconnu : %s\n", a); return 0; }
    }
    if (*list) return 1;
    if (g_dfreq < 0) g_dfreq = g_freq;
    if (!g_serial && !g_iq_file) { fprintf(stderr, "--serial (ou --iq-file) obligatoire\n"); return 0; }
    if (g_fs < 2e5 || g_fs > 10e6 || g_freq < 1e3 || g_freq > 2e9 || g_lna < 0 || g_lna > 9 || g_gr < 20 || g_gr > 59
        || !is_pow2(g_fft) || g_fft < 512 || g_fft > 16384 || !is_pow2(g_bins) || g_bins < 128 || g_bins > g_fft
        || g_rate < 1 || g_rate > 25 || (g_ant != 'A' && g_ant != 'B') || (g_agc != 0 && g_agc != 1)
        || g_mode < 0 || g_dbw < 100 || g_dbw > 15000 || g_sql < 0 || g_sql > 40 || fabs(g_dfreq - g_freq) > g_fs / 2
        || (g_zoom != 1 && g_zoom != 2 && g_zoom != 4 && g_zoom != 8 && g_zoom != 16) || fabs(g_zoom_off) > g_fs / 2) {
        fprintf(stderr, "réglage hors limites\n");
        return 0;
    }
    return 1;
}

// ---------------------------------------------------------------- programme
int main(int argc, char **argv) {
    int list = 0;
    if (!parse_args(argc, argv, &list)) return 2;
    if (list) {
        int first = 1, service = 0;
        float ver = 0;
        (void)first;
        printf("{\"devices\":[");
#ifndef SDR_NO_SDRPLAY
        service = api_list(&first, &ver);
#endif
#ifdef SDR_RTLSDR
        rtl_list(&first);
#endif
        if (service) printf("],\"api\":%.2f}\n", ver);
#ifndef SDR_NO_SDRPLAY
        else printf("],\"api\":null,\"error\":\"service\"}\n");
#else
        else printf("],\"api\":null}\n");
#endif
        return 0;
    }
    signal(SIGINT, on_signal); signal(SIGTERM, on_signal); signal(SIGPIPE, SIG_IGN);
    g_ring = malloc(sizeof(int16_t) * 2 * RING_SIZE);
    if (!g_ring) fatal(6, "memory", "anneau");

    pthread_t src = 0, cmd;
    if (g_iq_file) {
        json_frame("{\"t\":\"started\",\"serial\":\"fichier\",\"hw\":0,\"api\":null,\"core\":\"%s\"}", CORE_VERSION);
        pthread_create(&src, NULL, file_thread, NULL);
    } else if (g_driver == 1) {
#ifdef SDR_RTLSDR
        rtl_start();
#else
        fatal(4, "service", "sdr-core compilé sans librtlsdr (clés RTL-SDR)");
#endif
    } else {
#ifndef SDR_NO_SDRPLAY
        api_start();
#else
        fatal(4, "service", "sdr-core compilé sans l'API SDRplay");
#endif
    }
    pthread_create(&cmd, NULL, command_thread, NULL);

    const int N = g_fft, B = g_bins, group = N / B;
    float complex *in = malloc(sizeof(float complex) * N), *out = malloc(sizeof(float complex) * N);
    float *win = malloc(sizeof(float) * N), *acc = calloc(N, sizeof(float));
    uint8_t *line = malloc(B);
    float complex *raw = malloc(sizeof(float complex) * N);
    fftplan plan = fft_create_plan(N, in, out, LIQUID_FFT_FORWARD, 0);
    double wsum = 0;
    for (int i = 0; i < N; i++) { win[i] = 0.5f - 0.5f * cosf(2.0f * (float)M_PI * i / (N - 1)); wsum += win[i]; }
    const float norm = (float)(1.0 / (wsum * wsum * 32768.0 * 32768.0));
    int nacc = 0;
    uint64_t consumed = 0, next_line_at = 0;
    double last_status = now_s();

    while (!g_stop) {
        pthread_mutex_lock(&g_lock);
        while (!g_stop && g_head - g_tail < (uint64_t)N) {      // attente bornée : un signal n'a pas à réveiller
            struct timespec until;
            clock_gettime(CLOCK_REALTIME, &until);
            until.tv_nsec += 200000000L;
            if (until.tv_nsec >= 1000000000L) { until.tv_sec++; until.tv_nsec -= 1000000000L; }
            pthread_cond_timedwait(&g_cond, &g_lock, &until);
        }
        uint64_t avail = g_head - g_tail;
        pthread_mutex_unlock(&g_lock);
        if (g_stop) break;
        uint64_t per_line = (uint64_t)(g_fs / g_rate);
        uint64_t ffts_line = per_line / (uint64_t)N, skip = ffts_line > MAX_FFT_PER_LINE ? ffts_line / MAX_FFT_PER_LINE : 1;
        while (avail >= (uint64_t)N && !g_stop) {
            if (((consumed / N) % skip) == 0) {
                for (int i = 0; i < N; i++) {
                    uint64_t k = (g_tail + i) & (RING_SIZE - 1);
                    in[i] = (g_ring[2 * k] + I * g_ring[2 * k + 1]) * win[i];
                }
                fft_execute(plan);
                for (int i = 0; i < N; i++) acc[i] += crealf(out[i]) * crealf(out[i]) + cimagf(out[i]) * cimagf(out[i]);
                nacc++;
            }
            if (g_audio) {                                    // son démodulé : TOUS les échantillons, pas une FFT sur n
                for (int i = 0; i < N; i++) {
                    uint64_t k = (g_tail + i) & (RING_SIZE - 1);
                    raw[i] = (g_ring[2 * k] + I * g_ring[2 * k + 1]) * (1.0f / 32768.0f);   // pleine échelle = 1
                }
                demod_feed(raw, (unsigned int)N);
            }
            pthread_mutex_lock(&g_lock);
            g_tail += N;
            pthread_mutex_unlock(&g_lock);
            avail -= N; consumed += N;
            if (consumed >= next_line_at && nacc > 0) {
                // ligne : case 0 = fréquence la plus basse (FFT recentrée), max sur chaque groupe de cases ;
                // zoom (étape 200) : la ligne ne couvre que N/zoom cases de la FFT, autour de centre + décalage
                int zoom = g_zoom, shown = N / zoom;
                long start = N / 2 + lround(g_zoom_off * N / g_fs) - shown / 2;      // en cases recentrées (0 = bas)
                if (start < 0) start = 0;
                if (start > N - shown) start = N - shown;
                for (int b = 0; b < B; b++) {
                    long c0 = start + (long)b * shown / B, c1 = start + (long)(b + 1) * shown / B;
                    if (c1 <= c0) c1 = c0 + 1;
                    float best = 0;
                    for (long c = c0; c < c1; c++) {
                        int k = (int)((c + N / 2) % N);
                        if (acc[k] > best) best = acc[k];
                    }
                    float db = 10.0f * log10f(best / nacc * norm + 1e-30f);
                    float q = (db - DB_MIN) / DB_STEP;
                    line[b] = q <= 0 ? 0 : q >= 255 ? 255 : (uint8_t)(q + 0.5f);
                }
                (void)group;
                double lcenter = g_freq + (start + shown / 2.0 - N / 2.0) * g_fs / N, lspan = g_fs / zoom;
                struct { double center, span; uint16_t bins, reserved; } __attribute__((packed)) h = { lcenter, lspan, (uint16_t)B, 0 };
                write_frame(FRAME_LINE, &h, sizeof h, line, (uint32_t)B);
                memset(acc, 0, sizeof(float) * N); nacc = 0;
                next_line_at = consumed + per_line;
            }
        }
        double t = now_s();
        if (t - last_status >= 1.0) {
            last_status = t;
            json_frame("{\"t\":\"status\",\"fs\":%.0f,\"freq\":%.0f,\"lna\":%d,\"gr\":%d,\"ant\":\"%c\",\"rate\":%.1f,"
                       "\"bins\":%d,\"agc\":%d,\"gr_now\":%d,\"gain_db\":%.1f,\"overload\":%d,\"samples\":%llu,"
                       "\"drops\":%llu,\"gaps\":%llu,\"audio\":%d,\"dfreq\":%.0f,\"mode\":\"%s\",\"dbw\":%d,"
                       "\"sql\":%.1f,\"sql_open\":%d,\"chan_db\":%.1f,\"noise_db\":%.1f,\"zoom\":%d}",
                       g_fs, g_freq, g_lna, g_gr, g_ant, g_rate, B, g_agc, g_gr_now, g_gain_db, g_overload,
                       (unsigned long long)g_samples, (unsigned long long)g_drops, (unsigned long long)g_gaps,
                       g_audio, g_dfreq, MODE_NAMES[g_mode], g_dbw, g_sql, g_sql_open,
                       g_audio ? g_chan_db : -200.0, g_audio ? g_noise_db : -200.0, g_zoom);
        }
    }
#ifndef SDR_NO_SDRPLAY
    api_stop();
#endif
#ifdef SDR_RTLSDR
    rtl_stop();
#endif
    if (src) pthread_join(src, NULL);
    json_frame("{\"t\":\"stopped\"}");
    fflush(stdout);
    _exit(0);       // pas exit() : il verrouille stdin, que le fil des commandes tient dans fgets (interblocage)
}

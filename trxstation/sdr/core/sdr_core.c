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

#define CORE_VERSION "1.0"
#define FRAME_MAGIC "ORS1"
#define FRAME_LINE 1
#define FRAME_JSON 2
#define DB_MIN (-150.0f)      // dBFS de la valeur 0 d'une case
#define DB_STEP (0.5f)        // dB par pas (255 = -22,5 dBFS)
#define RING_BITS 21          // 2 097 152 échantillons complexes en attente au plus
#define RING_SIZE (1u << RING_BITS)
#define MAX_FFT_PER_LINE 64

// ---------------------------------------------------------------- réglages
static double g_fs = 2e6, g_freq = 7.1e6;
static int g_bw = 1536, g_lna = 2, g_gr = 50, g_fft = 4096, g_bins = 1024;
static double g_rate = 8.0;
static char g_ant = 'A';
static int g_agc = 1;                   // AGC matériel de la FI (consigne AGC_SETPOINT_DBFS) : le SDR règle la réduction
#define AGC_SETPOINT_DBFS (-30)
static volatile int g_gr_now = -1;      // réduction de gain FI réellement appliquée (événement de l'API), -1 = inconnue
static volatile double g_gain_db = 0;   // gain total du récepteur selon l'API (dB)
static const char *g_serial = NULL, *g_iq_file = NULL;

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

static void api_list(void) {
    float ver = 0;
    if (sdrplay_api_Open() != sdrplay_api_Success) { printf("{\"api\":null,\"devices\":[],\"error\":\"service\"}\n"); exit(4); }
    sdrplay_api_ApiVersion(&ver);
    sdrplay_api_LockDeviceApi();
    unsigned int n = 0;
    sdrplay_api_GetDevices(g_devs, &n, 8);
    sdrplay_api_UnlockDeviceApi();
    printf("{\"api\":%.2f,\"devices\":[", ver);
    for (unsigned int i = 0; i < n; i++)
        printf("%s{\"serial\":\"%s\",\"hw\":%u}", i ? "," : "", g_devs[i].SerNo, g_devs[i].hwVer);
    printf("]}\n");
    sdrplay_api_Close();
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
        if (sscanf(line, "freq %lf", &hz) == 1 && hz >= 1e3 && hz <= 2e9) {
            g_freq = hz;
#ifndef SDR_NO_SDRPLAY
            api_set_freq(hz);
#endif
        } else if (sscanf(line, "gain %d %d", &lna, &gr) == 2 && lna >= 0 && lna <= 9 && gr >= 20 && gr <= 59) {
            g_lna = lna; g_gr = gr;
#ifndef SDR_NO_SDRPLAY
            api_set_gain(lna, gr);
#endif
        } else if (sscanf(line, "agc %d", &lna) == 1 && (lna == 0 || lna == 1)) {
            g_agc = lna;
#ifndef SDR_NO_SDRPLAY
            api_set_agc(lna);
#endif
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
        else if (!strcmp(a, "--agc")) g_agc = atoi(v);
        else { fprintf(stderr, "argument inconnu : %s\n", a); return 0; }
    }
    if (*list) return 1;
    if (!g_serial && !g_iq_file) { fprintf(stderr, "--serial (ou --iq-file) obligatoire\n"); return 0; }
    if (g_fs < 2e5 || g_fs > 10e6 || g_freq < 1e3 || g_freq > 2e9 || g_lna < 0 || g_lna > 9 || g_gr < 20 || g_gr > 59
        || !is_pow2(g_fft) || g_fft < 512 || g_fft > 16384 || !is_pow2(g_bins) || g_bins < 128 || g_bins > g_fft
        || g_rate < 1 || g_rate > 25 || (g_ant != 'A' && g_ant != 'B') || (g_agc != 0 && g_agc != 1)) {
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
#ifndef SDR_NO_SDRPLAY
        api_list();
#else
        printf("{\"api\":null,\"devices\":[],\"error\":\"sans API\"}\n");
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
            pthread_mutex_lock(&g_lock);
            g_tail += N;
            pthread_mutex_unlock(&g_lock);
            avail -= N; consumed += N;
            if (consumed >= next_line_at && nacc > 0) {
                // ligne : case 0 = fréquence la plus basse (FFT recentrée), max sur chaque groupe de cases
                for (int b = 0; b < B; b++) {
                    float best = 0;
                    for (int j = 0; j < group; j++) {
                        int k = (b * group + j + N / 2) % N;
                        if (acc[k] > best) best = acc[k];
                    }
                    float db = 10.0f * log10f(best / nacc * norm + 1e-30f);
                    float q = (db - DB_MIN) / DB_STEP;
                    line[b] = q <= 0 ? 0 : q >= 255 ? 255 : (uint8_t)(q + 0.5f);
                }
                struct { double center, span; uint16_t bins, reserved; } __attribute__((packed)) h = { g_freq, g_fs, (uint16_t)B, 0 };
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
                       "\"drops\":%llu,\"gaps\":%llu}",
                       g_fs, g_freq, g_lna, g_gr, g_ant, g_rate, B, g_agc, g_gr_now, g_gain_db, g_overload,
                       (unsigned long long)g_samples, (unsigned long long)g_drops, (unsigned long long)g_gaps);
        }
    }
#ifndef SDR_NO_SDRPLAY
    api_stop();
#endif
    if (src) pthread_join(src, NULL);
    json_frame("{\"t\":\"stopped\"}");
    fflush(stdout);
    _exit(0);       // pas exit() : il verrouille stdin, que le fil des commandes tient dans fgets (interblocage)
}

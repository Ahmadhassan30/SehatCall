/**
 * DAWA P1 — Caregiver Dashboard
 *
 * Shows Razia Bibi's medication schedule, a live call dispatch button,
 * an interactive VMR demo card, and a safety notice.
 */

import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  Modal,
  TextInput,
  Animated,
  ActivityIndicator,
  Alert,
  Platform,
  StatusBar,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useDawa, type Medication, type DoseEvent } from '@/context/DawaContext';

// ─── Colour tokens ────────────────────────────────────────────────────────────
const C = {
  green:      '#1B6B3A',
  greenLight: '#E8F5ED',
  greenMid:   '#2E8B57',
  orange:     '#D97706',
  orangeLight:'#FEF3C7',
  red:        '#DC2626',
  redLight:   '#FEE2E2',
  blue:       '#1D4ED8',
  blueLight:  '#DBEAFE',
  bg:         '#F4F6F3',
  card:       '#FFFFFF',
  border:     '#E4E9E6',
  textDark:   '#111827',
  textMid:    '#374151',
  textMuted:  '#6B7280',
  textLight:  '#9CA3AF',
  urdu:       '#1B3A5C',
};

// ─── Phase → display mapping ──────────────────────────────────────────────────
const PHASE_LABEL: Record<string, string> = {
  idle:        'No active call',
  dispatching: 'Connecting…',
  dispatched:  'Call dispatched',
  dialing:     'Dialing…',
  ringing:     'Ringing…',
  answered:    'Connected ✓',
  completed:   'Call ended',
  failed:      'Call failed',
};

const PHASE_COLOR: Record<string, string> = {
  idle:        C.textMuted,
  dispatching: C.orange,
  dispatched:  C.orange,
  dialing:     C.orange,
  ringing:     C.orange,
  answered:    C.green,
  completed:   C.textMid,
  failed:      C.red,
};

const ACTIVE_PHASES = new Set(['dispatching', 'dispatched', 'dialing', 'ringing', 'answered']);

// ─── Helpers ──────────────────────────────────────────────────────────────────
function formatScheduleTime(hhmm: string): string {
  const [hh, mm] = hhmm.split(':').map(Number);
  if (isNaN(hh)) return hhmm;
  const period = hh >= 12 ? 'PM' : 'AM';
  const h12 = hh % 12 || 12;
  return `${h12}:${String(mm ?? 0).padStart(2, '0')} ${period}`;
}

function getMedicationIcon(med: Medication): string {
  const time = parseInt(med.schedule_time?.split(':')[0] ?? '0', 10);
  if (time >= 5 && time < 12) return '🌅';
  if (time >= 12 && time < 17) return '☀️';
  if (time >= 17 && time < 20) return '🌇';
  return '🌙';
}

// ─── Pulsing dot ─────────────────────────────────────────────────────────────
function PulsingDot({ color }: { color: string }) {
  const scale = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(scale, { toValue: 1.5, duration: 700, useNativeDriver: true }),
        Animated.timing(scale, { toValue: 1,   duration: 700, useNativeDriver: true }),
      ])
    );
    anim.start();
    return () => anim.stop();
  }, [scale]);
  return (
    <Animated.View
      style={{
        width: 8, height: 8, borderRadius: 4,
        backgroundColor: color,
        transform: [{ scale }],
        marginRight: 6,
      }}
    />
  );
}

// ─── Main screen ─────────────────────────────────────────────────────────────
export default function DawaScreen() {
  const {
    apiBaseUrl, setApiBaseUrl,
    patient, medications, isLoading, loadError, refresh,
    vmrCues, addVmrCue, clearVmrCues, vmrResult, vmrLoading,
    callPhase, activeCallId, recentDoseEvents,
    dispatchCall, callError,
  } = useDawa();

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [urlDraft, setUrlDraft] = useState(apiBaseUrl);

  // Auto-open settings if no API URL is configured
  useEffect(() => {
    if (!apiBaseUrl) setSettingsOpen(true);
  }, []);

  // ── VMR demo logic ──────────────────────────────────────────────────────
  const [vmrBoxColor, setVmrBoxColor]     = useState<string | null>(null);
  const [vmrStripeColor, setVmrStripeColor] = useState<string | null>(null);

  function handleVmrBoxColor(color: string) {
    setVmrBoxColor(color);
    setVmrStripeColor(null);
    clearVmrCues();
    addVmrCue('package_color', color);
  }

  function handleVmrStripeColor(stripe: string) {
    setVmrStripeColor(stripe);
    if (vmrBoxColor) {
      clearVmrCues();
      addVmrCue('package_color', vmrBoxColor);
      addVmrCue('stripe_color', stripe);
    }
  }

  function resetVmr() {
    setVmrBoxColor(null);
    setVmrStripeColor(null);
    clearVmrCues();
  }

  // ── Dispatch handler ────────────────────────────────────────────────────
  function handleCallPress(med: Medication) {
    if (ACTIVE_PHASES.has(callPhase)) {
      Alert.alert('Call in progress', 'Wait for the current call to finish before placing another.');
      return;
    }
    Alert.alert(
      `Call Razia Bibi`,
      `Dispatch a call for "${med.nickname || med.clinical_name}"?\n\nShe will receive a call on the registered phone.`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Call Now', onPress: () => dispatchCall('razia-bibi', med.id) },
      ]
    );
  }

  const isActiveCall = ACTIVE_PHASES.has(callPhase);
  const phaseColor = PHASE_COLOR[callPhase] ?? C.textMuted;

  // ── VMR result display ──────────────────────────────────────────────────
  function renderVmrResult() {
    if (!vmrResult) return null;
    if (vmrResult.status === 'NO_MATCH') {
      return (
        <View style={[styles.vmrResultBox, { backgroundColor: C.redLight, borderColor: C.red }]}>
          <Text style={[styles.vmrResultTitle, { color: C.red }]}>⚠ NO_MATCH</Text>
          <Text style={styles.vmrResultBody}>
            These cues don't match any verified medication. Cannot identify.
          </Text>
        </View>
      );
    }
    if (vmrResult.status === 'AMBIGUOUS') {
      const disc = vmrResult.bestDiscriminator;
      return (
        <View style={[styles.vmrResultBox, { backgroundColor: C.orangeLight, borderColor: C.orange }]}>
          <Text style={[styles.vmrResultTitle, { color: C.orange }]}>⚡ AMBIGUOUS</Text>
          <Text style={styles.vmrResultBody}>
            Two white boxes — can't tell apart yet.
          </Text>
          {disc && (
            <Text style={[styles.vmrResultHint]}>
              💡 Ask about: <Text style={{ fontWeight: '700' }}>{disc.replace('_', ' ')}</Text>
              {disc === 'stripe_color' ? '\n  → Blue stripe = Metformin\n  → Red stripe = Amlodipine' : ''}
            </Text>
          )}
        </View>
      );
    }
    if (vmrResult.status === 'UNIQUE') {
      const med = medications.find(m => m.id === vmrResult.medicationId);
      return (
        <View style={[styles.vmrResultBox, { backgroundColor: C.greenLight, borderColor: C.green }]}>
          <Text style={[styles.vmrResultTitle, { color: C.green }]}>✓ UNIQUE — IDENTIFIED</Text>
          <Text style={styles.vmrResultBody}>
            {med?.nickname ?? vmrResult.medicationId}
          </Text>
          {med && (
            <Text style={styles.vmrResultSub}>
              {med.clinical_name} {med.dosage} · {med.dose_instruction}
            </Text>
          )}
        </View>
      );
    }
    return null;
  }

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar barStyle="light-content" backgroundColor={C.green} />

      {/* ── Header ── */}
      <View style={styles.header}>
        <View>
          <Text style={styles.headerTitle}>DAWA</Text>
          <Text style={styles.headerSubtitle}>ادویات ساتھی</Text>
        </View>
        <TouchableOpacity style={styles.gearBtn} onPress={() => { setUrlDraft(apiBaseUrl); setSettingsOpen(true); }}>
          <Text style={{ fontSize: 22 }}>⚙️</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent}>

        {/* ── Connection error ── */}
        {loadError && (
          <View style={[styles.card, styles.errorCard]}>
            <Text style={styles.errorTitle}>⚠ Cannot reach DAWA backend</Text>
            <Text style={styles.errorBody}>{loadError}</Text>
            <TouchableOpacity style={styles.retryBtn} onPress={refresh}>
              <Text style={styles.retryBtnText}>Retry</Text>
            </TouchableOpacity>
          </View>
        )}

        {isLoading && (
          <View style={styles.loadingBox}>
            <ActivityIndicator color={C.green} size="large" />
            <Text style={styles.loadingText}>Connecting to DAWA…</Text>
          </View>
        )}

        {/* ── Patient card ── */}
        {patient && (
          <View style={[styles.card, styles.patientCard]}>
            <View style={styles.patientRow}>
              <View style={styles.patientAvatar}>
                <Text style={{ fontSize: 26 }}>👩</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.patientName}>{patient.name}</Text>
                <Text style={styles.patientUrdu}>{patient.preferred_address} — آواز ساتھی</Text>
                <Text style={styles.patientBadge}>🇵🇰 اردو  ·  Voice-first care</Text>
              </View>
            </View>
          </View>
        )}

        {/* ── Today's schedule ── */}
        {medications.length > 0 && (
          <>
            <Text style={styles.sectionLabel}>TODAY'S MEDICATIONS</Text>
            {medications.map((med) => {
              const isCallable = med.id === 'metformin-500'; // evening call for demo
              return (
                <View key={med.id} style={[styles.card, styles.medCard]}>
                  <View style={styles.medHeader}>
                    <Text style={styles.medIcon}>{getMedicationIcon(med)}</Text>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.medTime}>{formatScheduleTime(med.schedule_time)}</Text>
                      <Text style={styles.medAnchor}>{med.routine_anchor}</Text>
                    </View>
                  </View>

                  <Text style={styles.medNickname}>{med.nickname || med.clinical_name}</Text>
                  <Text style={styles.medClinical}>
                    {med.clinical_name} {med.dosage}  ·  {med.dose_instruction}
                    {med.food_instruction && med.food_instruction !== 'none'
                      ? `  ·  ${med.food_instruction}` : ''}
                  </Text>

                  {med.cues && Object.keys(med.cues).length > 0 && (
                    <View style={styles.cueRow}>
                      {Object.entries(med.cues).slice(0, 3).map(([k, v]) => (
                        <View key={k} style={styles.cuePill}>
                          <Text style={styles.cuePillText}>{k.replace('_', ' ')}: {v}</Text>
                        </View>
                      ))}
                    </View>
                  )}

                  {isCallable && (
                    <TouchableOpacity
                      style={[styles.callBtn, isActiveCall && styles.callBtnDisabled]}
                      onPress={() => handleCallPress(med)}
                      disabled={isActiveCall}
                      activeOpacity={0.8}
                    >
                      <Text style={styles.callBtnText}>
                        {isActiveCall ? '📡 Call in progress…' : '📞 Call Razia now'}
                      </Text>
                    </TouchableOpacity>
                  )}
                </View>
              );
            })}
          </>
        )}

        {/* ── Active call status ── */}
        {(isActiveCall || callPhase === 'completed' || callPhase === 'failed') && callPhase !== 'idle' && (
          <View style={[styles.card, styles.statusCard]}>
            <Text style={styles.sectionLabel} >CALL STATUS</Text>
            <View style={styles.statusRow}>
              {isActiveCall && <PulsingDot color={phaseColor} />}
              <Text style={[styles.statusLabel, { color: phaseColor }]}>
                {PHASE_LABEL[callPhase] ?? callPhase}
              </Text>
            </View>

            {/* Phase timeline */}
            <View style={styles.phaseTimeline}>
              {(['dispatched','dialing','ringing','answered','completed'] as const).map((ph) => {
                const phaseOrder = ['dispatched','dialing','ringing','answered','completed'];
                const current = phaseOrder.indexOf(callPhase);
                const thisIdx = phaseOrder.indexOf(ph);
                const active = current >= thisIdx;
                return (
                  <View key={ph} style={styles.phaseStep}>
                    <View style={[styles.phaseDot, active && { backgroundColor: C.green }]} />
                    <Text style={[styles.phaseLabel, active && { color: C.green }]}>
                      {ph}
                    </Text>
                  </View>
                );
              })}
            </View>

            {callPhase === 'completed' && (
              <View style={styles.adherenceNotice}>
                <Text style={styles.adherenceText}>
                  📋 Call ended — adherence outcome not yet confirmed.
                  {'\n'}A completed call ≠ medication taken.
                </Text>
              </View>
            )}

            {callError && (
              <Text style={styles.callErrorText}>⚠ {callError}</Text>
            )}
            {activeCallId && (
              <Text style={styles.callIdText}>Call ID: {activeCallId}</Text>
            )}
          </View>
        )}

        {callError && callPhase === 'idle' && (
          <View style={[styles.card, { backgroundColor: C.redLight, borderColor: C.red }]}>
            <Text style={{ color: C.red, fontSize: 14 }}>⚠ {callError}</Text>
          </View>
        )}

        {/* ── VMR Demo card ── */}
        <Text style={styles.sectionLabel}>MEDICINE RECOGNITION DEMO</Text>
        <View style={[styles.card, styles.vmrCard]}>
          <Text style={styles.vmrTitle}>Verified Medication Recognition</Text>
          <Text style={styles.vmrSubtitle}>
            Razia holds up her medicine. Tap cues to identify it.
          </Text>

          {/* Step 1: Box color */}
          <Text style={styles.vmrStepLabel}>Step 1 — Box colour</Text>
          <View style={styles.vmrBtnRow}>
            {[
              { label: '⬜ White', value: 'white' },
              { label: '🟩 Green', value: 'green' },
              { label: '🟦 Blue',  value: 'blue'  },
            ].map(({ label, value }) => (
              <TouchableOpacity
                key={value}
                style={[styles.vmrCueBtn, vmrBoxColor === value && styles.vmrCueBtnActive]}
                onPress={() => handleVmrBoxColor(value)}
              >
                <Text style={[styles.vmrCueBtnText, vmrBoxColor === value && { color: C.green }]}>
                  {label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Step 2: Stripe (only after white is selected) */}
          {vmrBoxColor === 'white' && (
            <>
              <Text style={styles.vmrStepLabel}>Step 2 — Stripe on the box?</Text>
              <View style={styles.vmrBtnRow}>
                {[
                  { label: '🔵 Blue stripe', value: 'blue' },
                  { label: '🔴 Red stripe',  value: 'red'  },
                  { label: '— No stripe',    value: 'none' },
                ].map(({ label, value }) => (
                  <TouchableOpacity
                    key={value}
                    style={[styles.vmrCueBtn, vmrStripeColor === value && styles.vmrCueBtnActive]}
                    onPress={() => handleVmrStripeColor(value)}
                  >
                    <Text style={[styles.vmrCueBtnText, vmrStripeColor === value && { color: C.green }]}>
                      {label}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </>
          )}

          {/* VMR spinner */}
          {vmrLoading && (
            <View style={{ alignItems: 'center', paddingVertical: 8 }}>
              <ActivityIndicator color={C.green} />
            </View>
          )}

          {/* VMR result */}
          {!vmrLoading && renderVmrResult()}

          {/* Reset button */}
          {(vmrBoxColor || vmrResult) && (
            <TouchableOpacity style={styles.vmrResetBtn} onPress={resetVmr}>
              <Text style={styles.vmrResetText}>↺ Reset</Text>
            </TouchableOpacity>
          )}

          {/* How it works note */}
          <Text style={styles.vmrNote}>
            ℹ VMR is deterministic — no AI, no guessing.  Verified by caregiver.
          </Text>
        </View>

        {/* ── Safety card ── */}
        <Text style={styles.sectionLabel}>SAFETY RULES</Text>
        <View style={[styles.card, styles.safetyCard]}>
          <Text style={styles.safetyTitle}>🛡 DAWA Safety Principles</Text>
          {[
            { icon: '🚫', text: 'Never changes the prescribed dose — even if patient asks' },
            { icon: '🚫', text: 'Never recommends a double dose if a previous dose is uncertain' },
            { icon: '✅', text: 'Only uses caregiver-verified medication descriptions' },
            { icon: '📣', text: 'Escalates any uncertainty to the caregiver immediately' },
            { icon: '📋', text: 'Call completed ≠ medication taken — adherence tracked separately' },
          ].map(({ icon, text }, i) => (
            <View key={i} style={styles.safetyRow}>
              <Text style={styles.safetyIcon}>{icon}</Text>
              <Text style={styles.safetyText}>{text}</Text>
            </View>
          ))}
        </View>

        {/* ── Recent events (compact) ── */}
        {recentDoseEvents.length > 0 && (
          <>
            <Text style={styles.sectionLabel}>RECENT CALLS</Text>
            <View style={[styles.card]}>
              {recentDoseEvents.slice(0, 4).map((ev) => (
                <View key={ev.id} style={styles.eventRow}>
                  <View style={[styles.eventDot, { backgroundColor: ev.callStatus === 'completed' ? C.green : ev.callStatus === 'failed' ? C.red : C.orange }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.eventMed}>{ev.medicationId}</Text>
                    <Text style={styles.eventStatus}>
                      {ev.callStatus}
                      {ev.adherenceOutcome ? ` · ${ev.adherenceOutcome}` : ' · outcome pending'}
                    </Text>
                  </View>
                  <Text style={styles.eventTime}>
                    {new Date(ev.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </Text>
                </View>
              ))}
            </View>
          </>
        )}

        <View style={{ height: 32 }} />
      </ScrollView>

      {/* ── Settings modal ── */}
      <Modal visible={settingsOpen} animationType="slide" presentationStyle="pageSheet">
        <SafeAreaView style={styles.modalSafe}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Settings</Text>
            <TouchableOpacity onPress={() => setSettingsOpen(false)}>
              <Text style={styles.modalClose}>Done</Text>
            </TouchableOpacity>
          </View>
          <ScrollView style={styles.modalBody}>
            <Text style={styles.fieldLabel}>DAWA Backend URL</Text>
            <TextInput
              style={styles.urlInput}
              value={urlDraft}
              onChangeText={setUrlDraft}
              placeholder="https://your-replit-domain.replit.dev"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
            />
            <Text style={styles.urlHint}>
              Set this to your Replit dev domain (no trailing slash).{'\n'}
              Example: https://abc123.replit.dev
            </Text>
            <TouchableOpacity
              style={styles.saveBtn}
              onPress={async () => {
                await setApiBaseUrl(urlDraft);
                setSettingsOpen(false);
                refresh();
              }}
            >
              <Text style={styles.saveBtnText}>Save & Connect</Text>
            </TouchableOpacity>

            <View style={styles.infoBox}>
              <Text style={styles.infoTitle}>How it works</Text>
              <Text style={styles.infoText}>
                DAWA connects to the Python backend and proxy at /api/*.{'\n\n'}
                Ensure both "DAWA Backend" and "API Server" workflows are running.{'\n\n'}
                Phone number is always read from TEST_PHONE_NUMBER on the server — never sent from this app.
              </Text>
            </View>
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: C.green },
  header: {
    backgroundColor: C.green,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: Platform.OS === 'android' ? 8 : 4,
    paddingBottom: 16,
  },
  headerTitle:    { color: '#FFF', fontSize: 28, fontWeight: '800', letterSpacing: 1 },
  headerSubtitle: { color: 'rgba(255,255,255,0.75)', fontSize: 14, marginTop: 1 },
  gearBtn:        { padding: 8 },

  scroll:         { flex: 1, backgroundColor: C.bg },
  scrollContent:  { padding: 16 },

  card: {
    backgroundColor: C.card,
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOpacity: 0.06,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
    borderWidth: 1,
    borderColor: C.border,
  },

  sectionLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: C.textMuted,
    letterSpacing: 1.2,
    marginBottom: 8,
    marginTop: 4,
  },

  // Patient card
  patientCard:   { borderLeftWidth: 4, borderLeftColor: C.green },
  patientRow:    { flexDirection: 'row', alignItems: 'center', gap: 12 },
  patientAvatar: {
    width: 52, height: 52, borderRadius: 26,
    backgroundColor: C.greenLight,
    alignItems: 'center', justifyContent: 'center',
  },
  patientName:   { fontSize: 20, fontWeight: '700', color: C.textDark },
  patientUrdu:   { fontSize: 15, color: C.urdu, marginTop: 2 },
  patientBadge:  { fontSize: 12, color: C.textMuted, marginTop: 3 },

  // Med card
  medCard:    {},
  medHeader:  { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 8 },
  medIcon:    { fontSize: 24 },
  medTime:    { fontSize: 18, fontWeight: '700', color: C.textDark },
  medAnchor:  { fontSize: 12, color: C.textMuted, marginTop: 1 },
  medNickname:{ fontSize: 17, fontWeight: '600', color: C.urdu, marginBottom: 2 },
  medClinical:{ fontSize: 13, color: C.textMuted },

  cueRow:     { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 10 },
  cuePill:    {
    backgroundColor: C.bg,
    borderRadius: 20, borderWidth: 1, borderColor: C.border,
    paddingHorizontal: 10, paddingVertical: 3,
  },
  cuePillText: { fontSize: 11, color: C.textMid },

  callBtn: {
    backgroundColor: C.green,
    borderRadius: 10, paddingVertical: 13,
    alignItems: 'center', marginTop: 12,
  },
  callBtnDisabled: { backgroundColor: C.textLight },
  callBtnText: { color: '#FFF', fontSize: 16, fontWeight: '700' },

  // Status card
  statusCard:  {},
  statusRow:   { flexDirection: 'row', alignItems: 'center', marginBottom: 12 },
  statusLabel: { fontSize: 18, fontWeight: '700' },

  phaseTimeline: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 10 },
  phaseStep:     { alignItems: 'center', flex: 1 },
  phaseDot:      { width: 8, height: 8, borderRadius: 4, backgroundColor: C.border, marginBottom: 4 },
  phaseLabel:    { fontSize: 9, color: C.textLight, textAlign: 'center' },

  adherenceNotice: {
    backgroundColor: C.orangeLight, borderRadius: 8, padding: 10, marginTop: 8,
    borderWidth: 1, borderColor: C.orange,
  },
  adherenceText: { fontSize: 12, color: C.orange, lineHeight: 18 },
  callErrorText: { color: C.red, fontSize: 12, marginTop: 6 },
  callIdText:    { color: C.textLight, fontSize: 10, marginTop: 4 },

  // Error / loading
  errorCard:   { backgroundColor: C.redLight, borderColor: C.red },
  errorTitle:  { fontSize: 15, fontWeight: '700', color: C.red, marginBottom: 4 },
  errorBody:   { fontSize: 13, color: C.red, marginBottom: 12 },
  retryBtn:    { backgroundColor: C.red, borderRadius: 8, paddingVertical: 8, alignItems: 'center' },
  retryBtnText:{ color: '#FFF', fontWeight: '700' },
  loadingBox:  { alignItems: 'center', paddingVertical: 40, gap: 12 },
  loadingText: { color: C.textMuted, fontSize: 14 },

  // VMR card
  vmrCard:     { borderTopWidth: 3, borderTopColor: C.green },
  vmrTitle:    { fontSize: 16, fontWeight: '700', color: C.textDark, marginBottom: 2 },
  vmrSubtitle: { fontSize: 13, color: C.textMuted, marginBottom: 14 },
  vmrStepLabel:{ fontSize: 12, fontWeight: '600', color: C.textMid, marginBottom: 8, marginTop: 4 },
  vmrBtnRow:   { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 8 },
  vmrCueBtn: {
    paddingHorizontal: 14, paddingVertical: 9,
    borderRadius: 8, borderWidth: 1.5, borderColor: C.border,
    backgroundColor: C.bg,
  },
  vmrCueBtnActive: { borderColor: C.green, backgroundColor: C.greenLight },
  vmrCueBtnText:   { fontSize: 13, fontWeight: '500', color: C.textMid },

  vmrResultBox:  { borderRadius: 8, borderWidth: 1, padding: 12, marginTop: 10 },
  vmrResultTitle:{ fontSize: 14, fontWeight: '800', letterSpacing: 0.5, marginBottom: 4 },
  vmrResultBody: { fontSize: 15, fontWeight: '600', color: C.textDark },
  vmrResultSub:  { fontSize: 12, color: C.textMuted, marginTop: 3 },
  vmrResultHint: { fontSize: 13, color: C.textMid, marginTop: 6, lineHeight: 20 },

  vmrResetBtn:  { alignSelf: 'flex-start', marginTop: 12, paddingVertical: 6 },
  vmrResetText: { color: C.green, fontSize: 13, fontWeight: '600' },
  vmrNote:      { fontSize: 11, color: C.textLight, marginTop: 12, fontStyle: 'italic' },

  // Safety card
  safetyCard:  { borderLeftWidth: 4, borderLeftColor: C.orange },
  safetyTitle: { fontSize: 15, fontWeight: '700', color: C.textDark, marginBottom: 10 },
  safetyRow:   { flexDirection: 'row', gap: 8, marginBottom: 8, alignItems: 'flex-start' },
  safetyIcon:  { fontSize: 16, width: 24 },
  safetyText:  { fontSize: 13, color: C.textMid, flex: 1, lineHeight: 19 },

  // Recent events
  eventRow:    { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: C.border },
  eventDot:    { width: 8, height: 8, borderRadius: 4 },
  eventMed:    { fontSize: 13, fontWeight: '600', color: C.textDark },
  eventStatus: { fontSize: 11, color: C.textMuted, marginTop: 1 },
  eventTime:   { fontSize: 11, color: C.textLight },

  // Settings modal
  modalSafe:   { flex: 1, backgroundColor: C.card },
  modalHeader: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    padding: 16, borderBottomWidth: 1, borderBottomColor: C.border,
  },
  modalTitle:  { fontSize: 18, fontWeight: '700', color: C.textDark },
  modalClose:  { fontSize: 16, color: C.green, fontWeight: '600' },
  modalBody:   { padding: 20 },

  fieldLabel:  { fontSize: 12, fontWeight: '700', color: C.textMuted, letterSpacing: 1, marginBottom: 6 },
  urlInput: {
    backgroundColor: C.bg, borderRadius: 10, borderWidth: 1.5, borderColor: C.border,
    padding: 14, fontSize: 15, color: C.textDark, marginBottom: 8,
  },
  urlHint:     { fontSize: 12, color: C.textMuted, marginBottom: 20 },
  saveBtn:     { backgroundColor: C.green, borderRadius: 10, paddingVertical: 14, alignItems: 'center' },
  saveBtnText: { color: '#FFF', fontSize: 16, fontWeight: '700' },
  infoBox: {
    backgroundColor: C.greenLight, borderRadius: 10,
    padding: 14, marginTop: 20,
  },
  infoTitle:   { fontSize: 14, fontWeight: '700', color: C.green, marginBottom: 6 },
  infoText:    { fontSize: 13, color: C.textMid, lineHeight: 20 },
});

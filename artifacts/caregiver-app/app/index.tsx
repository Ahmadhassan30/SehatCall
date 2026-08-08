/**
 * DAWA P1+P2 — Caregiver Dashboard
 *
 * P2 additions:
 *   • "Schedule demo reminder" under the Metformin card (delay picker)
 *   • Cosmetic countdown "DAWA will call Razia in X…"
 *   • UPCOMING CALL lifecycle card (real backend state)
 *   • Reset demo button in settings panel
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
  purple:     '#7C3AED',
  purpleLight:'#EDE9FE',
  bg:         '#F4F6F3',
  card:       '#FFFFFF',
  border:     '#E4E9E6',
  textDark:   '#111827',
  textMid:    '#374151',
  textMuted:  '#6B7280',
  textLight:  '#9CA3AF',
  urdu:       '#1B3A5C',
};

// ─── Phase → display ─────────────────────────────────────────────────────────
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

// Dose event statuses that map to UI labels
const STATUS_LABEL: Record<string, string> = {
  scheduled:  'Scheduled',
  due:        'Due',
  calling:    'Calling',
  dispatched: 'Dispatched',
  dialing:    'Dialing',
  ringing:    'Ringing',
  answered:   'Answered',
  completed:  'Completed',
  failed:     'Failed',
};

const STATUS_COLOR: Record<string, string> = {
  scheduled:  C.blue,
  due:        C.orange,
  calling:    C.orange,
  dispatched: C.orange,
  dialing:    C.orange,
  ringing:    C.orange,
  answered:   C.green,
  completed:  C.textMid,
  failed:     C.red,
};

const ACTIVE_PHASES = new Set(['dispatching', 'dispatched', 'dialing', 'ringing', 'answered']);

// ─── Demo delay options ───────────────────────────────────────────────────────
const DELAY_OPTIONS = [
  { label: '30 seconds', value: 30 },
  { label: '60 seconds', value: 60 },
  { label: '2 minutes',  value: 120 },
];

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
  if (time >= 5  && time < 12) return '🌅';
  if (time >= 12 && time < 17) return '☀️';
  if (time >= 17 && time < 20) return '🌇';
  return '🌙';
}

function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function friendlyFailureReason(reason?: string | null): string {
  if (!reason) return 'Unknown issue';
  const map: Record<string, string> = {
    busy:           'Phone busy',
    no_answer:      'No answer',
    silent_pickup:  'No response after pickup',
    voicemail:      'Went to voicemail',
    network_error:  'Network issue',
    unreachable:    'Phone unreachable',
    declined:       'Call declined',
    wrong_number:   'Wrong number',
  };
  return map[reason] ?? reason;
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
    <Animated.View style={{
      width: 8, height: 8, borderRadius: 4,
      backgroundColor: color,
      transform: [{ scale }],
      marginRight: 6,
    }} />
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
    // P2
    scheduledCall, countdownSeconds, isScheduling, scheduleDemo, scheduleError,
    isResetting, resetDemo, resetError,
  } = useDawa();

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [urlDraft, setUrlDraft] = useState(apiBaseUrl);

  // Demo scheduling
  const [schedulePickerOpen, setSchedulePickerOpen] = useState(false);
  const [selectedDelay, setSelectedDelay] = useState(60);

  // Auto-open settings if no API URL is configured
  useEffect(() => { if (!apiBaseUrl) setSettingsOpen(true); }, []);

  // ── VMR demo logic ──────────────────────────────────────────────────────
  const [vmrBoxColor, setVmrBoxColor]       = useState<string | null>(null);
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

  // ── Manual call handler ──────────────────────────────────────────────────
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

  // ── Schedule demo handler ────────────────────────────────────────────────
  async function handleSchedulePress() {
    setSchedulePickerOpen(false);
    await scheduleDemo('metformin-500', selectedDelay);
  }

  // ── Reset handler ────────────────────────────────────────────────────────
  async function handleReset() {
    Alert.alert(
      'Reset demo?',
      "This will clear all call history and scheduled reminders. Razia's medication data will be preserved.",
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Reset', style: 'destructive', onPress: () => resetDemo() },
      ]
    );
  }

  const isActiveCall = ACTIVE_PHASES.has(callPhase);
  const phaseColor   = PHASE_COLOR[callPhase] ?? C.textMuted;

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
          <Text style={styles.vmrResultBody}>Two white boxes — can't tell apart yet.</Text>
          {disc && (
            <Text style={styles.vmrResultHint}>
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
          <Text style={styles.vmrResultBody}>{med?.nickname ?? vmrResult.medicationId}</Text>
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

  // ── UPCOMING CALL card ────────────────────────────────────────────────────
  function renderUpcomingCallCard() {
    if (!scheduledCall) return null;
    const status = scheduledCall.callStatus;
    const statusColor = STATUS_COLOR[status] ?? C.textMuted;
    const statusLabel = STATUS_LABEL[status] ?? status;
    const med = medications.find(m => m.id === scheduledCall.medicationId);
    const isActive = ['calling', 'dispatched', 'dialing', 'ringing', 'answered'].includes(status);
    const isDone   = ['completed', 'failed'].includes(status);

    return (
      <View style={[styles.card, {
        borderLeftWidth: 4,
        borderLeftColor: statusColor,
        marginBottom: 12,
      }]}>
        <View style={styles.row}>
          <Text style={styles.sectionLabel}>UPCOMING CALL</Text>
          {isActive && <PulsingDot color={statusColor} />}
        </View>
        <Text style={styles.upcomingMedName}>
          {med?.nickname ?? med?.clinical_name ?? scheduledCall.medicationId}
        </Text>
        <Text style={styles.upcomingTime}>
          {med ? `${formatScheduleTime(med.schedule_time)}` : ''}
          {countdownSeconds !== null && countdownSeconds > 0 && !isActive
            ? ` · demo in ${Math.ceil(countdownSeconds / 60)} min` : ''}
        </Text>

        {/* Countdown display */}
        {countdownSeconds !== null && countdownSeconds > 0 && !isActive && (
          <View style={styles.countdownBox}>
            <Text style={styles.countdownNumber}>{formatCountdown(countdownSeconds)}</Text>
            <Text style={styles.countdownLabel}>until DAWA calls Razia</Text>
          </View>
        )}

        {/* Status badge */}
        <View style={[styles.statusBadge, { backgroundColor: statusColor + '22' }]}>
          <Text style={[styles.statusBadgeText, { color: statusColor }]}>
            {statusLabel}
          </Text>
        </View>

        {/* Phase timeline */}
        <View style={styles.timeline}>
          {(['scheduled', 'due', 'calling', 'ringing', 'answered', 'completed'] as const).map((s, i) => {
            const reached = isStatusReached(status, s);
            return (
              <React.Fragment key={s}>
                {i > 0 && (
                  <View style={[styles.timelineLine, reached && { backgroundColor: statusColor }]} />
                )}
                <View style={[styles.timelineDot,
                  reached && { backgroundColor: statusColor, borderColor: statusColor }]} />
              </React.Fragment>
            );
          })}
        </View>
        <View style={styles.timelineLabels}>
          {['Sched', 'Due', 'Calling', 'Ringing', 'Answered', isDone ? statusLabel : 'Done'].map((l) => (
            <Text key={l} style={styles.timelineLabel}>{l}</Text>
          ))}
        </View>
      </View>
    );
  }

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

        {/* ── UPCOMING CALL card (P2) ── */}
        {renderUpcomingCallCard()}

        {/* ── Schedule error ── */}
        {scheduleError && (
          <View style={[styles.card, { borderLeftWidth: 4, borderLeftColor: C.red }]}>
            <Text style={[styles.errorTitle, { fontSize: 14 }]}>Schedule error</Text>
            <Text style={styles.errorBody}>{scheduleError}</Text>
          </View>
        )}

        {/* ── Today's schedule ── */}
        {medications.length > 0 && (
          <>
            <Text style={styles.sectionHeader}>Today's Schedule</Text>

            {medications.map((med) => {
              const isMetformin = med.id === 'metformin-500';
              const alreadyScheduled = scheduledCall?.medicationId === med.id &&
                !['completed', 'failed'].includes(scheduledCall.callStatus);

              return (
                <View key={med.id} style={styles.card}>
                  {/* Med header */}
                  <View style={styles.medHeader}>
                    <Text style={styles.medIcon}>{getMedicationIcon(med)}</Text>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.medNickname}>{med.nickname ?? med.clinical_name}</Text>
                      <Text style={styles.medName}>{med.clinical_name} {med.dosage}</Text>
                    </View>
                    <View style={styles.medTimeBadge}>
                      <Text style={styles.medTime}>{formatScheduleTime(med.schedule_time)}</Text>
                    </View>
                  </View>

                  <Text style={styles.medInstruction}>{med.dose_instruction} · {med.food_instruction}</Text>

                  {/* Verified cues */}
                  {med.cues && Object.keys(med.cues).length > 0 && (
                    <View style={styles.cueRow}>
                      {Object.entries(med.cues).map(([k, v]) => (
                        <View key={k} style={styles.cuePill}>
                          <Text style={styles.cuePillText}>{k.replace('_', ' ')}: {v}</Text>
                        </View>
                      ))}
                    </View>
                  )}

                  {/* Action row */}
                  <View style={styles.medActions}>
                    {/* Manual call button */}
                    <TouchableOpacity
                      style={[styles.callBtn, isActiveCall && styles.callBtnDisabled]}
                      onPress={() => handleCallPress(med)}
                      disabled={isActiveCall}
                    >
                      <Text style={styles.callBtnText}>
                        {isActiveCall ? '📞 Calling…' : '📞 Call Razia now'}
                      </Text>
                    </TouchableOpacity>

                    {/* P2: Schedule demo reminder (Metformin only) */}
                    {isMetformin && (
                      <TouchableOpacity
                        style={[styles.scheduleBtn, (alreadyScheduled || isScheduling) && styles.scheduleBtnDisabled]}
                        onPress={() => setSchedulePickerOpen(true)}
                        disabled={alreadyScheduled || isScheduling}
                      >
                        <Text style={styles.scheduleBtnText}>
                          {isScheduling ? '⏳ Scheduling…' :
                           alreadyScheduled ? '✓ Scheduled' : '🕐 Schedule demo reminder'}
                        </Text>
                      </TouchableOpacity>
                    )}
                  </View>
                </View>
              );
            })}
          </>
        )}

        {/* ── Active call status ── */}
        {callPhase !== 'idle' && (
          <View style={styles.card}>
            <Text style={styles.sectionLabel}>MANUAL CALL STATUS</Text>
            <View style={styles.phaseRow}>
              {isActiveCall && <PulsingDot color={phaseColor} />}
              <Text style={[styles.phaseLabel, { color: phaseColor }]}>
                {PHASE_LABEL[callPhase] ?? callPhase}
              </Text>
            </View>
            {callError && (
              <Text style={styles.callErrorText}>⚠ {callError}</Text>
            )}
            <View style={styles.phaseTimeline}>
              {(['dispatched', 'dialing', 'ringing', 'answered', 'completed'] as const).map((p, i) => {
                const reached = isCallPhaseReached(callPhase as any, p);
                return (
                  <React.Fragment key={p}>
                    {i > 0 && (
                      <View style={[styles.timelineLine, reached && { backgroundColor: phaseColor }]} />
                    )}
                    <View style={[styles.timelineDot, reached && { backgroundColor: phaseColor, borderColor: phaseColor }]} />
                  </React.Fragment>
                );
              })}
            </View>
            <View style={[styles.timelineLabels, { marginTop: 4 }]}>
              {['Dispatch', 'Dialing', 'Ringing', 'Answered', 'Done'].map((l) => (
                <Text key={l} style={styles.timelineLabel}>{l}</Text>
              ))}
            </View>
          </View>
        )}

        {/* ── VMR demo card ── */}
        <View style={styles.card}>
          <Text style={styles.sectionLabel}>MEDICATION IDENTIFIER (VMR)</Text>
          <Text style={styles.vmrSubtitle}>
            Both white boxes — tap to identify which medicine it is.
          </Text>

          <Text style={styles.vmrStepLabel}>Step 1 — Box colour</Text>
          <View style={styles.vmrRow}>
            {['white', 'blue', 'green'].map((color) => (
              <TouchableOpacity
                key={color}
                style={[styles.vmrColorBtn,
                  vmrBoxColor === color && { borderColor: C.green, borderWidth: 2.5 }]}
                onPress={() => handleVmrBoxColor(color)}
              >
                <Text style={styles.vmrColorLabel}>{color}</Text>
              </TouchableOpacity>
            ))}
          </View>

          {vmrBoxColor === 'white' && (
            <>
              <Text style={styles.vmrStepLabel}>Step 2 — Stripe colour</Text>
              <View style={styles.vmrRow}>
                {['none', 'blue', 'red', 'yellow'].map((stripe) => (
                  <TouchableOpacity
                    key={stripe}
                    style={[styles.vmrColorBtn,
                      vmrStripeColor === stripe && { borderColor: C.green, borderWidth: 2.5 }]}
                    onPress={() => handleVmrStripeColor(stripe)}
                  >
                    <Text style={styles.vmrColorLabel}>{stripe}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </>
          )}

          {vmrLoading && (
            <ActivityIndicator color={C.green} style={{ marginTop: 8 }} />
          )}
          {renderVmrResult()}

          {(vmrBoxColor || vmrResult) && (
            <TouchableOpacity style={styles.vmrResetBtn} onPress={resetVmr}>
              <Text style={styles.vmrResetText}>↺ Reset VMR</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* ── Safety rules ── */}
        <View style={[styles.card, { borderLeftWidth: 4, borderLeftColor: C.orange }]}>
          <Text style={styles.sectionLabel}>SAFETY RULES</Text>
          <Text style={styles.safetyItem}>✓ Completed call ≠ dose taken — verify separately</Text>
          <Text style={styles.safetyItem}>✓ VMR uses caregiver-verified visual cues only</Text>
          <Text style={styles.safetyItem}>✓ Phone number is set by the care team, not the app</Text>
          <Text style={styles.safetyItem}>✓ DAWA never auto-records TAKEN from call status</Text>
        </View>

      </ScrollView>

      {/* ── Delay picker modal (P2) ── */}
      <Modal
        visible={schedulePickerOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setSchedulePickerOpen(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.pickerCard}>
            <Text style={styles.pickerTitle}>Schedule demo reminder</Text>
            <Text style={styles.pickerSubtitle}>
              DAWA will call Razia after the selected delay.{'\n'}
              Do not touch the app — the call will happen automatically.
            </Text>

            {DELAY_OPTIONS.map((opt) => (
              <TouchableOpacity
                key={opt.value}
                style={[styles.delayOption, selectedDelay === opt.value && styles.delayOptionSelected]}
                onPress={() => setSelectedDelay(opt.value)}
              >
                <Text style={[styles.delayOptionText, selectedDelay === opt.value && { color: C.green, fontWeight: '700' }]}>
                  {opt.label}
                </Text>
                {selectedDelay === opt.value && (
                  <Text style={{ color: C.green, fontSize: 18 }}>✓</Text>
                )}
              </TouchableOpacity>
            ))}

            <View style={styles.pickerActions}>
              <TouchableOpacity
                style={[styles.pickerBtn, { backgroundColor: C.greenLight, borderColor: C.green }]}
                onPress={handleSchedulePress}
              >
                <Text style={[styles.pickerBtnText, { color: C.green }]}>Confirm</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.pickerBtn, { backgroundColor: C.bg, borderColor: C.border }]}
                onPress={() => setSchedulePickerOpen(false)}
              >
                <Text style={[styles.pickerBtnText, { color: C.textMid }]}>Cancel</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* ── Settings modal ── */}
      <Modal
        visible={settingsOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setSettingsOpen(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.settingsCard}>
            <Text style={styles.settingsTitle}>DAWA Settings</Text>

            <Text style={styles.settingsLabel}>Backend URL</Text>
            <TextInput
              style={styles.settingsInput}
              value={urlDraft}
              onChangeText={setUrlDraft}
              placeholder="https://your-replit-domain"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
            />

            <TouchableOpacity
              style={styles.settingsSaveBtn}
              onPress={() => {
                setApiBaseUrl(urlDraft);
                setSettingsOpen(false);
              }}
            >
              <Text style={styles.settingsSaveBtnText}>Save & Close</Text>
            </TouchableOpacity>

            {/* P2: Reset demo */}
            <View style={styles.settingsDivider} />
            <Text style={styles.settingsLabel}>Demo Controls</Text>
            <TouchableOpacity
              style={[styles.resetBtn, isResetting && styles.resetBtnDisabled]}
              onPress={() => { setSettingsOpen(false); setTimeout(handleReset, 200); }}
              disabled={isResetting}
            >
              {isResetting
                ? <ActivityIndicator color={C.red} size="small" />
                : <Text style={styles.resetBtnText}>🗑 Reset demo</Text>
              }
            </TouchableOpacity>
            {resetError && (
              <Text style={[styles.errorBody, { marginTop: 4 }]}>{resetError}</Text>
            )}
            <Text style={styles.resetHint}>
              Clears call history and scheduled reminders.{'\n'}
              Razia's medication data is preserved.
            </Text>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

// ─── Phase helpers ────────────────────────────────────────────────────────────

type CallPhaseKey = 'dispatched' | 'dialing' | 'ringing' | 'answered' | 'completed';
const CALL_PHASE_ORDER: CallPhaseKey[] = ['dispatched', 'dialing', 'ringing', 'answered', 'completed'];

function isCallPhaseReached(current: string, target: CallPhaseKey): boolean {
  const ci = CALL_PHASE_ORDER.indexOf(current as CallPhaseKey);
  const ti = CALL_PHASE_ORDER.indexOf(target);
  return ci >= ti;
}

type DoseStatusKey = 'scheduled' | 'due' | 'calling' | 'ringing' | 'answered' | 'completed';
const STATUS_ORDER: DoseStatusKey[] = ['scheduled', 'due', 'calling', 'ringing', 'answered', 'completed'];

function isStatusReached(current: string, target: DoseStatusKey): boolean {
  const ci = STATUS_ORDER.indexOf(current as DoseStatusKey);
  const ti = STATUS_ORDER.indexOf(target);
  if (ci === -1) return false;
  return ci >= ti;
}

// ─── Styles ──────────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  safe:             { flex: 1, backgroundColor: C.green },
  header:           { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
                      paddingHorizontal: 20, paddingVertical: 16, backgroundColor: C.green },
  headerTitle:      { fontSize: 26, fontWeight: '800', color: '#fff', letterSpacing: 1.5 },
  headerSubtitle:   { fontSize: 14, color: 'rgba(255,255,255,0.8)', marginTop: 2 },
  gearBtn:          { padding: 8 },

  scroll:           { flex: 1, backgroundColor: C.bg },
  scrollContent:    { padding: 16, paddingBottom: 40 },

  card:             { backgroundColor: C.card, borderRadius: 16, padding: 16, marginBottom: 12,
                      shadowColor: '#000', shadowOffset: { width: 0, height: 2 },
                      shadowOpacity: 0.06, shadowRadius: 6, elevation: 3 },
  sectionHeader:    { fontSize: 13, fontWeight: '700', color: C.textMuted, letterSpacing: 1,
                      textTransform: 'uppercase', marginBottom: 8, marginTop: 4 },
  sectionLabel:     { fontSize: 11, fontWeight: '700', color: C.textMuted, letterSpacing: 1,
                      textTransform: 'uppercase', marginBottom: 8 },
  row:              { flexDirection: 'row', alignItems: 'center', marginBottom: 8 },

  // Patient
  patientCard:      { borderLeftWidth: 4, borderLeftColor: C.green },
  patientRow:       { flexDirection: 'row', alignItems: 'center', gap: 12 },
  patientAvatar:    { width: 52, height: 52, borderRadius: 26, backgroundColor: C.greenLight,
                      alignItems: 'center', justifyContent: 'center' },
  patientName:      { fontSize: 18, fontWeight: '700', color: C.textDark },
  patientUrdu:      { fontSize: 14, color: C.urdu, marginTop: 2 },
  patientBadge:     { fontSize: 12, color: C.textMuted, marginTop: 4 },

  // Medication cards
  medHeader:        { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 6 },
  medIcon:          { fontSize: 24 },
  medNickname:      { fontSize: 16, fontWeight: '700', color: C.textDark },
  medName:          { fontSize: 13, color: C.textMuted, marginTop: 1 },
  medTimeBadge:     { backgroundColor: C.greenLight, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4 },
  medTime:          { fontSize: 13, fontWeight: '700', color: C.green },
  medInstruction:   { fontSize: 13, color: C.textMid, marginBottom: 10 },
  cueRow:           { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 10 },
  cuePill:          { backgroundColor: C.blueLight, borderRadius: 12, paddingHorizontal: 10, paddingVertical: 3 },
  cuePillText:      { fontSize: 11, color: C.blue, fontWeight: '600' },
  medActions:       { gap: 8 },
  callBtn:          { backgroundColor: C.green, borderRadius: 12, paddingVertical: 12,
                      alignItems: 'center' },
  callBtnDisabled:  { backgroundColor: C.textLight },
  callBtnText:      { color: '#fff', fontWeight: '700', fontSize: 15 },
  scheduleBtn:      { backgroundColor: C.purpleLight, borderRadius: 12, paddingVertical: 10,
                      alignItems: 'center', borderWidth: 1.5, borderColor: C.purple },
  scheduleBtnDisabled: { opacity: 0.5 },
  scheduleBtnText:  { color: C.purple, fontWeight: '700', fontSize: 14 },

  // UPCOMING CALL card
  upcomingMedName:  { fontSize: 18, fontWeight: '700', color: C.textDark, marginBottom: 2 },
  upcomingTime:     { fontSize: 13, color: C.textMuted, marginBottom: 10 },
  countdownBox:     { alignItems: 'center', paddingVertical: 12, marginBottom: 10 },
  countdownNumber:  { fontSize: 36, fontWeight: '800', color: C.purple, letterSpacing: 4 },
  countdownLabel:   { fontSize: 13, color: C.textMuted, marginTop: 4 },
  statusBadge:      { alignSelf: 'flex-start', borderRadius: 8, paddingHorizontal: 12,
                      paddingVertical: 4, marginBottom: 10 },
  statusBadgeText:  { fontSize: 13, fontWeight: '700' },

  // Timeline
  timeline:         { flexDirection: 'row', alignItems: 'center', marginTop: 8 },
  timelineLine:     { flex: 1, height: 2, backgroundColor: C.border },
  timelineDot:      { width: 10, height: 10, borderRadius: 5, borderWidth: 2,
                      borderColor: C.border, backgroundColor: C.card },
  timelineLabels:   { flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 },
  timelineLabel:    { fontSize: 10, color: C.textLight, flex: 1, textAlign: 'center' },

  // Manual call status
  phaseRow:         { flexDirection: 'row', alignItems: 'center', marginBottom: 8 },
  phaseLabel:       { fontSize: 16, fontWeight: '700' },
  phaseTimeline:    { flexDirection: 'row', alignItems: 'center', marginTop: 8 },
  callErrorText:    { fontSize: 13, color: C.red, marginTop: 4 },

  // VMR
  vmrSubtitle:      { fontSize: 13, color: C.textMid, marginBottom: 12 },
  vmrStepLabel:     { fontSize: 12, fontWeight: '600', color: C.textMuted, marginBottom: 6 },
  vmrRow:           { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 12 },
  vmrColorBtn:      { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8,
                      backgroundColor: C.bg, borderWidth: 1.5, borderColor: C.border },
  vmrColorLabel:    { fontSize: 13, color: C.textMid, fontWeight: '600' },
  vmrResultBox:     { borderWidth: 1.5, borderRadius: 10, padding: 12, marginTop: 4 },
  vmrResultTitle:   { fontSize: 14, fontWeight: '800', marginBottom: 4 },
  vmrResultBody:    { fontSize: 15, fontWeight: '700', color: C.textDark },
  vmrResultSub:     { fontSize: 12, color: C.textMuted, marginTop: 4 },
  vmrResultHint:    { fontSize: 13, color: C.textMid, marginTop: 6, lineHeight: 20 },
  vmrResetBtn:      { marginTop: 10, alignSelf: 'flex-start', paddingVertical: 6, paddingHorizontal: 12,
                      borderRadius: 8, backgroundColor: C.bg, borderWidth: 1, borderColor: C.border },
  vmrResetText:     { fontSize: 13, color: C.textMuted },

  // Safety
  safetyItem:       { fontSize: 13, color: C.textMid, marginBottom: 4, lineHeight: 20 },

  // Error / loading
  errorCard:        { borderLeftWidth: 4, borderLeftColor: C.red },
  errorTitle:       { fontSize: 16, fontWeight: '700', color: C.red, marginBottom: 4 },
  errorBody:        { fontSize: 13, color: C.textMid },
  retryBtn:         { marginTop: 8, alignSelf: 'flex-start', backgroundColor: C.red,
                      borderRadius: 8, paddingHorizontal: 14, paddingVertical: 7 },
  retryBtnText:     { color: '#fff', fontWeight: '700', fontSize: 13 },
  loadingBox:       { alignItems: 'center', paddingVertical: 32 },
  loadingText:      { color: C.textMuted, marginTop: 10 },

  // Delay picker modal
  modalOverlay:     { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'center',
                      alignItems: 'center', padding: 20 },
  pickerCard:       { backgroundColor: C.card, borderRadius: 20, padding: 24, width: '100%', maxWidth: 360 },
  pickerTitle:      { fontSize: 18, fontWeight: '800', color: C.textDark, marginBottom: 6 },
  pickerSubtitle:   { fontSize: 13, color: C.textMuted, marginBottom: 20, lineHeight: 20 },
  delayOption:      { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
                      padding: 14, borderRadius: 12, borderWidth: 1.5, borderColor: C.border,
                      marginBottom: 10 },
  delayOptionSelected: { borderColor: C.green, backgroundColor: C.greenLight },
  delayOptionText:  { fontSize: 15, color: C.textMid, fontWeight: '600' },
  pickerActions:    { flexDirection: 'row', gap: 12, marginTop: 8 },
  pickerBtn:        { flex: 1, borderRadius: 12, borderWidth: 1.5, paddingVertical: 12,
                      alignItems: 'center' },
  pickerBtnText:    { fontSize: 15, fontWeight: '700' },

  // Settings modal
  settingsCard:     { backgroundColor: C.card, borderRadius: 20, padding: 24, width: '100%', maxWidth: 400 },
  settingsTitle:    { fontSize: 20, fontWeight: '800', color: C.textDark, marginBottom: 20 },
  settingsLabel:    { fontSize: 12, fontWeight: '700', color: C.textMuted, letterSpacing: 1,
                      textTransform: 'uppercase', marginBottom: 8 },
  settingsInput:    { borderWidth: 1.5, borderColor: C.border, borderRadius: 10, padding: 12,
                      fontSize: 14, color: C.textDark, marginBottom: 16 },
  settingsSaveBtn:  { backgroundColor: C.green, borderRadius: 10, paddingVertical: 13,
                      alignItems: 'center', marginBottom: 4 },
  settingsSaveBtnText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  settingsDivider:  { height: 1, backgroundColor: C.border, marginVertical: 20 },
  resetBtn:         { borderWidth: 1.5, borderColor: C.red, borderRadius: 10, paddingVertical: 11,
                      alignItems: 'center', marginBottom: 8 },
  resetBtnDisabled: { opacity: 0.5 },
  resetBtnText:     { color: C.red, fontWeight: '700', fontSize: 14 },
  resetHint:        { fontSize: 12, color: C.textLight, lineHeight: 18 },
});

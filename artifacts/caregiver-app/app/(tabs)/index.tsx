/**
 * Home tab — next upcoming call, call-now, and live call status.
 */
import React, { useCallback, useEffect, useRef } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Animated,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import * as Haptics from 'expo-haptics';
import { useP3 } from '@/context/P3Context';
import { DawaHeader } from '@/components/DawaHeader';

const C = {
  cream: '#F7F3E8',
  blue: '#6F9FB5',
  navy: '#243642',
  white: '#FFFFFF',
  border: '#D8D0BC',
  muted: '#7A8A8E',
  warn: '#C97B2A',
  warnBg: '#FDF3E3',
  err: '#B83232',
  errBg: '#FDEAEA',
  ok: '#2D7A4F',
  okBg: '#EAF5EE',
};

function formatCountdown(secs: number | null): string {
  if (secs === null || secs <= 0) return 'Due now';
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-PK', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

function PulsingRing() {
  const anim = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(anim, { toValue: 1, duration: 900, useNativeDriver: true }),
        Animated.timing(anim, { toValue: 0, duration: 900, useNativeDriver: true }),
      ])
    ).start();
  }, []);
  return (
    <Animated.View
      style={[
        styles.pulseRing,
        { opacity: anim, transform: [{ scale: anim.interpolate({ inputRange: [0, 1], outputRange: [1, 1.18] }) }] },
      ]}
    />
  );
}

export default function HomeScreen() {
  const {
    nextCall, nextCallLoading, refreshNextCall, secondsUntilNext,
    calls, callsLoading, refreshCalls,
    callMedicationNow, activeCallPhase, activeCallError, clearCallState,
    medications,
  } = useP3();

  const recentCall = calls[0] ?? null;

  const onRefresh = useCallback(async () => {
    await Promise.all([refreshNextCall(), refreshCalls()]);
  }, [refreshNextCall, refreshCalls]);

  const handleCallNow = useCallback(async () => {
    if (!nextCall) return;
    await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    clearCallState();
    try {
      await callMedicationNow(nextCall.medicationId);
      await refreshCalls();
    } catch {
      // error shown via activeCallError
    }
  }, [nextCall, callMedicationNow, refreshCalls, clearCallState]);

  const isCalling = activeCallPhase === 'calling';

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <DawaHeader title="DAWA" subtitle="Medication reminder for Razia Bibi" />
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={nextCallLoading || callsLoading}
            onRefresh={onRefresh}
            tintColor={C.blue}
          />
        }
      >
        {/* ── Next call card ─────────────────────────────────────────── */}
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>NEXT SCHEDULED CALL</Text>
          {nextCall ? (
            <View style={styles.nextCard}>
              <View style={styles.nextCardTop}>
                <View style={styles.nextCardLeft}>
                  <Text style={styles.medName}>
                    {nextCall.nickname || nextCall.clinicalName}
                  </Text>
                  <Text style={styles.medSub}>{nextCall.clinicalName} · {nextCall.dosage}</Text>
                  <Text style={styles.scheduleTime}>Scheduled at {nextCall.scheduleTime}</Text>
                </View>
                <View style={styles.countdownBox}>
                  <Text style={styles.countdownValue}>{formatCountdown(secondsUntilNext)}</Text>
                  <Text style={styles.countdownLabel}>remaining</Text>
                </View>
              </View>

              {!nextCall.autoCallEnabled && (
                <View style={styles.infoBanner}>
                  <Text style={styles.infoText}>Auto-calling is off for this medication</Text>
                </View>
              )}

              {/* Call now button */}
              <TouchableOpacity
                style={[styles.callBtn, isCalling && styles.callBtnDisabled]}
                onPress={handleCallNow}
                disabled={isCalling}
                activeOpacity={0.8}
              >
                {isCalling ? (
                  <View style={styles.callBtnInner}>
                    <PulsingRing />
                    <ActivityIndicator color={C.white} size="small" />
                    <Text style={styles.callBtnText}>Calling Razia Bibi…</Text>
                  </View>
                ) : (
                  <Text style={styles.callBtnText}>Call now</Text>
                )}
              </TouchableOpacity>

              {activeCallError ? (
                <View style={styles.errBanner}>
                  <Text style={styles.errText}>{activeCallError}</Text>
                </View>
              ) : null}
            </View>
          ) : (
            <View style={styles.emptyCard}>
              <Text style={styles.emptyTitle}>No upcoming call</Text>
              <Text style={styles.emptyText}>
                Add a medication with auto-calling enabled to schedule a reminder.
              </Text>
            </View>
          )}
        </View>

        {/* ── Most recent call ───────────────────────────────────────── */}
        {recentCall ? (
          <View style={styles.section}>
            <Text style={styles.sectionLabel}>MOST RECENT CALL</Text>
            <View style={styles.recentCard}>
              <View style={styles.recentRow}>
                <Text style={styles.recentMed}>{recentCall.nickname || recentCall.clinicalName}</Text>
                <StatusBadge status={recentCall.callStatus} />
              </View>
              <Text style={styles.recentTime}>{formatTime(recentCall.scheduledTime)}</Text>
              <View style={styles.adherenceRow}>
                <Text style={styles.adherenceKey}>Outcome: </Text>
                <Text style={styles.adherenceVal}>{recentCall.adherenceLabel}</Text>
              </View>
            </View>
          </View>
        ) : null}

        {/* ── All medications summary ────────────────────────────────── */}
        {medications.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionLabel}>MEDICATIONS ON SCHEDULE</Text>
            {medications.filter((m) => m.active).map((med) => (
              <View key={med.id} style={styles.summaryRow}>
                <View style={styles.summaryDot} />
                <Text style={styles.summaryName}>{med.nickname || med.clinicalName}</Text>
                <Text style={styles.summaryTime}>{med.scheduleTime}</Text>
              </View>
            ))}
            {medications.filter((m) => m.active).length === 0 && (
              <Text style={styles.emptyText}>No active medications</Text>
            )}
          </View>
        )}
      </ScrollView>
    </View>
  );
}

function StatusBadge({ status }: { status: string }) {
  const configs: Record<string, { bg: string; fg: string; label: string }> = {
    completed: { bg: C.okBg, fg: C.ok, label: 'Completed' },
    answered: { bg: C.okBg, fg: C.ok, label: 'Answered' },
    failed: { bg: C.errBg, fg: C.err, label: 'Failed' },
    calling: { bg: C.warnBg, fg: C.warn, label: 'Calling' },
    dispatched: { bg: C.warnBg, fg: C.warn, label: 'Dispatched' },
    ringing: { bg: C.warnBg, fg: C.warn, label: 'Ringing' },
  };
  const cfg = configs[status] ?? { bg: '#F0F0F0', fg: C.muted, label: status };
  return (
    <View style={[styles.badge, { backgroundColor: cfg.bg }]}>
      <Text style={[styles.badgeText, { color: cfg.fg }]}>{cfg.label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.cream },
  scroll: { padding: 20, paddingBottom: 40 },
  section: { marginBottom: 24 },
  sectionLabel: {
    fontFamily: 'Inter_600SemiBold',
    fontSize: 11,
    color: C.muted,
    letterSpacing: 1.1,
    marginBottom: 10,
  },

  // Next card
  nextCard: {
    backgroundColor: C.white,
    borderRadius: 16,
    padding: 20,
    shadowColor: C.navy,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.07,
    shadowRadius: 8,
    elevation: 3,
  },
  nextCardTop: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 18 },
  nextCardLeft: { flex: 1, marginRight: 12 },
  medName: { fontFamily: 'Inter_700Bold', fontSize: 20, color: C.navy, marginBottom: 4 },
  medSub: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.muted },
  scheduleTime: { fontFamily: 'Inter_500Medium', fontSize: 13, color: C.navy + 'AA', marginTop: 4 },
  countdownBox: { alignItems: 'center', justifyContent: 'center', minWidth: 72 },
  countdownValue: { fontFamily: 'Inter_700Bold', fontSize: 22, color: C.blue },
  countdownLabel: { fontFamily: 'Inter_400Regular', fontSize: 11, color: C.muted, marginTop: 2 },

  callBtn: {
    backgroundColor: C.blue,
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 56,
  },
  callBtnDisabled: { backgroundColor: C.blue + 'AA' },
  callBtnInner: { flexDirection: 'row', alignItems: 'center', gap: 10, position: 'relative' },
  callBtnText: { fontFamily: 'Inter_600SemiBold', fontSize: 17, color: C.white },
  pulseRing: {
    position: 'absolute',
    width: 28,
    height: 28,
    borderRadius: 14,
    borderWidth: 2,
    borderColor: C.white,
    left: -6,
  },

  infoBanner: {
    backgroundColor: C.warnBg,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginBottom: 12,
  },
  infoText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.warn },
  errBanner: {
    backgroundColor: C.errBg,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginTop: 10,
  },
  errText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.err },

  // Empty card
  emptyCard: {
    backgroundColor: C.white,
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: C.border,
    borderStyle: 'dashed',
  },
  emptyTitle: { fontFamily: 'Inter_600SemiBold', fontSize: 16, color: C.navy, marginBottom: 6 },
  emptyText: { fontFamily: 'Inter_400Regular', fontSize: 14, color: C.muted, textAlign: 'center', lineHeight: 20 },

  // Recent call
  recentCard: {
    backgroundColor: C.white,
    borderRadius: 16,
    padding: 18,
    shadowColor: C.navy,
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 2,
  },
  recentRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  recentMed: { fontFamily: 'Inter_600SemiBold', fontSize: 16, color: C.navy },
  recentTime: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.muted, marginBottom: 8 },
  adherenceRow: { flexDirection: 'row' },
  adherenceKey: { fontFamily: 'Inter_500Medium', fontSize: 13, color: C.muted },
  adherenceVal: { fontFamily: 'Inter_500Medium', fontSize: 13, color: C.navy },

  badge: { borderRadius: 8, paddingHorizontal: 10, paddingVertical: 4 },
  badgeText: { fontFamily: 'Inter_600SemiBold', fontSize: 12 },

  // Medications summary
  summaryRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: C.border + '60' },
  summaryDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: C.blue, marginRight: 12 },
  summaryName: { fontFamily: 'Inter_500Medium', fontSize: 15, color: C.navy, flex: 1 },
  summaryTime: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.muted },
});

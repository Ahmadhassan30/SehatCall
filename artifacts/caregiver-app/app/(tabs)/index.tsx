import React, { useCallback } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import * as Haptics from 'expo-haptics';
import { Ionicons } from '@expo/vector-icons';
import { DawaHeader } from '@/components/DawaHeader';
import { useLanguage } from '@/context/LanguageContext';
import { useP3 } from '@/context/P3Context';
import { radius, ui } from '@/lib/ui';

function adherenceKey(outcome: string | null): string {
  if (outcome === 'TAKEN') return 'adherence.taken';
  if (outcome === 'NOT_TAKEN') return 'adherence.notTaken';
  return 'adherence.unknown';
}

export default function HomeScreen() {
  const { isUrdu, language, t } = useLanguage();
  const {
    patient,
    nextCall,
    nextCallLoading,
    refreshNextCall,
    secondsUntilNext,
    calls,
    callsLoading,
    refreshCalls,
    callMedicationNow,
    activeCallPhase,
    activeCallError,
    clearCallState,
    medications,
  } = useP3();
  const activeMeds = medications.filter((med) => med.active);
  const recentCall = calls[0] ?? null;
  const patientName = patient?.name ?? t('settings.patient');
  const rtl = isUrdu ? styles.rtlText : undefined;

  const formatCountdown = (seconds: number | null) => {
    if (seconds === null || seconds <= 0) return t('home.dueNow');
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours > 0) return `${t('home.hours', { value: hours })} ${t('home.minutes', { value: minutes })}`;
    if (minutes > 0) return t('home.minutes', { value: minutes });
    return t('home.seconds', { value: seconds });
  };

  const formatTime = (iso: string) => {
    try {
      return new Date(iso).toLocaleTimeString(language === 'ur' ? 'ur-PK' : 'en-PK', {
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return iso;
    }
  };

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
      // P3Context exposes the call error below the action.
    }
  }, [nextCall, callMedicationNow, refreshCalls, clearCallState]);

  const isCalling = activeCallPhase === 'calling';

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <DawaHeader title="SehatCall" subtitle={t('home.subtitle', { name: patientName })} />
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={nextCallLoading || callsLoading}
            onRefresh={onRefresh}
            tintColor={ui.primary}
          />
        }
      >
        <Text style={[styles.sectionLabel, rtl]}>{t('home.next')}</Text>
        {nextCall ? (
          <View style={styles.primaryPanel}>
            <View style={[styles.topRow, isUrdu && styles.rowRtl]}>
              <View style={styles.medInfo}>
                <Text style={[styles.medName, rtl]}>{nextCall.nickname || nextCall.clinicalName}</Text>
                <Text style={[styles.secondary, rtl]}>{nextCall.clinicalName}  {nextCall.dosage}</Text>
                <Text style={[styles.schedule, rtl]}>{t('home.scheduledAt', { time: nextCall.scheduleTime })}</Text>
              </View>
              <View style={styles.countdown}>
                <Text style={[styles.countdownValue, rtl]}>{formatCountdown(secondsUntilNext)}</Text>
                <Text style={[styles.countdownLabel, rtl]}>{t('home.remaining')}</Text>
              </View>
            </View>

            {!nextCall.autoCallEnabled ? (
              <View style={[styles.notice, isUrdu && styles.rowRtl]}>
                <Ionicons name="information-circle-outline" size={18} color={ui.info} />
                <Text style={[styles.noticeText, rtl]}>{t('home.autoOff')}</Text>
              </View>
            ) : null}

            <TouchableOpacity
              style={[styles.primaryButton, isCalling && styles.disabled]}
              onPress={handleCallNow}
              disabled={isCalling}
              activeOpacity={0.75}
              accessibilityRole="button"
            >
              {isCalling ? <ActivityIndicator color={ui.surface} size="small" /> : <Ionicons name="call-outline" size={19} color={ui.surface} />}
              <Text style={[styles.primaryButtonText, rtl]}>
                {isCalling ? t('home.calling', { name: patientName }) : t('home.callNow')}
              </Text>
            </TouchableOpacity>

            {activeCallError ? (
              <View style={styles.errorPanel}>
                <Text style={[styles.errorText, rtl]}>{activeCallError}</Text>
              </View>
            ) : null}
          </View>
        ) : (
          <View style={styles.emptyPanel}>
            <Ionicons name="calendar-outline" size={24} color={ui.muted} />
            <Text style={[styles.emptyTitle, rtl]}>{t('home.noUpcoming')}</Text>
            <Text style={[styles.emptyText, rtl]}>{t('home.noUpcomingBody')}</Text>
          </View>
        )}

        {recentCall ? (
          <View style={styles.section}>
            <Text style={[styles.sectionLabel, rtl]}>{t('home.recent')}</Text>
            <View style={styles.panel}>
              <View style={[styles.topRow, isUrdu && styles.rowRtl]}>
                <Text style={[styles.recentMed, rtl]}>{recentCall.nickname || recentCall.clinicalName}</Text>
                <StatusBadge status={recentCall.callStatus} />
              </View>
              <Text style={[styles.secondary, rtl]}>{formatTime(recentCall.scheduledTime)}</Text>
              <View style={[styles.outcomeRow, isUrdu && styles.rowRtl]}>
                <Text style={[styles.outcomeLabel, rtl]}>{t('home.outcome')}</Text>
                <Text style={[styles.outcomeValue, rtl]}>{t(adherenceKey(recentCall.adherenceOutcome))}</Text>
              </View>
            </View>
          </View>
        ) : null}

        <View style={styles.section}>
          <Text style={[styles.sectionLabel, rtl]}>{t('home.schedule')}</Text>
          <View style={styles.listPanel}>
            {activeMeds.length ? activeMeds.map((med, index) => (
              <View key={med.id} style={[styles.scheduleRow, index > 0 && styles.rowBorder, isUrdu && styles.rowRtl]}>
                <View style={styles.scheduleMarker} />
                <Text style={[styles.scheduleName, rtl]} numberOfLines={1}>{med.nickname || med.clinicalName}</Text>
                <Text style={styles.scheduleValue}>{med.scheduleTime}</Text>
              </View>
            )) : <Text style={[styles.emptyInline, rtl]}>{t('home.noActive')}</Text>}
          </View>
        </View>
      </ScrollView>
    </View>
  );
}

function StatusBadge({ status }: { status: string }) {
  const { isUrdu, t } = useLanguage();
  const statusKey = `status.${status}`;
  const translatedStatus = t(statusKey);
  const tone = status === 'completed' || status === 'answered'
    ? { bg: ui.successSoft, fg: ui.success }
    : status === 'failed'
      ? { bg: ui.dangerSoft, fg: ui.danger }
      : { bg: ui.warningSoft, fg: ui.warning };
  return (
    <View style={[styles.badge, { backgroundColor: tone.bg }]}>
      <Text style={[styles.badgeText, { color: tone.fg }, isUrdu && styles.rtlText]}>
        {translatedStatus === statusKey ? status : translatedStatus}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: ui.canvas },
  scroll: { padding: 16, paddingBottom: 40 },
  section: { marginTop: 28 },
  sectionLabel: { fontFamily: 'Inter_700Bold', fontSize: 16, color: ui.text, marginBottom: 10 },
  primaryPanel: { backgroundColor: ui.surface, borderWidth: 1, borderColor: ui.line, borderRadius: radius.medium, padding: 20 },
  panel: { backgroundColor: ui.surface, borderWidth: 1, borderColor: ui.line, borderRadius: radius.medium, padding: 18 },
  listPanel: { backgroundColor: ui.surface, borderWidth: 1, borderColor: ui.line, borderRadius: radius.medium, paddingHorizontal: 16 },
  topRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  rowRtl: { flexDirection: 'row-reverse' },
  medInfo: { flex: 1 },
  medName: { fontFamily: 'Inter_700Bold', fontSize: 24, lineHeight: 30, color: ui.text },
  secondary: { fontFamily: 'Inter_400Regular', fontSize: 14, lineHeight: 20, color: ui.muted, marginTop: 4 },
  schedule: { fontFamily: 'Inter_600SemiBold', fontSize: 14, color: ui.text, marginTop: 8 },
  countdown: { alignItems: 'center', minWidth: 86 },
  countdownValue: { fontFamily: 'Inter_700Bold', fontSize: 22, color: ui.primary, textAlign: 'center' },
  countdownLabel: { fontFamily: 'Inter_400Regular', fontSize: 11, color: ui.muted, marginTop: 2 },
  notice: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: ui.infoSoft, borderRadius: radius.small, padding: 10, marginTop: 16 },
  noticeText: { flex: 1, fontFamily: 'Inter_400Regular', fontSize: 13, color: ui.info },
  primaryButton: { minHeight: 54, backgroundColor: ui.primary, borderRadius: radius.medium, marginTop: 18, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 9 },
  primaryButtonText: { fontFamily: 'Inter_700Bold', fontSize: 17, color: ui.surface },
  disabled: { opacity: 0.65 },
  errorPanel: { backgroundColor: ui.dangerSoft, borderRadius: radius.small, padding: 10, marginTop: 10 },
  errorText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: ui.danger },
  emptyPanel: { borderWidth: 1, borderColor: ui.line, borderRadius: radius.medium, padding: 24, alignItems: 'center', backgroundColor: ui.surface },
  emptyTitle: { fontFamily: 'Inter_700Bold', fontSize: 19, color: ui.text, marginTop: 12 },
  emptyText: { fontFamily: 'Inter_400Regular', fontSize: 15, lineHeight: 22, color: ui.muted, textAlign: 'center', marginTop: 6, maxWidth: 300 },
  recentMed: { flex: 1, fontFamily: 'Inter_700Bold', fontSize: 19, color: ui.text },
  badge: { borderRadius: radius.small, paddingHorizontal: 9, paddingVertical: 4 },
  badgeText: { fontFamily: 'Inter_600SemiBold', fontSize: 12 },
  outcomeRow: { flexDirection: 'row', justifyContent: 'space-between', borderTopWidth: 1, borderTopColor: ui.line, marginTop: 12, paddingTop: 12, gap: 12 },
  outcomeLabel: { fontFamily: 'Inter_500Medium', fontSize: 14, color: ui.muted },
  outcomeValue: { flex: 1, fontFamily: 'Inter_700Bold', fontSize: 14, color: ui.text, textAlign: 'right' },
  scheduleRow: { minHeight: 58, flexDirection: 'row', alignItems: 'center', gap: 10 },
  rowBorder: { borderTopWidth: 1, borderTopColor: ui.line },
  scheduleMarker: { width: 6, height: 6, borderRadius: 3, backgroundColor: ui.primary },
  scheduleName: { flex: 1, fontFamily: 'Inter_600SemiBold', fontSize: 16, color: ui.text },
  scheduleValue: { fontFamily: 'Inter_700Bold', fontSize: 16, color: ui.primary },
  emptyInline: { fontFamily: 'Inter_400Regular', fontSize: 14, color: ui.muted, paddingVertical: 18 },
  rtlText: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
});

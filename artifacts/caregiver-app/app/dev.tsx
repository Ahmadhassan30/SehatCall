import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useDawa } from '@/context/DawaContext';
import { useLanguage } from '@/context/LanguageContext';
import { useP3 } from '@/context/P3Context';
import { radius, ui } from '@/lib/ui';

function SectionTitle({ children }: { children: React.ReactNode }) {
  const { isUrdu } = useLanguage();
  return <Text style={[styles.sectionTitle, isUrdu && styles.rtlText]}>{children}</Text>;
}

export default function DevScreen() {
  const router = useRouter();
  const dawa = useDawa();
  const p3 = useP3();
  const { isUrdu, t } = useLanguage();
  const [selectedMedicineId, setSelectedMedicineId] = useState('');
  const [delaySeconds, setDelaySeconds] = useState('30');
  const rtl = isUrdu ? styles.rtlText : undefined;

  useEffect(() => {
    if (p3.medications.length && !selectedMedicineId) setSelectedMedicineId(p3.medications[0].id);
  }, [p3.medications, selectedMedicineId]);

  const scheduleCall = async () => {
    if (!p3.medications.some((medicine) => medicine.id === selectedMedicineId)) {
      Alert.alert(t('dev.noMedicine'));
      return;
    }
    const delay = Number.parseInt(delaySeconds, 10);
    if (Number.isNaN(delay) || delay < 15 || delay > 300) {
      Alert.alert(t('dev.invalidDelay'));
      return;
    }
    try {
      await dawa.scheduleDemo(selectedMedicineId, delay);
    } catch (error) {
      Alert.alert(t('dev.failed'), error instanceof Error ? error.message : t('common.tryAgain'));
    }
  };

  const resetDemo = () => {
    Alert.alert(t('dev.reset'), t('dev.resetBody'), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('dev.reset'),
        style: 'destructive',
        onPress: async () => {
          try {
            await dawa.resetDemo();
            await Promise.all([p3.refreshCalls(), p3.refreshNextCall()]);
          } catch (error) {
            Alert.alert(t('dev.failed'), error instanceof Error ? error.message : t('common.tryAgain'));
          }
        },
      },
    ]);
  };

  const requestCall = async () => {
    if (!selectedMedicineId) {
      Alert.alert(t('dev.noMedicine'));
      return;
    }
    try {
      await p3.callMedicationNow(selectedMedicineId);
      Alert.alert(t('dev.dispatched'));
    } catch (error) {
      Alert.alert(t('dev.failed'), error instanceof Error ? error.message : t('common.tryAgain'));
    }
  };

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top']} style={[styles.topBar, isUrdu && styles.rowRtl]}>
        <TouchableOpacity style={styles.iconButton} onPress={() => router.back()} accessibilityLabel={t('common.back')}>
          <Ionicons name={isUrdu ? 'arrow-forward' : 'arrow-back'} size={21} color={ui.text} />
        </TouchableOpacity>
        <Text style={[styles.title, rtl]}>{t('dev.title')}</Text>
        <View style={styles.iconButton} />
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={[styles.warning, isUrdu && styles.rowRtl]}>
          <Ionicons name="warning-outline" size={20} color={ui.warning} />
          <Text style={[styles.warningText, rtl]}>{t('dev.warning')}</Text>
        </View>

        <SectionTitle>{t('dev.medicine')}</SectionTitle>
        <View style={styles.card}>
          {p3.medications.map((medicine, index) => {
            const selected = selectedMedicineId === medicine.id;
            return (
              <TouchableOpacity
                key={medicine.id}
                style={[styles.medicineRow, index > 0 && styles.divider, isUrdu && styles.rowRtl]}
                onPress={() => setSelectedMedicineId(medicine.id)}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected }}
              >
                <View style={styles.medicineInfo}>
                  <Text style={[styles.medicineName, selected && styles.selectedText, rtl]}>{medicine.nickname || medicine.clinicalName}</Text>
                  <Text style={[styles.medicineTime, rtl]}>{medicine.scheduleTime}</Text>
                </View>
                <Ionicons name={selected ? 'radio-button-on' : 'radio-button-off'} size={21} color={selected ? ui.primary : ui.muted} />
              </TouchableOpacity>
            );
          })}
        </View>

        <SectionTitle>{t('dev.manualCall')}</SectionTitle>
        <TouchableOpacity style={[styles.primaryButton, p3.activeCallPhase === 'calling' && styles.disabled]} onPress={requestCall} disabled={p3.activeCallPhase === 'calling'}>
          {p3.activeCallPhase === 'calling' ? <ActivityIndicator color={ui.surface} /> : <Ionicons name="call-outline" size={19} color={ui.surface} />}
          <Text style={[styles.primaryButtonText, rtl]}>{t('dev.callNow')}</Text>
        </TouchableOpacity>
        {p3.activeCallError ? <View style={styles.errorPanel}><Text style={[styles.errorText, rtl]}>{p3.activeCallError}</Text></View> : null}

        <SectionTitle>{t('dev.schedule')}</SectionTitle>
        <View style={styles.card}>
          <Text style={[styles.fieldLabel, rtl]}>{t('dev.delay')}</Text>
          <TextInput style={styles.input} value={delaySeconds} onChangeText={setDelaySeconds} keyboardType="number-pad" placeholderTextColor={ui.muted} />
          <TouchableOpacity style={[styles.secondaryButton, dawa.isScheduling && styles.disabled]} onPress={scheduleCall} disabled={dawa.isScheduling}>
            {dawa.isScheduling ? <ActivityIndicator color={ui.primary} /> : <Ionicons name="time-outline" size={19} color={ui.primary} />}
            <Text style={[styles.secondaryButtonText, rtl]}>{t('dev.scheduleAction')}</Text>
          </TouchableOpacity>
          {dawa.scheduleError ? <View style={styles.errorPanel}><Text style={[styles.errorText, rtl]}>{dawa.scheduleError}</Text></View> : null}
          {dawa.scheduledCall ? (
            <View style={styles.infoPanel}>
              <Text style={[styles.infoText, rtl]}>
                {t('dev.scheduled')}  {dawa.scheduledCall.callStatus}
                {dawa.countdownSeconds !== null && dawa.countdownSeconds > 0 ? `  ${t('dev.remaining', { seconds: dawa.countdownSeconds })}` : ''}
              </Text>
            </View>
          ) : null}
        </View>

        <SectionTitle>{t('dev.reset')}</SectionTitle>
        <TouchableOpacity style={[styles.dangerButton, dawa.isResetting && styles.disabled]} onPress={resetDemo} disabled={dawa.isResetting}>
          {dawa.isResetting ? <ActivityIndicator color={ui.danger} /> : <Ionicons name="trash-outline" size={19} color={ui.danger} />}
          <Text style={[styles.dangerButtonText, rtl]}>{t('dev.reset')}</Text>
        </TouchableOpacity>
        {dawa.resetError ? <View style={styles.errorPanel}><Text style={[styles.errorText, rtl]}>{dawa.resetError}</Text></View> : null}

        <SectionTitle>{t('dev.backend')}</SectionTitle>
        <View style={styles.card}>
          {[
            [t('dev.apiUrl'), dawa.apiBaseUrl || t('dev.notSet')],
            [t('dev.patient'), p3.patient?.name ?? t('dev.notLoaded')],
            [t('dev.medicines'), String(p3.medications.length)],
            [t('dev.callPhase'), p3.activeCallPhase],
            [t('dev.recentCalls'), String(p3.calls.length)],
          ].map(([label, value], index) => (
            <View key={label} style={[styles.statusRow, index > 0 && styles.divider, isUrdu && styles.rowRtl]}>
              <Text style={[styles.statusLabel, rtl]}>{label}</Text>
              <Text style={[styles.statusValue, rtl]} numberOfLines={1}>{value}</Text>
            </View>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: ui.canvas },
  topBar: { minHeight: 58, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingBottom: 8, backgroundColor: ui.surface, borderBottomWidth: 1, borderBottomColor: ui.line },
  rowRtl: { flexDirection: 'row-reverse' },
  iconButton: { width: 40, height: 40, borderRadius: radius.medium, alignItems: 'center', justifyContent: 'center' },
  title: { flex: 1, fontFamily: 'Inter_700Bold', fontSize: 21, color: ui.text, textAlign: 'center', marginHorizontal: 10 },
  scroll: { padding: 16, paddingBottom: 60 },
  warning: { flexDirection: 'row', alignItems: 'flex-start', gap: 9, backgroundColor: ui.warningSoft, borderLeftWidth: 3, borderLeftColor: ui.warning, borderRadius: radius.medium, padding: 12 },
  warningText: { flex: 1, fontFamily: 'Inter_400Regular', fontSize: 13, lineHeight: 19, color: ui.warning },
  sectionTitle: { fontFamily: 'Inter_700Bold', fontSize: 16, color: ui.text, marginTop: 28, marginBottom: 10 },
  card: { backgroundColor: ui.surface, borderWidth: 1, borderColor: ui.line, borderRadius: radius.medium, paddingHorizontal: 16, paddingVertical: 8 },
  medicineRow: { minHeight: 58, flexDirection: 'row', alignItems: 'center', gap: 12 },
  divider: { borderTopWidth: 1, borderTopColor: ui.line },
  medicineInfo: { flex: 1 },
  medicineName: { fontFamily: 'Inter_600SemiBold', fontSize: 16, color: ui.text },
  selectedText: { fontFamily: 'Inter_700Bold', color: ui.primary },
  medicineTime: { fontFamily: 'Inter_400Regular', fontSize: 12, color: ui.muted, marginTop: 2 },
  primaryButton: { minHeight: 48, borderRadius: radius.medium, backgroundColor: ui.primary, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  primaryButtonText: { fontFamily: 'Inter_700Bold', fontSize: 16, color: ui.surface },
  secondaryButton: { minHeight: 46, borderRadius: radius.medium, borderWidth: 1, borderColor: ui.primary, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, marginBottom: 8 },
  secondaryButtonText: { fontFamily: 'Inter_600SemiBold', fontSize: 14, color: ui.primary },
  dangerButton: { minHeight: 46, borderRadius: radius.medium, borderWidth: 1, borderColor: ui.danger, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  dangerButtonText: { fontFamily: 'Inter_600SemiBold', fontSize: 14, color: ui.danger },
  disabled: { opacity: 0.6 },
  fieldLabel: { fontFamily: 'Inter_500Medium', fontSize: 13, color: ui.muted, marginTop: 10, marginBottom: 6 },
  input: { minHeight: 46, fontFamily: 'Inter_400Regular', fontSize: 15, color: ui.text, borderWidth: 1, borderColor: ui.line, borderRadius: radius.medium, paddingHorizontal: 12, backgroundColor: ui.canvas, marginBottom: 10 },
  errorPanel: { backgroundColor: ui.dangerSoft, borderRadius: radius.small, padding: 10, marginTop: 8 },
  errorText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: ui.danger },
  infoPanel: { backgroundColor: ui.infoSoft, borderRadius: radius.small, padding: 10, marginVertical: 8 },
  infoText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: ui.info },
  statusRow: { minHeight: 48, flexDirection: 'row', alignItems: 'center', gap: 12 },
  statusLabel: { flex: 1, fontFamily: 'Inter_400Regular', fontSize: 13, color: ui.muted },
  statusValue: { flex: 1, fontFamily: 'Inter_500Medium', fontSize: 13, color: ui.text, textAlign: 'right' },
  rtlText: { fontFamily: undefined, textAlign: 'right', writingDirection: 'rtl' },
});

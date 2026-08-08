/**
 * Developer tools — demo call dispatch, VMR tester, demo reset.
 *
 * Deliberately de-emphasised: not in the tab bar, only reachable from Settings.
 * The production four-tab UI is kept clean.
 */
import React, { useState } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  TextInput,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import { useDawa } from '@/context/DawaContext';
import { useP3 } from '@/context/P3Context';

const C = {
  cream: '#F7F3E8',
  blue: '#6F9FB5',
  navy: '#243642',
  white: '#FFFFFF',
  border: '#D8D0BC',
  muted: '#7A8A8E',
  err: '#B83232',
  errBg: '#FDEAEA',
  warn: '#C97B2A',
};

export default function DevScreen() {
  const router = useRouter();
  const dawa = useDawa();
  const p3 = useP3();
  const medications = p3.medications;

  const [selectedMedId, setSelectedMedId] = useState<string>('');
  const [delaySeconds, setDelaySeconds] = useState('30');

  React.useEffect(() => {
    if (medications.length && !selectedMedId) {
      setSelectedMedId(medications[0].id);
    }
  }, [medications]);

  const handleSchedule = async () => {
    const med = medications.find((m) => m.id === selectedMedId);
    if (!med) { Alert.alert('No medication selected'); return; }
    const delay = parseInt(delaySeconds, 10);
    if (isNaN(delay) || delay < 15 || delay > 300) {
      Alert.alert('Delay must be 15–300 seconds');
      return;
    }
    try {
      await dawa.scheduleDemo(selectedMedId, delay);
    } catch (e) {
      Alert.alert('Error', e instanceof Error ? e.message : 'Unknown');
    }
  };

  const handleReset = async () => {
    Alert.alert(
      'Reset demo data',
      'This clears all call records. Medication data is preserved.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reset',
          style: 'destructive',
          onPress: async () => {
            try {
              await dawa.resetDemo();
              await p3.refreshCalls();
              await p3.refreshNextCall();
            } catch (e) {
              Alert.alert('Reset failed', e instanceof Error ? e.message : 'Unknown');
            }
          },
        },
      ]
    );
  };

  const handleManualCall = async () => {
    if (!selectedMedId) { Alert.alert('No medication selected'); return; }
    try {
      await p3.callMedicationNow(selectedMedId);
      Alert.alert('Dispatched', 'Call sent via DAWA.');
    } catch (e) {
      Alert.alert('Failed', e instanceof Error ? e.message : 'Unknown');
    }
  };

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top']} style={styles.topBar}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
          <Text style={styles.backText}>Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>Developer Tools</Text>
        <View style={{ minWidth: 60 }} />
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.warningBanner}>
          <Text style={styles.warningText}>
            This screen is for testing only. Actions here place real calls and modify demo state.
          </Text>
        </View>

        {/* ── Medication selector ──────────────────────────────── */}
        <Text style={styles.sectionTitle}>MEDICATION</Text>
        {medications.map((med) => (
          <TouchableOpacity
            key={med.id}
            style={[styles.medOption, selectedMedId === med.id && styles.medOptionSelected]}
            onPress={() => setSelectedMedId(med.id)}
          >
            <Text style={[styles.medOptionText, selectedMedId === med.id && styles.medOptionTextSelected]}>
              {med.nickname || med.clinicalName} — {med.scheduleTime}
            </Text>
          </TouchableOpacity>
        ))}

        {/* ── Manual call now ───────────────────────────────────── */}
        <Text style={styles.sectionTitle}>MANUAL CALL</Text>
        <TouchableOpacity
          style={[styles.btn, styles.btnBlue, p3.activeCallPhase === 'calling' && styles.btnDisabled]}
          onPress={handleManualCall}
          disabled={p3.activeCallPhase === 'calling'}
        >
          {p3.activeCallPhase === 'calling'
            ? <ActivityIndicator color={C.white} size="small" />
            : <Text style={styles.btnText}>Call now</Text>
          }
        </TouchableOpacity>
        {p3.activeCallError ? (
          <View style={styles.errBanner}><Text style={styles.errText}>{p3.activeCallError}</Text></View>
        ) : null}

        {/* ── Schedule demo call ────────────────────────────────── */}
        <Text style={styles.sectionTitle}>SCHEDULE DEMO CALL</Text>
        <Text style={styles.fieldLabel}>Delay (seconds, 15–300)</Text>
        <TextInput
          style={styles.input}
          value={delaySeconds}
          onChangeText={setDelaySeconds}
          keyboardType="number-pad"
          placeholderTextColor={C.muted}
        />
        <TouchableOpacity
          style={[styles.btn, styles.btnBlue, dawa.isScheduling && styles.btnDisabled]}
          onPress={handleSchedule}
          disabled={dawa.isScheduling}
        >
          {dawa.isScheduling
            ? <ActivityIndicator color={C.white} size="small" />
            : <Text style={styles.btnText}>Schedule call</Text>
          }
        </TouchableOpacity>
        {dawa.scheduleError ? (
          <View style={styles.errBanner}><Text style={styles.errText}>{dawa.scheduleError}</Text></View>
        ) : null}
        {dawa.scheduledCall ? (
          <View style={styles.infoBanner}>
            <Text style={styles.infoText}>
              Scheduled: {dawa.scheduledCall.callStatus}
              {dawa.countdownSeconds !== null && dawa.countdownSeconds > 0
                ? ` — ${dawa.countdownSeconds}s remaining`
                : ''}
            </Text>
          </View>
        ) : null}

        {/* ── Reset ────────────────────────────────────────────── */}
        <Text style={styles.sectionTitle}>DEMO RESET</Text>
        <TouchableOpacity
          style={[styles.btn, styles.btnReset, dawa.isResetting && styles.btnDisabled]}
          onPress={handleReset}
          disabled={dawa.isResetting}
        >
          {dawa.isResetting
            ? <ActivityIndicator color={C.white} size="small" />
            : <Text style={styles.btnText}>Reset demo data</Text>
          }
        </TouchableOpacity>
        {dawa.resetError ? (
          <View style={styles.errBanner}><Text style={styles.errText}>{dawa.resetError}</Text></View>
        ) : null}

        {/* ── Backend state ─────────────────────────────────────── */}
        <Text style={styles.sectionTitle}>BACKEND STATUS</Text>
        <View style={styles.statusCard}>
          <Text style={styles.statusRow}>API URL: {dawa.apiBaseUrl || '(not set)'}</Text>
          <Text style={styles.statusRow}>Patient: {p3.patient?.name ?? 'not loaded'}</Text>
          <Text style={styles.statusRow}>Medications: {p3.medications.length}</Text>
          <Text style={styles.statusRow}>Call phase: {p3.activeCallPhase}</Text>
          <Text style={styles.statusRow}>Recent calls: {p3.calls.length}</Text>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.cream },
  topBar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingBottom: 12, backgroundColor: C.cream, borderBottomWidth: 1, borderBottomColor: C.border },
  backBtn: { padding: 4, minWidth: 60 },
  backText: { fontFamily: 'Inter_400Regular', fontSize: 16, color: C.blue },
  title: { fontFamily: 'Inter_700Bold', fontSize: 17, color: C.navy },
  scroll: { padding: 20, paddingBottom: 60 },

  warningBanner: { backgroundColor: '#FDF3E3', borderRadius: 10, padding: 14, marginBottom: 20, borderLeftWidth: 3, borderLeftColor: C.warn },
  warningText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.warn, lineHeight: 18 },

  sectionTitle: { fontFamily: 'Inter_600SemiBold', fontSize: 11, color: C.muted, letterSpacing: 1.1, marginTop: 20, marginBottom: 10 },

  medOption: { padding: 14, borderRadius: 10, borderWidth: 1, borderColor: C.border, marginBottom: 8, backgroundColor: C.white },
  medOptionSelected: { borderColor: C.blue, backgroundColor: '#EDF4F8' },
  medOptionText: { fontFamily: 'Inter_400Regular', fontSize: 14, color: C.navy },
  medOptionTextSelected: { fontFamily: 'Inter_600SemiBold', color: C.blue },

  fieldLabel: { fontFamily: 'Inter_500Medium', fontSize: 13, color: C.muted, marginBottom: 6 },
  input: { fontFamily: 'Inter_400Regular', fontSize: 16, color: C.navy, borderWidth: 1, borderColor: C.border, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12, backgroundColor: C.white, marginBottom: 12 },

  btn: { borderRadius: 12, paddingVertical: 14, alignItems: 'center', marginBottom: 8 },
  btnBlue: { backgroundColor: C.blue },
  btnReset: { backgroundColor: '#A04040' },
  btnDisabled: { opacity: 0.6 },
  btnText: { fontFamily: 'Inter_600SemiBold', fontSize: 16, color: C.white },

  errBanner: { backgroundColor: C.errBg, borderRadius: 8, padding: 10, marginBottom: 8, borderLeftWidth: 2, borderLeftColor: C.err },
  errText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.err },
  infoBanner: { backgroundColor: '#EDF4F8', borderRadius: 8, padding: 10, marginBottom: 8 },
  infoText: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.blue },

  statusCard: { backgroundColor: C.white, borderRadius: 12, padding: 16, gap: 6 },
  statusRow: { fontFamily: 'Inter_400Regular', fontSize: 13, color: C.muted },
});
